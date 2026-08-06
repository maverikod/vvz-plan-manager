"""Storage of HRS binding paragraphs (MRS concept C-002).

Wholesale replace/read operations against the paragraph table (the
paragraph set of a plan is replaced wholesale from a freshly parsed
document: delete_paragraphs then insert_paragraphs) plus targeted
single-row primitives (insert_paragraph_at, update_paragraph_text,
delete_paragraph, shift_positions) used by the paragraph-granular
editing commands. The server never authors or rewrites paragraph prose
on its own; these functions only persist already-validated content.
"""
import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.entity import DataclassEntity


class _ParagraphRow(DataclassEntity):
    """Table-bound write seat for paragraph rows (CR-7 G-004).

    The Paragraph domain class deliberately stays table-unbound
    (TABLE_NAME=None); this seat routes the store's row writes through the
    unified engine. ENTITY_TYPE=None keeps it out of the catalog's
    entity-type resolver; guard calls name the audit type explicitly.
    """

    ENTITY_TYPE = None
    REGISTER_IDENTITY = False  # Identity for paragraph rows is registered by the DB trigger; the seat carries ENTITY_TYPE=None, so Python-side registration would write entity_type NULL (bug 1cbe201e).
    TABLE_NAME = "paragraph"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "plan_uuid", "label", "text", "position", "binding")
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    CREATED_AT_COLUMN = None
    OWNER_COLUMN = "plan_uuid"



@dataclass
class StoredParagraph:
    """Stored HRS paragraph row with immutable database identity.

    ``binding`` is True for a normal binding paragraph and False for one that has been marked
    non-binding by para_mark_non_binding (the row is kept so an unwrap can restore it). Only
    binding rows are surfaced by list_paragraphs and counted by coverage/gate.
    """

    uuid: uuid.UUID
    plan_uuid: uuid.UUID
    label: str | None
    text: str
    position: int
    binding: bool = True


def delete_paragraphs(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Delete every stored paragraph row belonging to one plan.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan; rows where the
            paragraph table's plan_uuid column equals this value are
            deleted.

    Returns:
        None.
    """
    # CR-7 G-004 compatibility note: this is a SET deletion (the plan's whole
    # paragraph collection is replaced in one statement). The single-row engine
    # wrapper cannot express it; the set-wise purge engine of G-006/T-001 owns
    # this shape and adopts it there.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM paragraph WHERE plan_uuid = %s", (plan_uuid,))


def insert_paragraphs(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    paragraphs: list[Paragraph],
) -> list[uuid.UUID]:
    """Insert a plan's binding paragraphs as new paragraph rows.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan; stored in each inserted
            row's plan_uuid column.
        paragraphs: The binding paragraphs to store. Every element must
            have a non-None label field (only binding paragraphs, all
            of which are labeled, are ever stored as paragraph rows).

    Returns:
        The generated paragraph row UUIDs, in the same order as the input
        paragraphs.

    Raises:
        ValueError: if any paragraph in paragraphs has label equal to
            None. The message is exactly "paragraph has no label".
    """
    row_uuids: list[uuid.UUID] = []
    for paragraph in paragraphs:
        if paragraph.label is None:
            raise ValueError("paragraph has no label")
        row_uuid = uuid.uuid4()
        # CR-7 G-004 (C-005, C-012): delegated to the unified creation path.
        _ParagraphRow.crud_create(
            conn,
            {
                "uuid": row_uuid,
                "plan_uuid": plan_uuid,
                "label": paragraph.label,
                "text": paragraph.text,
                "position": paragraph.position,
            },
            returning=False,
        )
        row_uuids.append(row_uuid)
    return row_uuids


def list_paragraphs(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> list[StoredParagraph]:
    """List a plan's stored binding paragraphs in document order.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan; only rows whose
            plan_uuid column equals this value are returned.

    Returns:
        A list of StoredParagraph objects, one per stored paragraph row
        for this plan, ordered by the paragraph table's position column
        ascending.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid, plan_uuid, label, text, position "
            "FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE ORDER BY position",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [
        StoredParagraph(
            uuid=row[0],
            plan_uuid=row[1],
            label=row[2],
            text=row[3],
            position=row[4],
            binding=True,
        )
        for row in rows
    ]


def list_all_paragraphs(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> list[StoredParagraph]:
    """List every stored paragraph row of a plan, binding AND non-binding.

    Unlike list_paragraphs (which surfaces only binding rows), this returns
    the full physical row set in position order. The targeted-editing
    operations need it because the position column is a single sequence over
    ALL rows: a wrapped (non-binding) row keeps its position, so position
    shifts on insert/delete must move non-binding rows too, and label
    uniqueness must be checked against labels held by wrapped rows (an
    unwrap restores them into the binding set).

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan.

    Returns:
        A list of StoredParagraph objects, one per stored row for this
        plan, ordered by the position column ascending.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid, plan_uuid, label, text, position, binding "
            "FROM paragraph WHERE plan_uuid = %s ORDER BY position",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [
        StoredParagraph(
            uuid=row[0],
            plan_uuid=row[1],
            label=row[2],
            text=row[3],
            position=row[4],
            binding=row[5],
        )
        for row in rows
    ]


def insert_paragraph_at(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    label: str,
    text: str,
    position: int,
) -> uuid.UUID:
    """Insert one new binding paragraph row at an already-vacated position.

    The caller is responsible for shifting existing rows (shift_positions)
    before the insert so the position is free; this function only writes
    the row.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan.
        label: The paragraph's four-character base36 label (never None:
            only labeled binding paragraphs are inserted this way).
        text: The paragraph's prose text without any "{xxxx} " prefix.
        position: The row's position value.

    Returns:
        The generated paragraph row UUID.
    """
    row_uuid = uuid.uuid4()
    # CR-7 G-004 (C-005, C-012): delegated to the unified creation path.
    _ParagraphRow.crud_create(
        conn,
        {
            "uuid": row_uuid,
            "plan_uuid": plan_uuid,
            "label": label,
            "text": text,
            "position": position,
            "binding": True,
        },
        returning=False,
    )
    return row_uuid


def update_paragraph_text(
    conn: psycopg.Connection, row_uuid: uuid.UUID, text: str
) -> None:
    """Replace the text of one paragraph row in place (uuid, label, position, binding kept)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE paragraph SET text = %s WHERE uuid = %s",
            (text, row_uuid),
        )


def delete_paragraph(conn: psycopg.Connection, row_uuid: uuid.UUID) -> None:
    """Delete one paragraph row by its uuid."""
    # CR-7 G-004 (C-005, C-012): removal goes through the guarded engine wrapper.
    _ParagraphRow.crud_hard_delete(
        conn,
        row_uuid,
        require_soft_deleted=False,
        returning=False,
        audit_entity_type="paragraph",
    )


def shift_positions(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    start_position: int,
    delta: int,
) -> None:
    """Shift the position of every row (any binding flag) at or after start_position by delta.

    Non-binding rows shift together with binding ones: the position column
    is one sequence over all rows, and a wrapped row must keep its place in
    that sequence so a later unwrap restores it where it belongs.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE paragraph SET position = position + %s "
            "WHERE plan_uuid = %s AND position >= %s",
            (delta, plan_uuid, start_position),
        )


def get_paragraph_at_position(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    position: int,
    *,
    binding: bool,
) -> StoredParagraph | None:
    """Return the paragraph row at ``position`` with the given binding flag, or None.

    Unlike list_paragraphs (which surfaces only binding rows), this looks up a single row by
    position AND binding state so para_mark_non_binding can find the binding row to wrap or the
    non-binding row to unwrap.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The owning plan.
        position: The paragraph position to look up.
        binding: Whether to match the binding (True) or non-binding (False) row at that position.

    Returns:
        The matching StoredParagraph, or None when no such row exists.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid, plan_uuid, label, text, position, binding "
            "FROM paragraph WHERE plan_uuid = %s AND position = %s AND binding = %s",
            (plan_uuid, position, binding),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return StoredParagraph(
        uuid=row[0],
        plan_uuid=row[1],
        label=row[2],
        text=row[3],
        position=row[4],
        binding=row[5],
    )


def set_paragraph_binding(
    conn: psycopg.Connection, row_uuid: uuid.UUID, binding: bool
) -> None:
    """Set the binding flag of one paragraph row (wrap sets False, unwrap sets True)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE paragraph SET binding = %s WHERE uuid = %s",
            (binding, row_uuid),
        )
