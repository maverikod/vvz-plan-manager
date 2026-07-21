"""Command: retrieve a single runtime comment by identifier (C-014, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.comment_command_metadata import comment_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import get_comment


class CommentGetCommand(Command):
    name: ClassVar[str] = "comment_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single runtime comment by identifier."
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
                "comment_uuid": {"type": "string", "format": "uuid", "description": "UUID of the comment to retrieve."},
            },
            "required": ["plan", "comment_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "comment_uuid": {"description": "UUID of the comment to retrieve.", "type": "string", "required": True},
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "The retrieved RuntimeComment payload."}},
            [{"description": "Retrieve a comment by UUID.", "command": {"plan": "plan_manager", "comment_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}}],
            best_practices=[
                "get_comment excludes soft-deleted rows, so COMMENT_NOT_FOUND covers both 'never existed' and 'deleted' — it does not distinguish them.",
                "The result is the exact row for comment_uuid, not the head of its supersede chain — check supersedes_comment_uuid or comment_list for later versions.",
                "resolved is nullable: None means never marked, distinct from an explicit false.",
            ],
        )

    async def execute(
        self,
        plan: str,
        comment_uuid: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                record = get_comment(conn, uuid.UUID(comment_uuid))
                if record is None:
                    raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment_uuid}")
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
