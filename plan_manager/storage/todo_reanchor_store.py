"""TODO re-anchor storage function: moves a TODO item's primary anchor with an audit record (C-012)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.primary_anchor import PrimaryAnchor, anchor_to_columns, validate_anchor
from plan_manager.domain.reanchor_guard import guard_reanchor_target_not_frozen
from plan_manager.domain.todo import TodoItem
from plan_manager.storage.runtime_audit_store import record_runtime_change
from plan_manager.storage.todo_store import get_todo


def reanchor_todo(
    conn: psycopg.Connection,
    todo_uuid: uuid.UUID,
    *,
    changed_by: str,
    new_anchor: PrimaryAnchor,
) -> TodoItem:
    """Move a TODO item's primary anchor to a new target, with an audit record.

    Parameters:
        conn: psycopg.Connection
            Open connection used to perform the move.
        todo_uuid: uuid.UUID
            The TODO item whose primary anchor is being moved.
        changed_by: str
            Identity of the actor performing the re-anchor move, recorded on
            the appended audit record.
        new_anchor: PrimaryAnchor
            The candidate new primary anchor target.

    Returns:
        TodoItem
            The TODO item after its anchor fields are overwritten with the
            new target.

    Raises:
        DomainCommandError: With code TODO_NOT_FOUND when todo_uuid does not
            resolve to an existing live TODO item, either before or after
            the update.
        InvalidAnchorError: When new_anchor fails validate_anchor's shape
            checks for its anchor_type.
        FrozenTruthMutationError: When new_anchor targets a frozen plan or a
            frozen step (guard_reanchor_target_not_frozen).
    """
    from plan_manager.commands.errors import DomainCommandError

    existing = get_todo(conn, todo_uuid)
    if existing is None:
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    validate_anchor(conn, new_anchor)
    guard_reanchor_target_not_frozen(
        conn,
        new_anchor.anchor_type,
        new_anchor.plan_uuid,
        new_anchor.step_uuid,
    )

    old_anchor: dict[str, Any] = {
        "anchor_type": existing.primary_anchor_type,
        "project_id": str(existing.anchor_project_id) if existing.anchor_project_id is not None else None,
        "file_path": existing.anchor_file_path,
        "plan_uuid": str(existing.anchor_plan_uuid) if existing.anchor_plan_uuid is not None else None,
        "revision_uuid": str(existing.anchor_revision_uuid) if existing.anchor_revision_uuid is not None else None,
        "step_uuid": str(existing.anchor_step_uuid) if existing.anchor_step_uuid is not None else None,
        "step_path": existing.anchor_step_path,
        "ref_id": str(existing.anchor_ref_id) if existing.anchor_ref_id is not None else None,
    }
    new_anchor_payload: dict[str, Any] = {
        "anchor_type": new_anchor.anchor_type,
        "project_id": str(new_anchor.project_id) if new_anchor.project_id is not None else None,
        "file_path": new_anchor.file_path,
        "plan_uuid": str(new_anchor.plan_uuid) if new_anchor.plan_uuid is not None else None,
        "revision_uuid": str(new_anchor.revision_uuid) if new_anchor.revision_uuid is not None else None,
        "step_uuid": str(new_anchor.step_uuid) if new_anchor.step_uuid is not None else None,
        "step_path": new_anchor.step_path,
        "ref_id": str(new_anchor.ref_id) if new_anchor.ref_id is not None else None,
    }

    columns = anchor_to_columns(new_anchor)
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE todo_item SET primary_anchor_type = %s, anchor_project_id = %s, "
        "anchor_file_path = %s, anchor_plan_uuid = %s, anchor_revision_uuid = %s, "
        "anchor_step_uuid = %s, anchor_step_path = %s, anchor_ref_id = %s, updated_at = %s "
        "WHERE uuid = %s",
        (
            columns["primary_anchor_type"],
            columns["anchor_project_id"],
            columns["anchor_file_path"],
            columns["anchor_plan_uuid"],
            columns["anchor_revision_uuid"],
            columns["anchor_step_uuid"],
            columns["anchor_step_path"],
            columns["anchor_ref_id"],
            now,
            todo_uuid,
        ),
    )

    updated = get_todo(conn, todo_uuid)
    if updated is None:
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=updated.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
        changed_fields={"old_anchor": old_anchor, "new_anchor": new_anchor_payload},
    )

    return updated
