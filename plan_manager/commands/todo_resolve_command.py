"""Command: mark a TODO work item resolved (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import resolve_todo


class TodoResolveCommand(Command):
    name: ClassVar[str] = "todo_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Mark a TODO work item resolved."
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
                "changed_by": {"type": "string", "description": "Identity of the actor resolving this TODO item."},
            },
            "required": ["todo", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "todo": {"description": "TODO item UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor resolving this TODO item.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The resolved TodoItem payload."}},
            [{"description": "Resolve a TODO item.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}}],
            best_practices=[
                "Sets status unconditionally to resolved and stamps resolved_at — there is no precondition check on the current status, so resolving an already-resolved or closed item silently succeeds again.",
                "Distinct from todo_close: resolve implies the underlying work was completed, whereas close is a terminal state without asserting completion — pick based on outcome, not just to end the item.",
                "changed_by is required and recorded via the runtime audit trail (record_runtime_change), not stored as a field on the TodoItem payload itself.",
            ],
        )

    async def execute(
        self,
        todo: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                todo_uuid = uuid.UUID(todo)
                record = resolve_todo(conn, todo_uuid, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
