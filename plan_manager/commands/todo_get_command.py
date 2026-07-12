"""Command: fetch a single TODO work item by identifier (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import get_todo


class TodoGetCommand(Command):
    name: ClassVar[str] = "todo_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Fetch a single TODO work item by identifier."
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
            },
            "required": ["todo"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "todo": {"description": "TODO item UUID.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The TodoItem payload."}},
            [{"description": "Fetch a TODO item by uuid.", "command": {"todo": "11111111-1111-1111-1111-111111111111"}}],
            best_practices=[
                "todo_get only returns live items; a soft-deleted (deleted_at set) or nonexistent uuid both raise TODO_NOT_FOUND, so a soft-deleted item is indistinguishable from one that never existed.",
                "This is a single-uuid lookup with no filtering or search — use todo_list first to discover the uuid you need.",
                "Returns the full TodoItem payload including anchor fields and audit timestamps; no pagination applies here.",
            ],
        )

    async def execute(
        self,
        todo: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                todo_uuid = validate_uuid(todo)
                record = get_todo(conn, todo_uuid)
                if record is None:
                    raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo}")
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
