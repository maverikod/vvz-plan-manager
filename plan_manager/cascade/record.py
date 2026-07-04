"""Cascade record entity: lifecycle states and database operations for the cascade table."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg


CASCADE_STATUSES: frozenset[str] = frozenset({"open", "committed", "aborted"})


class CascadeError(ValueError):
    """Raised on any cascade lifecycle violation."""


@dataclass(frozen=True)
class CascadeRecord:
    """A cascade record: one row of the cascade table.

    Fields, in order: uuid (the cascade's own identity), plan_uuid (the
    owning plan), name (the cascade reference name held in the version
    store, "cascade/<cascade uuid>"), base_revision_uuid (the plan head
    revision the cascade was anchored at when opened, or None),
    status (one of the three values in CASCADE_STATUSES), created_at
    (creation timestamp).
    """

    uuid: uuid.UUID
    plan_uuid: uuid.UUID
    name: str
    base_revision_uuid: uuid.UUID | None
    status: str
    created_at: datetime


def insert_cascade(conn: psycopg.Connection, record: CascadeRecord) -> None:
    """Insert a cascade record into the cascade table.

    Executes an INSERT into the normative `cascade` table with columns
    (uuid, plan_uuid, name, base_revision_uuid, status, created_at), using
    the corresponding fields of `record` as the six parameter values, in
    that column order.

    Raises CascadeError("plan already has an open cascade") if the insert
    violates the database's partial unique index on (plan_uuid) WHERE
    status = 'open' (a psycopg.errors.UniqueViolation), because that index
    allows at most one open cascade per plan.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cascade (uuid, plan_uuid, name, base_revision_uuid, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    record.uuid,
                    record.plan_uuid,
                    record.name,
                    record.base_revision_uuid,
                    record.status,
                    record.created_at,
                ),
            )
    except psycopg.errors.UniqueViolation:
        raise CascadeError("plan already has an open cascade")


def get_open_cascade(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> CascadeRecord | None:
    """Return the open cascade record for a plan, or None if there is none.

    Executes a SELECT of columns (uuid, plan_uuid, name, base_revision_uuid,
    status, created_at) from the `cascade` table filtered to
    `plan_uuid = %s AND status = 'open'`, fetches at most one row, and
    returns it as a CascadeRecord, or None when no row is found.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid, plan_uuid, name, base_revision_uuid, status, created_at "
            "FROM cascade WHERE plan_uuid = %s AND status = 'open'",
            (plan_uuid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return CascadeRecord(
        uuid=row[0],
        plan_uuid=row[1],
        name=row[2],
        base_revision_uuid=row[3],
        status=row[4],
        created_at=row[5],
    )


def close_cascade(conn: psycopg.Connection, cascade_uuid: uuid.UUID, status: str) -> None:
    """Close an open cascade by transitioning it to a terminal status.

    `status` must be either "committed" or "aborted"; any other value
    raises CascadeError. Executes an UPDATE of the `cascade` table setting
    `status` to the given value where `uuid = %s AND status = 'open'`. If
    no row was updated (cur.rowcount == 0), raises
    CascadeError("no open cascade with this uuid").
    """
    if status not in ("committed", "aborted"):
        raise CascadeError('status must be "committed" or "aborted"')
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cascade SET status = %s WHERE uuid = %s AND status = 'open'",
            (status, cascade_uuid),
        )
        if cur.rowcount == 0:
            raise CascadeError("no open cascade with this uuid")
