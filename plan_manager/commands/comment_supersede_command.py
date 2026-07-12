"""Command: create a new runtime comment that supersedes an existing one, preserving history (C-014, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.comment_command_metadata import comment_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import supersede_comment


class CommentSupersedeCommand(Command):
    name: ClassVar[str] = "comment_supersede"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new runtime comment that supersedes an existing one, preserving history."
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
                "comment_uuid": {"type": "string", "format": "uuid", "description": "UUID of the comment being superseded."},
                "body": {"type": "string", "description": "Replacement body text for the new superseding comment."},
                "changed_by": {"type": "string", "description": "Identity of the caller performing this operation, recorded as the audit actor."},
            },
            "required": ["plan", "comment_uuid", "body", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "comment_uuid": {"description": "UUID of the comment being superseded.", "type": "string", "required": True},
            "body": {"description": "Replacement body text for the new superseding comment.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the caller performing this operation.", "type": "string", "required": True},
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "The new superseding RuntimeComment payload."}},
            [{"description": "Supersede a comment with a corrected body.", "command": {"plan": "plan_manager", "comment_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "body": "Corrected observation.", "changed_by": "reviewer"}}],
            best_practices=[
                "supersede_comment copies anchor, kind, visibility, author, and resolved unchanged from the target — only body changes; use comment_add if those fields must differ.",
                "The new comment's supersedes_comment_uuid points at the comment_uuid you passed — that input is not guaranteed to be the chain's current tip.",
                "Superseding a missing or soft-deleted comment_uuid raises rather than creating a fresh comment — call comment_get first if unsure it exists.",
                "resolved carries over from the superseded comment — call comment_resolve separately if the corrected version should also be marked resolved.",
            ],
        )

    async def execute(
        self,
        plan: str,
        comment_uuid: str,
        body: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                record = supersede_comment(conn, uuid.UUID(comment_uuid), new_body=body, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
