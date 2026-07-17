"""Command: list the fix attempts recorded for a bug, filtered and paginated (C-024, C-030)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.domain.bug_fix import BUG_FIX_STATUSES, BugFixStatus
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_report_store import get_bug
from plan_manager.storage.project_scope import resolve_project_plan_uuids


FILTER_FIELDS = ["status", "unverified_fixes", "created_after", "created_before", "project"]

_FILTER_ENUMS = {"status": BUG_FIX_STATUSES}

# Ordered vocabulary published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error.
_ENUM_OVERRIDES = {"status": [e.value for e in BugFixStatus]}


class BugFixListCommand(Command):
    name: ClassVar[str] = "bug_fix_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List the fix attempts recorded for a bug, filtered and paginated (read-only)."
    category: ClassVar[str] = "fix"
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
                        "Plan identifier (name or UUID), optional. When supplied, enforces plan/bug "
                        "consistency: when the bug's source_plan_uuid is set, it must equal the "
                        "resolved plan, otherwise BUG_NOT_FOUND is raised; a bug with "
                        "source_plan_uuid NULL (e.g. command-anchored bugs) is listable under any "
                        "supplied plan. When omitted, no plan/bug consistency check is performed."
                    ),
                },
                "bug": {"type": "string", "format": "uuid", "description": "UUID of the BugReport (C-020) whose fix attempts are listed. Must be anchored to the resolved plan when plan is supplied (source_plan_uuid equal or NULL)."},
                **filter_schema_properties(FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
            },
            "required": ["bug"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": (
                    "Plan identifier (name or UUID), optional. When supplied, enforces plan/bug "
                    "consistency: when the bug's source_plan_uuid is set, it must equal the "
                    "resolved plan, otherwise BUG_NOT_FOUND is raised; a bug with "
                    "source_plan_uuid NULL (e.g. command-anchored bugs) is listable under any "
                    "supplied plan. When omitted, no plan/bug consistency check is performed."
                ),
                "type": "string",
                "required": False,
            },
            "bug": {"description": "UUID of the BugReport (C-020) whose fix attempts are listed. Must be anchored to the resolved plan when plan is supplied (source_plan_uuid equal or NULL).", "type": "string", "required": True},
            **filter_metadata_params(FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_metadata_params(),
        }
        return bug_fix_metadata(
            cls,
            params,
            {"success": {"description": "A page of BugFix (C-024) payloads for the bug, plus total/limit/offset."}},
            [{"description": "List unverified fix attempts for a bug.", "command": {"plan": "plan_manager", "bug": "11111111-1111-1111-1111-111111111111", "unverified_fixes": True}}],
            error_cases={
                "BUG_NOT_FOUND": {
                    "description": "The supplied bug identifier does not resolve to an existing BugReport record, OR the bug's source_plan_uuid is set and differs from the resolved plan (plan/bug consistency guard). Bugs with source_plan_uuid NULL are accepted under any valid plan.",
                    "message": "bug not found: {bug}",
                    "solution": "Call bug_list for the plan and retry with a bug uuid anchored to that plan (or with a plan-unanchored bug).",
                },
            },
            best_practices=[
                "The optional plan parameter is a consistency guard: when supplied, a bug whose source_plan_uuid is set to a different plan raises BUG_NOT_FOUND instead of listing foreign fixes. Omit it to skip the guard entirely.",
                "Bugs with source_plan_uuid NULL (e.g. command-anchored bugs) are listable under any supplied plan; the plan does not further filter their fixes.",
                "A supplied but nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "The project filter matches transitively: a fix whose source_project_id equals the filter value matches directly, and a fix with source_project_id NULL still matches when the owning bug's source_plan_uuid is bound to that project (plan.project_ids).",
                "Set unverified_fixes=true to see only fix attempts not yet verified.",
                "Use limit/offset for pagination and compare offset+limit against total to detect more pages.",
            ],
        )

    async def execute(
        self,
        bug: str,
        plan: str | None = None,
        status: str | None = None,
        unverified_fixes: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        project: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan) if plan is not None else None
                bug_uuid = uuid.UUID(bug)
                bug_record = get_bug(conn, bug_uuid)
                if bug_record is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug}")
                if (
                    plan_record is not None
                    and bug_record.source_plan_uuid is not None
                    and bug_record.source_plan_uuid != plan_record.uuid
                ):
                    raise DomainCommandError(
                        "BUG_NOT_FOUND",
                        f"bug not found: {bug} (anchored to plan {bug_record.source_plan_uuid}, not the resolved plan {plan_record.uuid})",
                    )
                raw_params = {
                    "status": status,
                    "unverified_fixes": unverified_fixes,
                    "created_after": created_after,
                    "created_before": created_before,
                    "project": project,
                    "limit": limit,
                    "offset": offset,
                }
                filters = parse_filters(raw_params, FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination(raw_params)
                records = list_bug_fixes(conn, bug_uuid=bug_uuid, status=filters.get("status"))
                if filters.get("unverified_fixes"):
                    records = [r for r in records if r.status != "verified"]
                project_value = filters.get("project")
                if project_value is not None:
                    project_uuid = validate_uuid(project_value)
                    bound_plan_uuids = resolve_project_plan_uuids(conn, project_uuid)
                    records = [
                        r for r in records
                        if (r.source_project_id is not None and r.source_project_id == project_uuid)
                        or (bug_record.source_plan_uuid is not None and bug_record.source_plan_uuid in bound_plan_uuids)
                    ]
                created_after_value = filters.get("created_after")
                if created_after_value is not None:
                    records = [r for r in records if r.created_at > created_after_value]
                created_before_value = filters.get("created_before")
                if created_before_value is not None:
                    records = [r for r in records if r.created_at < created_before_value]
                total = len(records)
                page = records[pagination.offset:pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "bug_fixes": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
