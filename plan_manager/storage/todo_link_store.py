"""TODO link persistence: create/list/remove typed links over todo_link with guard enforcement, audit, and soft delete."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.todo_link import (
    TodoLink, TODO_LINK_TYPES, BLOCKING_LINK_TYPES,
    guard_self_reference, guard_no_duplicate, guard_no_blocking_cycle,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: Any) -> TodoLink:
    """Build a TodoLink from a database row whose columns are, in order: uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, created_at, updated_at, deleted_at. uuid columns become uuid.UUID; timestamptz columns become their .isoformat() string (deleted_at stays None if NULL)."""
    return TodoLink(
        link_uuid=row[0],
        from_todo_uuid=row[1],
        to_todo_uuid=row[2],
        link_type=row[3],
        created_by=row[4],
        created_at=row[5].isoformat(),
        updated_at=row[6].isoformat(),
        deleted_at=row[7].isoformat() if row[7] is not None else None,
    )


def create_todo_link(conn: psycopg.Connection, *, from_todo_uuid: uuid.UUID, to_todo_uuid: uuid.UUID,
                     link_type: str, created_by: str) -> TodoLink:
    """Create a typed link between two TODOs after enforcing all guards, then record an audit entry."""
    # Step 1: Validate link_type
    if link_type not in TODO_LINK_TYPES:
        raise RuntimeValidationError(f"Invalid link_type: {link_type}")

    # Step 2: Guard self-reference
    guard_self_reference(from_todo_uuid, to_todo_uuid)

    # Step 3: Check both TODOs exist
    check_row_exists(conn, "todo_item", from_todo_uuid, frozenset({"todo_item"}))
    check_row_exists(conn, "todo_item", to_todo_uuid, frozenset({"todo_item"}))

    # Step 4: Check for duplicate links
    sql = "SELECT from_todo_uuid, to_todo_uuid, link_type FROM todo_link WHERE deleted_at IS NULL"
    result = conn.execute(sql)
    existing = set()
    for row in result:
        existing.add((str(row[0]), str(row[1]), row[2]))
    guard_no_duplicate(existing, (str(from_todo_uuid), str(to_todo_uuid), link_type))

    # Step 5: Check for blocking cycles if applicable
    if link_type in BLOCKING_LINK_TYPES:
        sql = "SELECT from_todo_uuid, to_todo_uuid, link_type FROM todo_link WHERE deleted_at IS NULL AND link_type IN (%s, %s)"
        result = conn.execute(sql, ('blocks', 'blocked_by'))
        edges = []
        for row in result:
            if row[2] == 'blocks':
                edges.append((str(row[0]), str(row[1])))
            else:  # blocked_by
                edges.append((str(row[1]), str(row[0])))

        # Add the candidate edge
        if link_type == 'blocks':
            edges.append((str(from_todo_uuid), str(to_todo_uuid)))
        else:  # blocked_by
            edges.append((str(to_todo_uuid), str(from_todo_uuid)))

        guard_no_blocking_cycle(edges)

    # Step 6: Insert the new link
    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    sql = "INSERT INTO todo_link (uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, created_at, updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    conn.execute(sql, (new_uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, now, now, None))

    # Step 7: Record audit entry
    record_runtime_change(conn, plan_uuid=None, entity_type="todo_link", entity_id=new_uuid, action="create", changed_by=created_by)

    # Step 8: Return the created link
    return TodoLink(
        link_uuid=new_uuid,
        from_todo_uuid=from_todo_uuid,
        to_todo_uuid=to_todo_uuid,
        link_type=link_type,
        created_by=created_by,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        deleted_at=None,
    )


def get_todo_link(conn: psycopg.Connection, link_uuid: uuid.UUID) -> TodoLink | None:
    """Fetch a single todo_link row by its uuid, or None if no row with that uuid exists."""
    sql = "SELECT uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM todo_link WHERE uuid = %s"
    result = conn.execute(sql, (link_uuid,))
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_todo_links(conn: psycopg.Connection, *, todo_uuid: uuid.UUID | None = None,
                    include_deleted: bool = False) -> list[TodoLink]:
    """List todo_link rows, optionally filtered to those attached to todo_uuid, ordered by created_at ascending."""
    sql = "SELECT uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM todo_link"
    params: list[Any] = []
    conditions = []

    if todo_uuid is not None:
        conditions.append("(from_todo_uuid = %s OR to_todo_uuid = %s)")
        params.extend([todo_uuid, todo_uuid])

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY created_at ASC"

    if params:
        result = conn.execute(sql, params)
    else:
        result = conn.execute(sql)

    return [_row_to_record(row) for row in result]


def remove_todo_link(conn: psycopg.Connection, link_uuid: uuid.UUID, *, changed_by: str) -> TodoLink:
    """Soft-delete a todo_link row (never a physical DELETE), then record an audit entry, and return the updated row."""
    now = datetime.now(timezone.utc)

    # Soft-delete the link
    sql = "UPDATE todo_link SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    conn.execute(sql, (now, now, link_uuid))

    # Record audit entry
    record_runtime_change(conn, plan_uuid=None, entity_type="todo_link", entity_id=link_uuid, action="soft_delete", changed_by=changed_by)

    # Fetch and return the updated link
    sql = "SELECT uuid, from_todo_uuid, to_todo_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM todo_link WHERE uuid = %s"
    result = conn.execute(sql, (link_uuid,))
    row = result.fetchone()
    return _row_to_record(row)
