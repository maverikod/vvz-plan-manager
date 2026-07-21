"""Command: retrieve a single review result by identifier (C-018, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.review_result_store import get_review_result


class ReviewResultGetCommand(Command):
    name: ClassVar[str] = "review_result_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single review result by identifier."
    category: ClassVar[str] = "review"
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
                "review_uuid": {"type": "string", "description": "UUID of the review result to retrieve."},
            },
            "required": ["plan", "review_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "review_uuid": {"description": "UUID of the review result to retrieve.", "type": "string", "required": True},
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "The requested review result payload."}},
            [{
                "description": "Retrieve a review result by its UUID.",
                "command": {"plan": "plan_manager", "review_uuid": "c2a3b4c5-1111-2222-3333-444455556666"},
            }],
            best_practices=[
                "review_uuid must be an existing review_result UUID; an unknown value returns REVIEW_RESULT_NOT_FOUND.",
                "Use review_result_list first to discover valid review_uuid values before calling review_result_get.",
                "Soft-deleted review results are still returned; check the deleted_at field in the payload.",
            ],
        )

    async def execute(
        self, plan: str, review_uuid: str, context: object | None = None
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                record = get_review_result(conn, uuid.UUID(review_uuid))
                if record is None:
                    raise DomainCommandError("REVIEW_RESULT_NOT_FOUND", f"review result not found: {review_uuid}")
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
