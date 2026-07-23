"""UUID/name identity mechanism for plan_manager storage."""

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.storage.errors import NotFoundError


def new_entity_uuid() -> uuid.UUID:
    """Generate a new immutable primary identity for a stored entity.

    Returns:
        uuid.UUID
            A random UUID (uuid.uuid4()). This is the primary identity
            assigned once at creation time to every row in every table
            listed in ALLOWED_TABLES; it never changes for the lifetime
            of the row.
    """
    return uuid.uuid4()


ALLOWED_TABLES = frozenset(
    {
        "plan",
        "paragraph",
        "concept",
        "relation",
        "step",
        "node_version",
        "revision",
        "ref",
    }
)

ALLOWED_NAME_COLUMNS = frozenset({"concept_id", "step_id", "label", "name"})


def register_entity_identity(
    conn: psycopg.Connection,
    *,
    entity_id: uuid.UUID,
    table_name: str,
    entity_type: str,
    created_at: datetime | None = None,
) -> None:
    """Record the global UUID-to-table mapping for one entity row."""
    conn.execute(
        "INSERT INTO entity_identity (id, table_name, entity_type, created_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (entity_id, table_name, entity_type, created_at or datetime.now(timezone.utc)),
    )


def unregister_entity_identity(conn: psycopg.Connection, entity_id: uuid.UUID) -> None:
    """Remove one global identity mapping after the entity row is physically deleted."""
    conn.execute("DELETE FROM entity_identity WHERE id = %s", (entity_id,))


def resolve_entity_identity(conn: psycopg.Connection, entity_id: uuid.UUID) -> dict[str, Any]:
    """Resolve an entity UUID to its registered table and entity type."""
    row = conn.execute(
        "SELECT id, table_name, entity_type, created_at FROM entity_identity WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"entity identity not found: {entity_id}")
    return {
        "id": row[0],
        "table_name": row[1],
        "entity_type": row[2],
        "created_at": row[3],
    }


def resolve_entity_identities_batch(
    conn: psycopg.Connection, ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Resolve many entity UUIDs to their registered table/entity_type in one query.

    Unlike resolve_entity_identity, this never raises: ids with no
    entity_identity row are simply absent from the returned mapping. Used by
    callers (e.g. cascade_preview's detail projection, todo 3c762bfe) that
    classify a bounded batch of entity_uuids without one round trip per id.

    Parameters:
        conn: psycopg.Connection
            An open psycopg 3 connection.
        ids: list[uuid.UUID]
            The entity UUIDs to resolve. An empty list short-circuits to an
            empty dict without issuing a query.

    Returns:
        dict[uuid.UUID, dict[str, Any]]
            Mapping from each resolvable id to its
            {"id", "table_name", "entity_type", "created_at"} dict.
    """
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, table_name, entity_type, created_at FROM entity_identity WHERE id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    return {
        row[0]: {"id": row[0], "table_name": row[1], "entity_type": row[2], "created_at": row[3]}
        for row in rows
    }


def resolve_scoped_name(
    conn: psycopg.Connection,
    table: str,
    plan_uuid: uuid.UUID,
    name_column: str,
    name: str,
) -> uuid.UUID:
    """Resolve a human-readable scoped name to its immutable entity UUID.

    Parameters:
        conn: psycopg.Connection
            An open psycopg 3 connection, as returned by
            plan_manager.storage.connection.connect.
        table: str
            The table to query. Must be a member of ALLOWED_TABLES;
            otherwise ValueError is raised before any query is
            executed.
        plan_uuid: uuid.UUID
            The UUID of the owning plan; scopes the name lookup to one
            plan.
        name_column: str
            The column holding the human-readable scoped name (e.g.
            "concept_id" for concepts, "step_id" for steps, "label" for
            paragraphs, "name" for plans). Must be a member of
            ALLOWED_NAME_COLUMNS; otherwise ValueError is raised before
            any query is executed.
        name: str
            The scoped name value to look up.

    Returns:
        uuid.UUID
            The uuid column value of the matching row.

    Raises:
        ValueError: if table is not in ALLOWED_TABLES, or name_column is
            not in ALLOWED_NAME_COLUMNS. Raised before any SQL is
            executed, before any allowlist-failing value reaches string
            interpolation.
        plan_manager.storage.errors.NotFoundError: if no row matches
            plan_uuid and name in the given table/name_column.
    """
    if table not in ALLOWED_TABLES:
        raise ValueError(f"table not allowed: {table!r}")
    if name_column not in ALLOWED_NAME_COLUMNS:
        raise ValueError(f"name_column not allowed: {name_column!r}")
    sql = f"SELECT uuid FROM {table} WHERE plan_uuid = %s AND {name_column} = %s"
    row = conn.execute(sql, (plan_uuid, name)).fetchone()
    if row is None:
        raise NotFoundError(
            f"{table}.{name_column}={name!r} not found for plan {plan_uuid}"
        )
    return row[0]
