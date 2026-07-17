"""Command: list a paginated page of review results by reviewed object and status (C-018, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.review_result import REVIEW_STATUSES
from plan_manager.runtime.context import db_connection
from plan_manager.storage.review_result_store import list_review_results

class ReviewResultListCommand(Command):
    name: ClassVar[str] = "review_result_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of review results scoped by reviewed execution attempt and status."
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
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier (name or UUID). Scopes the listing: only review results "
                        "whose reviewed execution attempt belongs to the resolved plan "
                        "(execution_attempt.plan_uuid) are returned; review results with no "
                        "reviewed attempt (reviewed_attempt_uuid NULL, e.g. revision reviews) or "
                        "whose attempt belongs to another plan are excluded."
                    ),
                },
                "reviewed_attempt_uuid": {
                    "type": "string",
                    "description": "Restrict results to review results of this execution attempt.",
                },
                "status": {
                    "type": "string",
                    "enum": ["accepted", "rejected", "changes_requested", "escalated", "needs_owner_decision"],
                    "description": (
                        "Restrict results to review results with this status. One of the 5 "
                        "ReviewStatus values, in declared order: accepted, rejected, "
                        "changes_requested, escalated, needs_owner_decision."
                    ),
                },
                "include_deleted": {
                    "type": "boolean",
                    "description": "Include soft-deleted review results in the listing. Defaults to false.",
                },
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": (
                    "Plan identifier (name or UUID). Scopes the listing: only review results "
                    "whose reviewed execution attempt belongs to the resolved plan "
                    "(execution_attempt.plan_uuid) are returned; review results with no "
                    "reviewed attempt (reviewed_attempt_uuid NULL, e.g. revision reviews) or "
                    "whose attempt belongs to another plan are excluded."
                ),
                "type": "string",
                "required": True,
            },
            "reviewed_attempt_uuid": {"description": "Restrict results to review results of this execution attempt.", "type": "string", "required": False},
            "status": {
                "description": (
                    "Restrict results to review results with this status. One of the 5 "
                    "ReviewStatus values, in declared order: accepted, rejected, "
                    "changes_requested, escalated, needs_owner_decision."
                ),
                "type": "string",
                "required": False,
            },
            "include_deleted": {"description": "Include soft-deleted review results in the listing. Defaults to false.", "type": "boolean", "required": False},
            **pagination_metadata_params(),
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "A page of review result payloads matching the requested reviewed-attempt/status scope, ordered oldest first, plus total/limit/offset."}},
            [{
                "description": "List all accepted review results for a given execution attempt.",
                "command": {
                    "plan": "plan_manager",
                    "reviewed_attempt_uuid": "b1f2e3a4-1111-2222-3333-444455556666",
                    "status": "accepted",
                },
            }],
            best_practices=[
                "The required plan parameter scopes the listing via the reviewed execution attempt: only review results whose attempt has execution_attempt.plan_uuid equal to the resolved plan are returned; attempt-less (reviewed_attempt_uuid NULL) and foreign-plan review results are excluded.",
                "A nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "Omit reviewed_attempt_uuid and status to list every review result for the plan; add either filter to narrow the scope.",
                "include_deleted defaults to false; set it true only when auditing soft-deleted review history.",
                "Results are ordered oldest first (created_at ASC); reverse client-side for a newest-first view.",
                "Filter by status escalated or needs_owner_decision to find review results still awaiting an owner decision.",
                "Compare offset+limit against total to detect additional pages.",
            ],
        )

    async def execute(
        self,
        plan: str,
        reviewed_attempt_uuid: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan)
                if status is not None and status not in REVIEW_STATUSES:
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        f"'status' must be one of {sorted(REVIEW_STATUSES)}; got {status!r}",
                    )
                pagination = parse_pagination({"limit": limit, "offset": offset})
                records = list_review_results(
                    conn,
                    reviewed_attempt_uuid=uuid.UUID(reviewed_attempt_uuid) if reviewed_attempt_uuid else None,
                    status=status,
                    include_deleted=include_deleted,
                    plan_uuid=plan_record.uuid,
                )
                total = len(records)
                page = records[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "review_results": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
