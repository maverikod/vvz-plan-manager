"""Command: list BugImpact records for a bug, with uniform filtering and pagination (C-022, C-029, C-030)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import BASE_PARAMETERS, bug_impact_metadata
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
from plan_manager.domain.bug_impact import BUG_IMPACT_STATUSES, BUG_IMPACT_TYPES, BugImpactStatus, BugImpactType
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_impact_store import list_bug_impacts
from plan_manager.storage.bug_report_store import get_bug
from plan_manager.storage.project_scope import resolve_project_plan_uuids

_LIST_FILTER_FIELDS = ["status", "impact_type", "unresolved_impacts", "created_after", "created_before", "project"]
_RESOLVED_IMPACT_STATUSES = frozenset({"resolved", "verified", "unaffected", "skipped"})
_FILTER_ENUMS = {"status": BUG_IMPACT_STATUSES, "impact_type": BUG_IMPACT_TYPES}

# Ordered vocabulary published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error.
_ENUM_OVERRIDES = {"status": [e.value for e in BugImpactStatus], "impact_type": [e.value for e in BugImpactType]}


class BugImpactListCommand(Command):
    name: ClassVar[str] = "bug_impact_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List BugImpact records for a bug, with uniform filtering and pagination."
    category: ClassVar[str] = "impact"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        properties = {
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
            "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug_report whose impacts are listed. Must be anchored to the resolved plan when plan is supplied (source_plan_uuid equal or NULL)."},
        }
        properties.update(filter_schema_properties(_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES))
        properties.update(pagination_schema_properties())
        return {
            "type": "object",
            "properties": properties,
            "required": ["bug_id"],
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
            "bug_id": {"description": "UUID of the bug_report whose impacts are listed. Must be anchored to the resolved plan when plan is supplied (source_plan_uuid equal or NULL).", "type": "string", "required": True},
        }
        params.update(filter_metadata_params(_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES))
        params.update(pagination_metadata_params())
        return bug_impact_metadata(
            cls,
            params,
            {"success": {"description": "A page of BugImpact payloads for the bug, plus pagination metadata."}},
            [{
                "description": "List unresolved impacts of a bug.",
                "command": {
                    "plan": "plan_manager",
                    "bug_id": "11111111-1111-1111-1111-111111111111",
                    "unresolved_impacts": True,
                },
            }],
            error_cases={
                "BUG_NOT_FOUND": {
                    "description": "The supplied bug_id does not resolve to an existing bug_report record, OR the bug's source_plan_uuid is set and differs from the resolved plan (plan/bug consistency guard). Bugs with source_plan_uuid NULL are accepted under any valid plan.",
                    "message": "bug not found: {bug_id}",
                    "solution": "Call bug_list for the plan and retry with a bug uuid anchored to that plan (or with a plan-unanchored bug).",
                },
            },
            best_practices=[
                "The optional plan parameter is a consistency guard: when supplied, a bug whose source_plan_uuid is set to a different plan raises BUG_NOT_FOUND instead of listing foreign impacts. Omit it to skip the guard entirely.",
                "Bugs with source_plan_uuid NULL (e.g. command-anchored bugs) are listable under any supplied plan; the plan does not further filter their impacts.",
                "A supplied but nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "The project filter matches transitively: an impact whose target_project_id equals the filter value matches directly, and an impact with target_project_id NULL still matches when its own target_plan_uuid is bound to that project (plan.project_ids).",
                "Set unresolved_impacts=true to see only impacts still needing action.",
                "Combine created_after and created_before to scope impacts to a time window.",
                "Use limit and offset to page through large impact sets instead of fetching all at once.",
                "Filter by a specific status to inspect one lifecycle stage instead of unresolved_impacts.",
            ],
        )

    async def execute(
        self,
        bug_id: str,
        plan: str | None = None,
        status: str | None = None,
        impact_type: str | None = None,
        unresolved_impacts: bool | None = None,
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
                bug_uuid = validate_uuid(bug_id)
                bug_record = get_bug(conn, bug_uuid)
                if bug_record is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                if (
                    plan_record is not None
                    and bug_record.source_plan_uuid is not None
                    and bug_record.source_plan_uuid != plan_record.uuid
                ):
                    raise DomainCommandError(
                        "BUG_NOT_FOUND",
                        f"bug not found: {bug_id} (anchored to plan {bug_record.source_plan_uuid}, not the resolved plan {plan_record.uuid})",
                    )
                raw_params = {
                    "status": status,
                    "impact_type": impact_type,
                    "unresolved_impacts": unresolved_impacts,
                    "created_after": created_after,
                    "created_before": created_before,
                    "project": project,
                }
                filters = parse_filters(raw_params, _LIST_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                records = list_bug_impacts(conn, bug_uuid=bug_uuid, status=filters.get("status"), include_deleted=False)
                impact_type_filter = filters.get("impact_type")
                if impact_type_filter is not None:
                    records = [r for r in records if r.impact_type == impact_type_filter]
                if filters.get("unresolved_impacts"):
                    records = [r for r in records if r.status not in _RESOLVED_IMPACT_STATUSES]
                project_value = filters.get("project")
                if project_value is not None:
                    project_uuid = validate_uuid(project_value)
                    bound_plan_uuids = resolve_project_plan_uuids(conn, project_uuid)
                    records = [
                        r for r in records
                        if (r.target_project_id is not None and r.target_project_id == project_uuid)
                        or (r.target_plan_uuid is not None and r.target_plan_uuid in bound_plan_uuids)
                    ]
                after = filters.get("created_after")
                if after is not None:
                    after_dt = datetime.fromisoformat(after)
                    records = [r for r in records if datetime.fromisoformat(r.created_at) >= after_dt]
                before = filters.get("created_before")
                if before is not None:
                    before_dt = datetime.fromisoformat(before)
                    records = [r for r in records if datetime.fromisoformat(r.created_at) <= before_dt]
                total = len(records)
                page = records[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "bug_impacts": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
