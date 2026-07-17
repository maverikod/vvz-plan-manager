"""Command: list BugReports filtered and paginated per the uniform runtime filtering contract (C-020, C-030)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from plan_manager.commands.bug_command_metadata import bug_metadata, filter_schema_properties, filter_metadata_params, pagination_schema_properties, pagination_metadata_params
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import parse_filters, parse_pagination
from plan_manager.domain.bug_report import BUG_KINDS, BUG_SEVERITIES, BUG_STATUSES, BugKind, BugSeverity, BugStatus
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import list_bugs

# BugReport has no assignee column (only owner), so assignee is deliberately excluded
BUG_LIST_FILTER_FIELDS = ["project", "file", "anchor_plan", "revision", "step", "status", "kind", "severity", "priority", "owner", "created_after", "created_before", "active_only"]

_FILTER_ENUMS = {"status": BUG_STATUSES, "kind": BUG_KINDS, "severity": BUG_SEVERITIES}

# Ordered vocabularies published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error.
_ENUM_OVERRIDES = {
    "status": [e.value for e in BugStatus],
    "kind": [e.value for e in BugKind],
    "severity": [e.value for e in BugSeverity],
}

# These are the statuses treated as terminal/inactive for the active_only filter
BUG_TERMINAL_STATUSES = frozenset({"closed", "rejected", "duplicate"})


class BugListCommand(Command):
    name: ClassVar[str] = "bug_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List bug reports with filtering and pagination."
    category: ClassVar[str] = "bug"
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
                    "description": "Plan identifier (name or UUID). Scopes the listing: only bugs whose source_plan_uuid equals the resolved plan are returned; bugs anchored to other plans or with no plan anchor (source_plan_uuid NULL) are excluded. No transitive matching is performed.",
                },
                **filter_schema_properties(BUG_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {
                "type": prop["type"],
                "description": prop["description"],
                "required": name in schema["required"],
                **({"enum": prop["enum"]} if "enum" in prop else {}),
            }
            for name, prop in schema["properties"].items()
        }
        return bug_metadata(
            cls,
            params,
            {"type": "array", "description": "A page of BugReport payloads plus total/limit/offset."},
            [{"description": "List open bugs owned by alice.", "command": {"plan": "my-plan", "owner": "alice", "active_only": True}}],
            best_practices=[
                "The required plan parameter scopes the listing by direct source anchor: only bugs with source_plan_uuid equal to the resolved plan are returned; NULL and foreign plan anchors are excluded (no transitive matching via other anchor fields).",
                "A nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "Set active_only=True to exclude closed, rejected, and duplicate bugs.",
                "The project filter matches source_project_id only, not other anchor fields.",
                "Use limit/offset for pagination and compare offset+limit against total to detect more pages.",
                "Combine file/anchor_plan/revision/step filters with status/kind/severity/owner for precise anchor lookups.",
            ],
        )

    async def execute(
        self,
        plan: str,
        project: str | None = None,
        file: str | None = None,
        anchor_plan: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        severity: str | None = None,
        priority: int | None = None,
        owner: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        active_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan)
                raw_params = {
                    "project": project,
                    "file": file,
                    "anchor_plan": anchor_plan,
                    "revision": revision,
                    "step": step,
                    "status": status,
                    "kind": kind,
                    "severity": severity,
                    "priority": priority,
                    "owner": owner,
                    "created_after": created_after,
                    "created_before": created_before,
                    "active_only": active_only,
                    "limit": limit,
                    "offset": offset,
                }
                filters = parse_filters(raw_params, BUG_LIST_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination(raw_params)
                project_value = filters.get("project")
                source_project_uuid = validate_uuid(project_value) if project_value is not None else None
                bugs = list_bugs(
                    conn,
                    status=filters.get("status"),
                    kind=filters.get("kind"),
                    severity=filters.get("severity"),
                    owner=filters.get("owner"),
                    source_project_id=source_project_uuid,
                    source_plan_uuid=plan_record.uuid,
                    include_deleted=False,
                )
                file_value = filters.get("file")
                if file_value is not None:
                    bugs = [b for b in bugs if b.source_file_path == file_value]
                anchor_plan_value = filters.get("anchor_plan")
                if anchor_plan_value is not None:
                    bugs = [b for b in bugs if b.source_plan_uuid is not None and str(b.source_plan_uuid) == anchor_plan_value]
                revision_value = filters.get("revision")
                if revision_value is not None:
                    bugs = [b for b in bugs if b.source_revision_uuid is not None and str(b.source_revision_uuid) == revision_value]
                step_value = filters.get("step")
                if step_value is not None:
                    bugs = [b for b in bugs if b.source_step_uuid is not None and str(b.source_step_uuid) == step_value]
                priority_value = filters.get("priority")
                if priority_value is not None:
                    bugs = [b for b in bugs if b.priority_nice == priority_value]
                created_after_value = filters.get("created_after")
                if created_after_value is not None:
                    bugs = [b for b in bugs if b.created_at >= created_after_value]
                created_before_value = filters.get("created_before")
                if created_before_value is not None:
                    bugs = [b for b in bugs if b.created_at <= created_before_value]
                if filters.get("active_only"):
                    bugs = [b for b in bugs if b.status not in BUG_TERMINAL_STATUSES]
                total = len(bugs)
                page = bugs[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={"bugs": [b.to_payload() for b in page], "total": total, "limit": pagination.limit, "offset": pagination.offset})
        except Exception as exc:
            return map_exception(exc)
