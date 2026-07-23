"""Command: remove (soft-delete) a typed link between two TODO work items (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_todo_plan_completed
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_link_store import get_todo_link, remove_todo_link
from plan_manager.storage.todo_store import get_todo


class TodoLinkRemoveCommand(Command):
    name: ClassVar[str] = "todo_link_remove"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Remove (soft-delete) a typed link between two TODO work items."
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
                "link": {"type": "string", "format": "uuid", "description": "TODO link UUID."},
                "changed_by": {"type": "string", "description": "Identity of the actor removing this link."},
            },
            "required": ["link", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "link": {"description": "TODO link UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor removing this link.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The removed TodoLink payload."}},
            [{"description": "Remove a TODO link.", "command": {"link": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1"}}],
            best_practices=[
                "This is a soft-delete (deleted_at is set); the link row is never physically removed and stays visible via list_todo_links(include_deleted=True).",
                "get_todo_link does not filter on deleted_at, so removing an already-removed link succeeds again (refreshing deleted_at/updated_at) instead of erroring — effectively idempotent in practice, unlike todo_link_add.",
                "The parameter is the link_uuid returned by todo_link_add, not the from/to todo uuids it connects.",
            ],
        )

    async def execute(
        self,
        link: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                link_uuid = uuid.UUID(link)
                existing = get_todo_link(conn, link_uuid)
                if existing is None:
                    raise DomainCommandError("TODO_LINK_NOT_FOUND", f"todo link not found: {link}")
                # Both endpoints (bug c3950b83): a missing endpoint todo is
                # a separate, pre-existing dangling-reference concern this
                # guard does not police.
                from_record = get_todo(conn, existing.from_todo_uuid)
                if from_record is not None:
                    refuse_if_todo_plan_completed(conn, from_record)
                to_record = get_todo(conn, existing.to_todo_uuid)
                if to_record is not None:
                    refuse_if_todo_plan_completed(conn, to_record)
                record = remove_todo_link(conn, link_uuid, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
