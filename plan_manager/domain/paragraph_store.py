"""Storage of HRS binding paragraphs (MRS concept C-002).

Wholesale replace/read operations against the paragraph table. The
paragraph set of a plan is always replaced wholesale from a freshly
parsed document: delete_paragraphs then insert_paragraphs. The server
never authors or rewrites paragraph prose; these functions only persist
already-labeled Paragraph objects.
"""
import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.paragraph import Paragraph


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
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO paragraph (uuid, plan_uuid, label, text, position) "
                "VALUES (%s, %s, %s, %s, %s)",
                (row_uuid, plan_uuid, paragraph.label, paragraph.text, paragraph.position),
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
