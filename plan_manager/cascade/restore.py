"""Row restoration from the version store for cascade abort (C-018, C-035)."""

import uuid

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.cascade.record import CascadeError
from plan_manager.storage.version_ops import diff, state_at

from plan_manager.domain.entity import DataclassEntity


class _RestoreSeat(DataclassEntity):
    """Shared traits of the uuid-keyed restore seats (CR-7 G-004).

    Restore re-creates rows with their ORIGINAL identities, so writes go
    through the engine's recovery/import admission. Registry entries are
    retained across a cascade abort by design, so the engine's Python-side
    registration stays off; ENTITY_TYPE=None keeps the seats out of the
    catalog's entity-type resolver.
    """

    ENTITY_TYPE = None
    ID_COLUMN = "uuid"
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    CREATED_AT_COLUMN = None
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "plan_uuid"


class _StepRestoreRow(_RestoreSeat):
    TABLE_NAME = "step"
    COLUMNS = ("uuid", "plan_uuid", "parent_step_uuid", "level", "step_id",
               "slug", "fields", "depends_on", "concepts", "project_id", "status")


class _ConceptRestoreRow(_RestoreSeat):
    TABLE_NAME = "concept"
    COLUMNS = ("uuid", "plan_uuid", "concept_id", "name", "definition",
               "properties", "source_labels")


class _RelationRestoreRow(_RestoreSeat):
    TABLE_NAME = "relation"
    COLUMNS = ("uuid", "plan_uuid", "from_concept", "to_concept", "type")


class _ParagraphRestoreRow(_RestoreSeat):
    TABLE_NAME = "paragraph"
    COLUMNS = ("uuid", "plan_uuid", "label", "text", "position", "binding")


def _restore_row(conn, seat, node_uuid, values):
    """Write one snapshot row through the engine (create-or-update).

    The legacy statement was a single upsert; the engine expresses the same
    outcome as the recovery-flavoured create for an absent row and a plain
    engine update for a present one.
    """
    exists = conn.execute(
        f'SELECT 1 FROM {seat.TABLE_NAME} WHERE uuid = %s', (node_uuid,)
    ).fetchone()
    if exists is None:
        seat.crud_create(
            conn, {"uuid": node_uuid, **values},
            returning=False, recovery_mode=True, admit_original_timestamps=True,
        )
    else:
        seat.crud_update(conn, node_uuid, dict(values), returning=False)



def node_version_content(conn: psycopg.Connection, version_uuid: uuid.UUID) -> dict:
    """Fetch the content snapshot of a single node version.

    Executes ``SELECT content FROM node_version WHERE uuid = %s`` with
    ``version_uuid`` bound as the sole parameter, fetches at most one row
    via ``fetchone()``, and returns that row's ``content`` column value (a
    dict). If no row is found, raises ``CascadeError("node version not
    found")``.

    :param conn: open psycopg 3 database connection.
    :param version_uuid: UUID primary key of the node_version row to fetch.
    :return: the ``content`` dict stored on that node_version row.
    :raises CascadeError: when no node_version row has the given uuid.
    """
    cur = conn.execute(
        "SELECT content FROM node_version WHERE uuid = %s", (version_uuid,)
    )
    row = cur.fetchone()
    if row is None:
        raise CascadeError("node version not found")
    return row[0]


def apply_snapshot(conn: psycopg.Connection, node_uuid: uuid.UUID, snapshot: dict) -> None:
    """Upsert one working row from a recorded node snapshot.

    Routes on ``snapshot["kind"]`` to the matching table and performs an
    ``INSERT ... ON CONFLICT (uuid) DO UPDATE`` so the working row for
    ``node_uuid`` matches the snapshot content exactly, whether or not a
    row currently exists.

    Supported kinds and their non-uuid columns, all read from ``snapshot``
    by key:

    - ``"step"``: plan_uuid, parent_step_uuid, level, step_id, slug,
      fields (wrapped in ``psycopg.types.json.Jsonb``), depends_on,
      concepts, project_id, status.
    - ``"concept"``: plan_uuid, concept_id, name, definition, properties,
      source_labels.
    - ``"relation"``: plan_uuid, from_concept, to_concept, type.
    - ``"paragraph"``: plan_uuid, label, text, position, binding
      (defaulting to True when absent from an older snapshot).

    :param conn: open psycopg 3 database connection.
    :param node_uuid: uuid of the node whose working row is being written;
        used as the row's ``uuid`` column value.
    :param snapshot: full node snapshot dict as read from a node_version's
        ``content`` column; must carry key ``"kind"``.
    :raises CascadeError: when ``snapshot["kind"]`` is not one of
        "step", "concept", "relation", "paragraph".
    """
    kind = snapshot["kind"]
    # CR-7 G-004 (C-005, C-012): delegated to the unified engine's
    # recovery/import path; this module no longer composes INSERT SQL.
    if kind == "step":
        _restore_row(conn, _StepRestoreRow, node_uuid, {
            "plan_uuid": snapshot["plan_uuid"],
            "parent_step_uuid": snapshot["parent_step_uuid"],
            "level": snapshot["level"],
            "step_id": snapshot["step_id"],
            "slug": snapshot["slug"],
            "fields": Jsonb(snapshot["fields"]),
            "depends_on": snapshot["depends_on"],
            "concepts": snapshot["concepts"],
            "project_id": snapshot.get("project_id"),
            "status": snapshot["status"],
        })
    elif kind == "concept":
        _restore_row(conn, _ConceptRestoreRow, node_uuid, {
            "plan_uuid": snapshot["plan_uuid"],
            "concept_id": snapshot["concept_id"],
            "name": snapshot["name"],
            "definition": snapshot["definition"],
            "properties": snapshot["properties"],
            "source_labels": snapshot["source_labels"],
        })
    elif kind == "relation":
        _restore_row(conn, _RelationRestoreRow, node_uuid, {
            "plan_uuid": snapshot["plan_uuid"],
            "from_concept": snapshot["from_concept"],
            "to_concept": snapshot["to_concept"],
            "type": snapshot["type"],
        })
    elif kind == "paragraph":
        # ``binding`` defaults to True for historical snapshots recorded before
        # the flag existed (bug f253b08d).
        _restore_row(conn, _ParagraphRestoreRow, node_uuid, {
            "plan_uuid": snapshot["plan_uuid"],
            "label": snapshot["label"],
            "text": snapshot["text"],
            "position": snapshot["position"],
            "binding": snapshot.get("binding", True),
        })
    else:
        raise CascadeError(f"unknown node snapshot kind: {kind!r}")


def delete_node(conn: psycopg.Connection, node_uuid: uuid.UUID, kind: str) -> None:
    """Delete one working row identified by node uuid and kind.

    :param conn: open psycopg 3 database connection.
    :param node_uuid: uuid of the row to delete from its table.
    :param kind: one of "step", "concept", "relation", "paragraph";
        selects the target table via a fixed literal mapping (the table
        name is never built from external input).
    :raises CascadeError: when ``kind`` is not one of the four supported
        values.
    """
    tables = {
        "step": "step",
        "concept": "concept",
        "relation": "relation",
        "paragraph": "paragraph",
    }
    table = tables.get(kind)
    if table is None:
        raise CascadeError(f"unknown node kind: {kind!r}")
    # CR-7 G-004 compatibility note: this DELETE stays self-composed in this
    # state. Restore removes the SET of rows added since the base revision;
    # the guarded single-row wrapper consults blocking catalog entries
    # (node_version -> step, relation -> concept) that would refuse a mid-abort
    # removal and change cascade_abort's observable behaviour. The set-wise
    # deletion engine of G-006/T-001 adopts this shape.
    conn.execute(f"DELETE FROM {table} WHERE uuid = %s", (node_uuid,))


def _changed_entity_uuid(entry: uuid.UUID | dict) -> uuid.UUID:
    if isinstance(entry, dict):
        return entry["entity_uuid"]
    return entry


def restore_state(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    base_revision_uuid: uuid.UUID,
    tip_revision_uuid: uuid.UUID,
) -> None:
    """Restore working rows to the state recorded at a base revision."""
    base_map = state_at(conn, plan_uuid, base_revision_uuid)
    tip_map = state_at(conn, plan_uuid, tip_revision_uuid)
    d = diff(conn, plan_uuid, base_revision_uuid, tip_revision_uuid)
    changed = [_changed_entity_uuid(entry) for entry in d["changed"]]
    for node in changed + d["removed"]:
        apply_snapshot(conn, node, node_version_content(conn, base_map[node]))
    for node in d["added"]:
        snap = node_version_content(conn, tip_map[node])
        delete_node(conn, node, snap["kind"])
