"""Persists a guarded todo status transition requested through the todo_update path (C-009).

Mirrors the mechanical stamping style of plan_manager.storage.todo_store's resolve_todo/close_todo:
performs the UPDATE, stamps started_at on the first transition into in_progress, records the audit
change, and re-fetches the TodoItem via the existing public todo_store.get_todo reader (this module
does not duplicate or modify todo_store.py).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

import psycopg

from plan_manager.domain.todo import TodoItem
from plan_manager.storage.runtime_audit_store import record_runtime_change
from plan_manager.storage.todo_store import get_todo

def transition_todo_status(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str, new_status: str
) -> TodoItem:
    """Apply an already-guarded todo status transition and return the updated TodoItem.

    Callers must call plan_manager.domain.todo_status_transitions.guard_todo_transition before
    invoking this function; this function performs no legality check of its own.

    Args:
        conn: An open psycopg 3 connection.
        todo_uuid: UUID of the todo item to transition.
        changed_by: Actor identity recorded as the change actor for the audit record.
        new_status: The already-validated target status (one of "in_progress", "blocked",
            "cancelled").

    Returns:
        The updated TodoItem, re-fetched from storage after the write.

    Raises:
        plan_manager.commands.errors.DomainCommandError: with code "TODO_NOT_FOUND" when no live
            todo item with todo_uuid exists after the update.
    """
    now = datetime.now(timezone.utc)
    current = get_todo(conn, todo_uuid)
    stamp_started_at = new_status == "in_progress" and current is not None and current.started_at is None

    if stamp_started_at:
        sql = "UPDATE todo_item SET status = %s, started_at = %s, updated_at = %s WHERE uuid = %s"
        conn.execute(sql, (new_status, now, now, todo_uuid))
    else:
        sql = "UPDATE todo_item SET status = %s, updated_at = %s WHERE uuid = %s"
        conn.execute(sql, (new_status, now, todo_uuid))

    record_obj = get_todo(conn, todo_uuid)
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
