"""Command: list BugImpact records for a bug, with uniform filtering and pagination (C-022, C-029, C-030)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import BASE_PARAMETERS, bug_impact_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_impact_store import list_bug_impacts

_LIST_FILTER_FIELDS = ["status", "unresolved_impacts", "created_after", "created_before"]
_RESOLVED_IMPACT_STATUSES = frozenset({"resolved", "verified", "unaffected", "skipped"})


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
            "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
            "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug_report whose impacts are listed."},
        }
        properties.update(filter_schema_properties(_LIST_FILTER_FIELDS))
        properties.update(pagination_schema_properties())
        return {
            "type": "object",
            "properties": properties,
            "required": ["plan", "bug_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug_id": {"description": "UUID of the bug_report whose impacts are listed.", "type": "string", "required": True},
        }
        params.update(filter_metadata_params(_LIST_FILTER_FIELDS))
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
            best_practices=[
                "Set unresolved_impacts=true to see only impacts still needing action.",
                "Combine created_after and created_before to scope impacts to a time window.",
                "Use limit and offset to page through large impact sets instead of fetching all at once.",
                "Filter by a specific status to inspect one lifecycle stage instead of unresolved_impacts.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        status: str | None = None,
        unresolved_impacts: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                raw_params = {
                    "status": status,
                    "unresolved_impacts": unresolved_impacts,
                    "created_after": created_after,
                    "created_before": created_before,
                }
                filters = parse_filters(raw_params, _LIST_FILTER_FIELDS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                records = list_bug_impacts(conn, bug_uuid=bug_uuid, status=filters.get("status"), include_deleted=False)
                if filters.get("unresolved_impacts"):
                    records = [r for r in records if r.status not in _RESOLVED_IMPACT_STATUSES]
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
