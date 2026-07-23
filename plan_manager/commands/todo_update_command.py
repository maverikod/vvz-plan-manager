"""Command: update mutable fields of an existing TODO work item (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception, DomainCommandError
from plan_manager.commands.plan_completion_guard import refuse_if_todo_plan_completed
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.domain.todo_status_transitions import guard_todo_transition
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_status_store import transition_todo_status
from plan_manager.storage.todo_store import update_todo, get_todo


class TodoUpdateCommand(Command):
    name: ClassVar[str] = "todo_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Update mutable fields of an existing TODO work item."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todo": {"type": "string", "format": "uuid", "description": "TODO item UUID."},
                "changed_by": {"type": "string", "description": "Identity of the actor making this change."},
                "status": {"type": "string", "description": "New status via the guarded todo_update transition path: one of in_progress, blocked, cancelled.", "enum": ["in_progress", "blocked", "cancelled"]},
                "title": {"type": "string", "description": "New title, if changing."},
                "description": {"type": "string", "description": "New description, if changing."},
                "priority_nice": {"type": "integer", "description": "New nice-scale priority in [-20, 19], if changing."},
                "assigned_to": {"type": "string", "description": "New assignee identity, if changing."},
                "blocking_reason": {"type": "string", "description": "New blocking reason, if changing."},
                "execution_result": {"type": "string", "description": "New execution result note, if changing."},
            },
            "required": ["todo", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "todo": {"description": "TODO item UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor making this change.", "type": "string", "required": True},
            "status": {"description": "New status via the guarded todo_update transition path: one of in_progress, blocked, cancelled.", "type": "string", "required": False},
            "title": {"description": "New title, if changing.", "type": "string", "required": False},
            "description": {"description": "New description, if changing.", "type": "string", "required": False},
            "priority_nice": {"description": "New nice-scale priority in [-20, 19], if changing.", "type": "integer", "required": False},
            "assigned_to": {"description": "New assignee identity, if changing.", "type": "string", "required": False},
            "blocking_reason": {"description": "New blocking reason, if changing.", "type": "string", "required": False},
            "execution_result": {"description": "New execution result note, if changing.", "type": "string", "required": False},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The updated TodoItem payload."}},
            [{"description": "Reprioritize a TODO item.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "priority_nice": -10}}],
            best_practices=[
                "Only fields explicitly passed (non-None) are updated; omit a field entirely to leave it unchanged rather than passing an empty string.",
                "Anchor fields (anchor_type and all anchor_* columns) are never modified by this command — the primary anchor is immutable after todo_create.",
                "priority_nice is re-validated against [-20, 19] on every update, same as on create.",
                "status may move to in_progress, blocked, or cancelled here via the guarded todo_update transition path; use todo_resolve or todo_close for the separate unconditional resolved/closed transitions.",
            ],
        )

    async def execute(
        self,
        todo: str,
        changed_by: str,
        status: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority_nice: int | None = None,
        assigned_to: str | None = None,
        blocking_reason: str | None = None,
        execution_result: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                todo_uuid = uuid.UUID(todo)
                existing = get_todo(conn, todo_uuid)
                if existing is None:
                    raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo}")
                refuse_if_todo_plan_completed(conn, existing)
                if status is not None:
                    guard_todo_transition(existing.status, status)
                    transition_todo_status(conn, todo_uuid, changed_by=changed_by, new_status=status)
                record = update_todo(
                    conn,
                    todo_uuid,
                    changed_by=changed_by,
                    title=title,
                    description=description,
                    priority_nice=priority_nice,
                    assigned_to=assigned_to,
                    blocking_reason=blocking_reason,
                    execution_result=execution_result,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
