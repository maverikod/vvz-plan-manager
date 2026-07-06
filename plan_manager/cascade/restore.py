"""Row restoration from the version store for cascade abort (C-018, C-035)."""

import uuid

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.cascade.record import CascadeError
from plan_manager.storage.version_ops import diff, state_at


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
    - ``"paragraph"``: plan_uuid, label, text, position.

    :param conn: open psycopg 3 database connection.
    :param node_uuid: uuid of the node whose working row is being written;
        used as the row's ``uuid`` column value.
    :param snapshot: full node snapshot dict as read from a node_version's
        ``content`` column; must carry key ``"kind"``.
    :raises CascadeError: when ``snapshot["kind"]`` is not one of
        "step", "concept", "relation", "paragraph".
    """
    kind = snapshot["kind"]
    if kind == "step":
        conn.execute(
            "INSERT INTO step "
            "(uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
            "fields, depends_on, concepts, project_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (uuid) DO UPDATE SET "
            "plan_uuid = EXCLUDED.plan_uuid, "
            "parent_step_uuid = EXCLUDED.parent_step_uuid, "
            "level = EXCLUDED.level, "
            "step_id = EXCLUDED.step_id, "
            "slug = EXCLUDED.slug, "
            "fields = EXCLUDED.fields, "
            "depends_on = EXCLUDED.depends_on, "
            "concepts = EXCLUDED.concepts, "
            "project_id = EXCLUDED.project_id, "
            "status = EXCLUDED.status",
            (
                node_uuid,
                snapshot["plan_uuid"],
                snapshot["parent_step_uuid"],
                snapshot["level"],
                snapshot["step_id"],
                snapshot["slug"],
                Jsonb(snapshot["fields"]),
                snapshot["depends_on"],
                snapshot["concepts"],
                snapshot.get("project_id"),
                snapshot["status"],
            ),
        )
    elif kind == "concept":
        conn.execute(
            "INSERT INTO concept "
            "(uuid, plan_uuid, concept_id, name, definition, properties, "
            "source_labels) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (uuid) DO UPDATE SET "
            "plan_uuid = EXCLUDED.plan_uuid, "
            "concept_id = EXCLUDED.concept_id, "
            "name = EXCLUDED.name, "
            "definition = EXCLUDED.definition, "
            "properties = EXCLUDED.properties, "
            "source_labels = EXCLUDED.source_labels",
            (
                node_uuid,
                snapshot["plan_uuid"],
                snapshot["concept_id"],
                snapshot["name"],
                snapshot["definition"],
                snapshot["properties"],
                snapshot["source_labels"],
            ),
        )
    elif kind == "relation":
        conn.execute(
            "INSERT INTO relation "
            "(uuid, plan_uuid, from_concept, to_concept, type) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (uuid) DO UPDATE SET "
            "plan_uuid = EXCLUDED.plan_uuid, "
            "from_concept = EXCLUDED.from_concept, "
            "to_concept = EXCLUDED.to_concept, "
            "type = EXCLUDED.type",
            (
                node_uuid,
                snapshot["plan_uuid"],
                snapshot["from_concept"],
                snapshot["to_concept"],
                snapshot["type"],
            ),
        )
    elif kind == "paragraph":
        conn.execute(
            "INSERT INTO paragraph "
            "(uuid, plan_uuid, label, text, position) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (uuid) DO UPDATE SET "
            "plan_uuid = EXCLUDED.plan_uuid, "
            "label = EXCLUDED.label, "
            "text = EXCLUDED.text, "
            "position = EXCLUDED.position",
            (
                node_uuid,
                snapshot["plan_uuid"],
                snapshot["label"],
                snapshot["text"],
                snapshot["position"],
            ),
        )
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
