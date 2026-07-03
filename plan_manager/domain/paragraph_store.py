"""Storage of HRS binding paragraphs (MRS concept C-002).

Wholesale replace/read operations against the paragraph table. The
paragraph set of a plan is always replaced wholesale from a freshly
parsed document: delete_paragraphs then insert_paragraphs. The server
never authors or rewrites paragraph prose; these functions only persist
already-labeled Paragraph objects.
"""
import uuid

import psycopg

from plan_manager.domain.paragraph import Paragraph


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
) -> None:
    """Insert a plan's binding paragraphs as new paragraph rows.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan; stored in each inserted
            row's plan_uuid column.
        paragraphs: The binding paragraphs to store. Every element must
            have a non-None label field (only binding paragraphs, all
            of which are labeled, are ever stored as paragraph rows).

    Returns:
        None.

    Raises:
        ValueError: if any paragraph in paragraphs has label equal to
            None. The message is exactly "paragraph has no label".
    """
    for paragraph in paragraphs:
        if paragraph.label is None:
            raise ValueError("paragraph has no label")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO paragraph (uuid, plan_uuid, label, text, position) "
                "VALUES (%s, %s, %s, %s, %s)",
                (uuid.uuid4(), plan_uuid, paragraph.label, paragraph.text, paragraph.position),
            )


def list_paragraphs(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> list[Paragraph]:
    """List a plan's stored binding paragraphs in document order.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The uuid of the owning plan; only rows whose
            plan_uuid column equals this value are returned.

    Returns:
        A list of Paragraph objects, one per stored paragraph row for
        this plan, ordered by the paragraph table's position column
        ascending. Each Paragraph is constructed with label set to the
        row's label column, text set to the row's text column, and
        position set to the row's position column.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT label, text, position FROM paragraph WHERE plan_uuid = %s ORDER BY position",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [Paragraph(label=row[0], text=row[1], position=row[2]) for row in rows]
