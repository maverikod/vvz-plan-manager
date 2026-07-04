"""HRS paragraph access and mutation operations.

Read and mutate stored HRS paragraphs (C-002) through the stored-paragraph
primitives in plan_manager.domain.paragraph_store, and record each
mutation's revision attribution through plan_manager.storage.version_store
(direct mode) or plan_manager.cascade.write (cascade mode).

Only binding paragraphs are ever stored: paragraph_store never holds a
non-binding row. This module defines a function named list_paragraphs that
intentionally shadows the module-level function of the same name in
plan_manager.domain.paragraph_store. The store module is imported by module
name (``from plan_manager.domain import paragraph_store``) and its function
is always called qualified as ``paragraph_store.list_paragraphs(...)`` so
this module's own list_paragraphs never recurses into itself.
"""

import uuid

from plan_manager.cascade.record import CascadeRecord
from plan_manager.cascade.write import cascade_write
from plan_manager.domain import paragraph_store
from plan_manager.domain.labeling import assign_missing_labels
from plan_manager.domain.plan import get_plan
from plan_manager.storage.version_store import record_revision


def _paragraph_snapshot(row_uuid: uuid.UUID, plan_uuid: uuid.UUID, row, deleted: bool = False) -> dict:
    snapshot = {
        "kind": "paragraph",
        "uuid": str(row_uuid),
        "plan_uuid": str(plan_uuid),
        "label": row.label,
        "text": row.text,
        "position": row.position,
    }
    if deleted:
        snapshot["deleted"] = True
    return snapshot


def list_paragraphs(conn, plan_uuid: uuid.UUID) -> list[dict]:
    """Return every stored paragraph of a plan in position order.

    Reads all stored binding paragraphs of the plan identified by
    ``plan_uuid`` through
    ``plan_manager.domain.paragraph_store.list_paragraphs(conn, plan_uuid)``
    and projects each row to a dict with keys "label" (str | None),
    "binding" (bool, always True because only binding paragraphs are ever
    stored), "position" (int), and "text" (str). The store function already
    returns rows in position order; this function preserves that order.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :return: list[dict] -- one dict per stored paragraph, in position order.
    """
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    return [
        {
            "label": row.label,
            "binding": True,
            "position": row.position,
            "text": row.text,
        }
        for row in rows
    ]


def get_paragraph(conn, plan_uuid: uuid.UUID, label: str) -> dict | None:
    """Resolve one stored paragraph by its bare label.

    Calls this module's own list_paragraphs(conn, plan_uuid) and returns
    the single dict whose "label" key equals the given bare ``label``
    string. Returns None when no stored paragraph carries that label.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :param label: str, the bare four-character label to resolve.
    :return: dict | None -- the matching paragraph dict, or None.
    """
    for paragraph in list_paragraphs(conn, plan_uuid):
        if paragraph["label"] == label:
            return paragraph
    return None


def assign_labels(
    conn, plan_uuid: uuid.UUID, author: str, cascade: CascadeRecord | None
) -> list[str]:
    """Assign fresh labels to every unlabeled stored binding paragraph."""
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    labeled, new_labels = assign_missing_labels(rows)
    if not new_labels:
        return new_labels

    message = "assign paragraph labels"
    changed = [
        (rows[i].uuid, labeled[i])
        for i in range(len(rows))
        if rows[i].label is None
    ]

    with conn.cursor() as cur:
        for row_uuid, new_row in changed:
            cur.execute(
                "UPDATE paragraph SET label = %s WHERE uuid = %s",
                (new_row.label, row_uuid),
            )

    if cascade is None:
        changes = [
            (row_uuid, _paragraph_snapshot(row_uuid, plan_uuid, new_row))
            for row_uuid, new_row in changed
        ]
        plan = get_plan(conn, plan_uuid)
        record_revision(
            conn,
            plan_uuid,
            author,
            message,
            changes,
            plan.head_revision_uuid,
            ref_name=None,
        )
    else:
        for row_uuid, new_row in changed:
            cascade_write(
                conn,
                plan_uuid,
                cascade,
                row_uuid,
                _paragraph_snapshot(row_uuid, plan_uuid, new_row),
                [],
                author,
                message,
            )

    return new_labels


def set_non_binding(
    conn,
    plan_uuid: uuid.UUID,
    position: int,
    non_binding: bool,
    author: str,
    cascade: CascadeRecord | None,
) -> None:
    """Mark a stored binding paragraph position as non-binding by deleting it."""
    if not non_binding:
        raise ValueError(
            f"no stored block at position {position}: non-binding blocks are not stored"
        )

    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    row = next((candidate for candidate in rows if candidate.position == position), None)
    if row is None:
        raise ValueError(f"no block at position {position}")

    with conn.cursor() as cur:
        cur.execute("DELETE FROM paragraph WHERE uuid = %s", (row.uuid,))

    message = f"remove non-binding paragraph at position {position}"
    snapshot = _paragraph_snapshot(row.uuid, plan_uuid, row, deleted=True)
    if cascade is None:
        plan = get_plan(conn, plan_uuid)
        record_revision(
            conn,
            plan_uuid,
            author,
            message,
            [(row.uuid, snapshot)],
            plan.head_revision_uuid,
            ref_name=None,
        )
    else:
        cascade_write(conn, plan_uuid, cascade, row.uuid, snapshot, [], author, message)
