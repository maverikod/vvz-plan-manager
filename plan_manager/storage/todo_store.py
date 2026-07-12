from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.todo import TodoItem, TODO_KINDS, TODO_STATUSES
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor, anchor_to_columns
from plan_manager.domain.nice_priority import validate_nice_priority
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...]) -> TodoItem:
    """Convert a database row to a TodoItem instance.

    Row order matches todo_item table column order:
    uuid, title, description, kind, status, priority_nice, created_by,
    assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
    primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
    anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
    blocking_reason, execution_result, deleted_at
    """
    (
        row_uuid,
        title,
        description,
        kind,
        status,
        priority_nice,
        created_by,
        assigned_to,
        created_at,
        updated_at,
        started_at,
        resolved_at,
        due_at,
        primary_anchor_type,
        anchor_project_id,
        anchor_file_path,
        anchor_plan_uuid,
        anchor_revision_uuid,
        anchor_step_uuid,
        anchor_step_path,
        anchor_ref_id,
        blocking_reason,
        execution_result,
        deleted_at,
    ) = row

    return TodoItem(
        todo_uuid=row_uuid if isinstance(row_uuid, uuid.UUID) else uuid.UUID(row_uuid),
        title=title,
        description=description,
        kind=kind,
        status=status,
        priority_nice=priority_nice,
        created_by=created_by,
        assigned_to=assigned_to,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        started_at=started_at.isoformat() if started_at else None,
        resolved_at=resolved_at.isoformat() if resolved_at else None,
        due_at=due_at.isoformat() if due_at else None,
        primary_anchor_type=primary_anchor_type,
        anchor_project_id=anchor_project_id if isinstance(anchor_project_id, uuid.UUID) else (uuid.UUID(anchor_project_id) if anchor_project_id else None),
        anchor_file_path=anchor_file_path,
        anchor_plan_uuid=anchor_plan_uuid if isinstance(anchor_plan_uuid, uuid.UUID) else (uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid else None),
        anchor_revision_uuid=anchor_revision_uuid if isinstance(anchor_revision_uuid, uuid.UUID) else (uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid else None),
        anchor_step_uuid=anchor_step_uuid if isinstance(anchor_step_uuid, uuid.UUID) else (uuid.UUID(anchor_step_uuid) if anchor_step_uuid else None),
        anchor_step_path=anchor_step_path,
        anchor_ref_id=anchor_ref_id if isinstance(anchor_ref_id, uuid.UUID) else (uuid.UUID(anchor_ref_id) if anchor_ref_id else None),
        blocking_reason=blocking_reason,
        execution_result=execution_result,
        deleted_at=deleted_at.isoformat() if deleted_at else None,
    )


def _get_row(conn: psycopg.Connection, todo_uuid: uuid.UUID) -> TodoItem | None:
    """Select a single row by uuid, regardless of deleted_at status.

    Returns the row if it exists (including soft-deleted rows), else None.
    This is the internal fetch path for mutating functions.
    """
    sql = """
    SELECT
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
        primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        blocking_reason, execution_result, deleted_at
    FROM todo_item
    WHERE uuid = %s
    """
    result = conn.execute(sql, (todo_uuid,))
    row = result.fetchone()
    return _row_to_record(row) if row else None


def create_todo(
    conn: psycopg.Connection,
    *,
    title: str,
    description: str,
    kind: str,
    priority_nice: int,
    created_by: str,
    anchor: PrimaryAnchor,
    status: str = "open",
    assigned_to: str | None = None,
    due_at: str | None = None,
    blocking_reason: str | None = None,
    execution_result: str | None = None,
) -> TodoItem:
    """Create a new TODO item with validation and audit recording."""
    if kind not in TODO_KINDS:
        raise RuntimeValidationError(f"Invalid kind: {kind}")

    if status not in TODO_STATUSES:
        raise RuntimeValidationError(f"Invalid status: {status}")

    validate_nice_priority(priority_nice)
    validate_anchor(conn, anchor)

    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    columns = anchor_to_columns(anchor)

    sql = """
    INSERT INTO todo_item (
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
        primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        blocking_reason, execution_result, deleted_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s
    )
    """

    params = (
        new_uuid,
        title,
        description,
        kind,
        status,
        priority_nice,
        created_by,
        assigned_to,
        now,
        now,
        None,
        None,
        due_at,
        columns["primary_anchor_type"],
        columns["anchor_project_id"],
        columns["anchor_file_path"],
        columns["anchor_plan_uuid"],
        columns["anchor_revision_uuid"],
        columns["anchor_step_uuid"],
        columns["anchor_step_path"],
        columns["anchor_ref_id"],
        blocking_reason,
        execution_result,
        None,
    )

    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=anchor.plan_uuid,
        entity_type="todo",
        entity_id=new_uuid,
        action="create",
        changed_by=created_by,
    )

    fetched = _get_row(conn, new_uuid)
    return fetched


def get_todo(conn: psycopg.Connection, todo_uuid: uuid.UUID) -> TodoItem | None:
    """Retrieve a live TODO item by uuid.

    Returns None if the item does not exist or is soft-deleted.
    """
    sql = """
    SELECT
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
        primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        blocking_reason, execution_result, deleted_at
    FROM todo_item
    WHERE uuid = %s AND deleted_at IS NULL
    """
    result = conn.execute(sql, (todo_uuid,))
    row = result.fetchone()
    return _row_to_record(row) if row else None


def list_todos(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    include_deleted: bool = False,
) -> list[TodoItem]:
    """List TODO items, optionally filtered by status and/or kind.

    Excludes soft-deleted items unless include_deleted=True.
    Returns results ordered by created_at ASC.
    """
    sql = """
    SELECT
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
        primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        blocking_reason, execution_result, deleted_at
    FROM todo_item
    WHERE 1=1
    """

    params = []

    if kind is not None:
        sql += " AND kind = %s"
        params.append(kind)

    if status is not None:
        sql += " AND status = %s"
        params.append(status)

    if not include_deleted:
        sql += " AND deleted_at IS NULL"

    sql += " ORDER BY created_at ASC"

    result = conn.execute(sql, params)
    rows = result.fetchall()
    return [_row_to_record(row) for row in rows]


def update_todo(
    conn: psycopg.Connection,
    todo_uuid: uuid.UUID,
    *,
    changed_by: str,
    title: str | None = None,
    description: str | None = None,
    priority_nice: int | None = None,
    assigned_to: str | None = None,
    blocking_reason: str | None = None,
    execution_result: str | None = None,
) -> TodoItem:
    """Update mutable fields of a TODO item and record the change.

    Only non-None fields are updated. Anchor columns are never modified.
    """
    updates = []
    params = []

    if title is not None:
        updates.append("title = %s")
        params.append(title)

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if priority_nice is not None:
        validate_nice_priority(priority_nice)
        updates.append("priority_nice = %s")
        params.append(priority_nice)

    if assigned_to is not None:
        updates.append("assigned_to = %s")
        params.append(assigned_to)

    if blocking_reason is not None:
        updates.append("blocking_reason = %s")
        params.append(blocking_reason)

    if execution_result is not None:
        updates.append("execution_result = %s")
        params.append(execution_result)

    now = datetime.now(timezone.utc)
    updates.append("updated_at = %s")
    params.append(now)

    params.append(todo_uuid)

    sql = f"UPDATE todo_item SET {', '.join(updates)} WHERE uuid = %s"
    conn.execute(sql, params)

    record_obj = _get_row(conn, todo_uuid)
    if record_obj is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def resolve_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Transition a TODO item to 'resolved' status."""
    now = datetime.now(timezone.utc)

    sql = """
    UPDATE todo_item
    SET status = %s, resolved_at = %s, updated_at = %s
    WHERE uuid = %s
    """
    conn.execute(sql, ("resolved", now, now, todo_uuid))

    record_obj = _get_row(conn, todo_uuid)
    if record_obj is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def close_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Transition a TODO item to 'closed' status."""
    now = datetime.now(timezone.utc)

    sql = """
    UPDATE todo_item
    SET status = %s, updated_at = %s
    WHERE uuid = %s
    """
    conn.execute(sql, ("closed", now, todo_uuid))

    record_obj = _get_row(conn, todo_uuid)
    if record_obj is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def soft_delete_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Soft-delete a TODO item by setting deleted_at."""
    now = datetime.now(timezone.utc)

    sql = """
    UPDATE todo_item
    SET deleted_at = %s, updated_at = %s
    WHERE uuid = %s
    """
    conn.execute(sql, (now, now, todo_uuid))

    record_obj = _get_row(conn, todo_uuid)

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return record_obj
