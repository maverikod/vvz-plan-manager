"""Cascade record entity: lifecycle states and database operations for the cascade table."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg

from plan_manager.domain.entity import DataclassEntity


CASCADE_STATUSES: frozenset[str] = frozenset({"open", "committed", "aborted"})


class _CascadeRow(DataclassEntity):
    """Descriptor-only seat for the cascade table (CR-7 G-004).

    Exists to route insert_cascade through the unified creation path.
    Identity for cascade rows is registered by the DB trigger, so the
    engine's Python-side registration stays off and the routed create
    keeps the exact single-INSERT statement profile cascade_begin's
    fakes and error mapping (UniqueViolation -> CascadeError) rely on.
    """

    ENTITY_TYPE = "cascade"
    TABLE_NAME = "cascade"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "plan_uuid", "name", "base_revision_uuid", "status", "created_at")
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "plan_uuid"  # a cascade belongs to the plan it mutates


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
        # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
        # engine's creation path; this module no longer composes INSERT SQL.
        _CascadeRow.crud_create(
            conn,
            {
                "uuid": record.uuid,
                "plan_uuid": record.plan_uuid,
                "name": record.name,
                "base_revision_uuid": record.base_revision_uuid,
                "status": record.status,
                "created_at": record.created_at,
            },
            returning=False,
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
