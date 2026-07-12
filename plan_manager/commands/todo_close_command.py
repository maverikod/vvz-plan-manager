"""Command: mark a TODO work item closed (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import close_todo


class TodoCloseCommand(Command):
    name: ClassVar[str] = "todo_close"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Mark a TODO work item closed."
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
                "changed_by": {"type": "string", "description": "Identity of the actor closing this TODO item."},
            },
            "required": ["todo", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "todo": {"description": "TODO item UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor closing this TODO item.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The closed TodoItem payload."}},
            [{"description": "Close a TODO item.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}}],
            best_practices=[
                "Sets status unconditionally to closed with no precondition check on the current status — no error if the item is already closed or was never resolved.",
                "Unlike todo_resolve, todo_close does not stamp resolved_at — use it for TODOs abandoned or made obsolete rather than ones completed.",
                "changed_by is required and recorded via the runtime audit trail; it is not persisted on the TodoItem payload.",
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
                record = close_todo(conn, todo_uuid, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
