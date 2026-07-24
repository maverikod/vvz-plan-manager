"""Command: list a paginated page of execution attempts filtered by anchor, status, and parent lineage (C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.execution_attempt import ATTEMPT_STATUSES
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import list_execution_attempts
from plan_manager.commands.list_projection import (
    VIEW_SUMMARY,
    VIEW_VALUES,
    parse_view,
    project_entities,
)

# execution_attempt_list does NOT use list_projection's packaged
# view_schema_properties()/view_metadata_params(): those hardcode
# default="full". execution_attempt_list's rows always embed
# result_summary/command_test_results/resource_accounting/transcript_ref.
# Todo ffe0b0a8 (flip every SUMMARY_FIELDS-bearing list command's default to
# summary) fixes this: the default becomes VIEW_SUMMARY (the same
# deliberate deviation bug_list and srt_snapshot_list already made),
# pointing at ExecutionAttempt.SUMMARY_FIELDS; limit/offset/total pagination
# is unchanged. 'view=full' still opts into the complete record; full
# detail is always one execution_attempt_get call away either way.
_VIEW_DESCRIPTION: str = (
    "Row projection shape. 'summary' (default; todo ffe0b0a8) returns a compact "
    "per-row projection (uuid, plan_uuid, step_uuid, status, used_provider, "
    "used_model, updated_at) -- result_summary, command_test_results, "
    "resource_accounting, transcript_ref, and error detail are never "
    "included by default. 'full' opts into the complete record; use "
    "execution_attempt_get for a single attempt's full detail either way. "
    "One of: " + ", ".join(VIEW_VALUES) + "."
)

_VIEW_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(VIEW_VALUES),
    "default": VIEW_SUMMARY,
    "description": _VIEW_DESCRIPTION,
}

_VIEW_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _VIEW_DESCRIPTION,
    "required": False,
    "enum": list(VIEW_VALUES),
}


class ExecutionAttemptListCommand(Command):
    name: ClassVar[str] = "execution_attempt_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "List a paginated page of execution attempts filtered by plan, step, "
        "status, and parent attempt lineage."
    )
    category: ClassVar[str] = "execution"
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
                    "description": "Optional plan identifier (name or UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "step": {
                    "description": "Optional step identifier (UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "status": {
                    "description": (
                        "Optional execution attempt status to filter by. One of the 8 "
                        "ExecutionAttemptStatus values, in declared order: queued, running, "
                        "succeeded, failed, cancelled, timed_out, needs_review, "
                        "needs_escalation."
                    ),
                    "type": "string",
                    "enum": [
                        "queued",
                        "running",
                        "succeeded",
                        "failed",
                        "cancelled",
                        "timed_out",
                        "needs_review",
                        "needs_escalation",
                    ],
                    "required": False,
                },
                "parent_attempt_id": {
                    "description": "Optional parent execution attempt identifier (UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "include_deleted": {
                    "description": "Include soft-deleted execution attempts. Defaults to false.",
                    "type": "boolean",
                    "required": False,
                },
                **pagination_schema_properties(),
                "view": dict(_VIEW_SCHEMA_PROPERTY),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        params.update(pagination_metadata_params())
        params["view"] = dict(_VIEW_METADATA_PARAM)
        return_value = {
            "success": {
                "description": "A page of the matching execution attempt records (or, with view=summary, compact projections), with all UUID fields rendered as strings, plus total/limit/offset.",
                "data": {
                    "execution_attempts": "The requested page of execution attempt payloads.",
                    "total": "Count of the full matching set before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
            },
        }
        examples = [
            {
                "description": "List queued execution attempts for a plan.",
                "command": {"plan": "my-plan", "status": "queued"},
            },
        ]
        best_practices = [
            "All filters are optional; omit plan/step/status/parent_attempt_id to list every execution attempt in scope.",
            "Results are ordered by created_at ascending, oldest attempt first.",
            "include_deleted defaults to false; set it true only to audit soft-deleted attempts.",
            "Filter by parent_attempt_id to walk a retry lineage originating from a given attempt.",
            "Combine plan and status to check outstanding queued/running attempts before creating new ones.",
            "No transition matrix is enforced on execution attempt status: execution_attempt_report "
            "accepts any of the 8 ExecutionAttemptStatus values regardless of the attempt's current "
            "status, so this filter reflects whatever status was most recently reported, not a "
            "state-machine-validated progression.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary (the default; todo ffe0b0a8) returns a compact per-row projection (uuid, plan_uuid, step_uuid, status, used_provider, used_model, updated_at) instead of the full record (drops result_summary, command_test_results, resource_accounting, transcript_ref); use execution_attempt_get for a single attempt's full detail. Pass view=full to opt back into the complete record.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate execution_attempt_list parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If step or parent_attempt_id is supplied and
                is not a valid UUID string.
        """
        params = super().validate_params(params)
        step = params.get("step")
        if step is not None:
            try:
                uuid.UUID(step)
            except ValueError as exc:
                raise InvalidParamsError(f"step is not a valid UUID: {step!r}") from exc
        parent_attempt_id = params.get("parent_attempt_id")
        if parent_attempt_id is not None:
            try:
                uuid.UUID(parent_attempt_id)
            except ValueError as exc:
                raise InvalidParamsError(f"parent_attempt_id is not a valid UUID: {parent_attempt_id!r}") from exc
        return params

    async def execute(
        self,
        plan: str | None = None,
        step: str | None = None,
        status: str | None = None,
        parent_attempt_id: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view, default=VIEW_SUMMARY)
            with db_connection() as conn:
                plan_uuid = None
                if plan is not None:
                    p = resolve_plan(conn, plan)
                    plan_uuid = p.uuid
                if status is not None and status not in ATTEMPT_STATUSES:
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        f"'status' must be one of {sorted(ATTEMPT_STATUSES)}; got {status!r}",
                    )
                pagination = parse_pagination({"limit": limit, "offset": offset})
                attempts = list_execution_attempts(
                    conn,
                    plan_uuid=plan_uuid,
                    step_uuid=uuid.UUID(step) if step is not None else None,
                    status=status,
                    parent_attempt_uuid=uuid.UUID(parent_attempt_id) if parent_attempt_id is not None else None,
                    include_deleted=include_deleted,
                )
                total = len(attempts)
                page = attempts[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "execution_attempts": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
