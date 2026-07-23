"""Command: mark an existing runtime comment as resolved (C-014, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.comment_command_metadata import comment_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import get_comment, resolve_comment


class CommentResolveCommand(Command):
    name: ClassVar[str] = "comment_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Mark an existing runtime comment as resolved."
    category: ClassVar[str] = "comment"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
                "comment_uuid": {"type": "string", "format": "uuid", "description": "UUID of the comment to resolve."},
                "changed_by": {"type": "string", "description": "Identity of the caller performing this operation, recorded as the audit actor."},
            },
            "required": ["plan", "comment_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "comment_uuid": {"description": "UUID of the comment to resolve.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the caller performing this operation.", "type": "string", "required": True},
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "The resolved RuntimeComment payload."}},
            [{"description": "Resolve a comment.", "command": {"plan": "plan_manager", "comment_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "changed_by": "reviewer"}}],
            best_practices=[
                "resolve_comment only sets resolved=true; there is no unresolve path here — reopen via comment_add or comment_supersede instead.",
                "Resolving updates the row in place with the same comment_uuid, unlike comment_supersede which appends a new record.",
                "changed_by is the audit actor for this action, not the original author field, which stays unchanged.",
            ],
        )

    async def execute(
        self,
        plan: str,
        comment_uuid: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                comment_uuid_val = uuid.UUID(comment_uuid)
                if get_comment(conn, comment_uuid_val) is None:
                    raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment_uuid}")
                record = resolve_comment(conn, comment_uuid_val, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
