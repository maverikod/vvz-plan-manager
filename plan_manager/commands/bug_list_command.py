"""Command: list BugReports filtered and paginated per the uniform runtime filtering contract (C-020, C-030)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from plan_manager.commands.bug_command_metadata import bug_metadata, filter_schema_properties, filter_metadata_params, pagination_schema_properties, pagination_metadata_params
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import parse_filters, parse_pagination
from plan_manager.commands.list_projection import parse_view, project_entities, view_schema_properties
from plan_manager.domain.bug_report import BUG_KINDS, BUG_SEVERITIES, BUG_STATUSES, BugKind, BugSeverity, BugStatus
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import list_bugs_page

# BugReport has no assignee column (only owner), so assignee is deliberately excluded
BUG_LIST_FILTER_FIELDS = ["project", "file", "anchor_plan", "revision", "step", "status", "kind", "severity", "priority", "owner", "created_after", "created_before", "active_only", "unanchored_only"]

_FILTER_ENUMS = {"status": BUG_STATUSES, "kind": BUG_KINDS, "severity": BUG_SEVERITIES}

# Ordered vocabularies published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error.
_ENUM_OVERRIDES = {
    "status": [e.value for e in BugStatus],
    "kind": [e.value for e in BugKind],
    "severity": [e.value for e in BugSeverity],
}

# These are the statuses treated as terminal/inactive for the active_only filter.
# The SQL predicate now lives in bug_report_store.list_bugs_page (_TERMINAL_BUG_STATUSES);
# this copy is kept only as the documented, importable vocabulary for callers/tests.
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
                    "description": "Plan identifier (name or UUID), optional. When supplied, scopes the listing: only bugs whose source_plan_uuid equals the resolved plan are returned; bugs anchored to other plans or with no plan anchor (source_plan_uuid NULL) are excluded (direct anchor equality, no transitive matching). When omitted, no plan scoping is applied. The project filter (below) is independent and IS transitive: it also matches bugs whose source_plan_uuid is bound to that project via plan.project_ids, even when the bug's own source_project_id is NULL.",
                },
                **filter_schema_properties(BUG_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": [],
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
            {"type": "array", "description": "A page of BugReport payloads (or, with view=summary, compact projections) plus total/limit/offset."},
            [{"description": "List open bugs owned by alice.", "command": {"plan": "my-plan", "owner": "alice", "active_only": True}}],
            best_practices=[
                "view=summary returns a compact per-row projection (uuid, bug_uuid, title, kind, severity, status, priority_nice, source_anchor_type, source_ref_id, updated_at) instead of the full BugReport record (drops short/detailed_description, expected/actual_behavior, reproduction, evidence, environment); use bug_get for a single bug's full detail.",
                "The optional plan parameter scopes the listing by direct source anchor: only bugs with source_plan_uuid equal to the resolved plan are returned; NULL and foreign plan anchors are excluded (no transitive matching via other anchor fields). Omit it to list across all plans.",
                "A supplied but nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "Set active_only=True to exclude closed, rejected, and duplicate bugs.",
                "Set unanchored_only=True to find bugs whose source_anchor_type is unidentified -- including those recorded unanchored because bug_create/bug_reanchor could not confirm the requested project/file anchor against the Code Analysis server (see anchor_confirmation in the bug_create/bug_reanchor response).",
                "The project filter matches transitively: a bug whose source_project_id equals the filter value matches directly, and a bug with source_project_id NULL still matches when its source_plan_uuid is bound to that project (plan.project_ids).",
                "Use limit/offset for pagination and compare offset+limit against total to detect more pages.",
                "Combine file/anchor_plan/revision/step filters with status/kind/severity/owner for precise anchor lookups.",
            ],
        )

    async def execute(
        self,
        plan: str | None = None,
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
        unanchored_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view)
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan) if plan is not None else None
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
                    "unanchored_only": unanchored_only,
                    "limit": limit,
                    "offset": offset,
                }
                filters = parse_filters(raw_params, BUG_LIST_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination(raw_params)
                project_value = filters.get("project")
                project_uuid = validate_uuid(project_value) if project_value is not None else None
                anchor_plan_value = filters.get("anchor_plan")
                anchor_plan_uuid = validate_uuid(anchor_plan_value) if anchor_plan_value is not None else None
                revision_value = filters.get("revision")
                revision_uuid = validate_uuid(revision_value) if revision_value is not None else None
                step_value = filters.get("step")
                step_uuid = validate_uuid(step_value) if step_value is not None else None
                bugs, total = list_bugs_page(
                    conn,
                    status=filters.get("status"),
                    kind=filters.get("kind"),
                    severity=filters.get("severity"),
                    owner=filters.get("owner"),
                    source_plan_uuid=plan_record.uuid if plan_record is not None else None,
                    anchor_plan_uuid=anchor_plan_uuid,
                    source_file_path=filters.get("file"),
                    source_revision_uuid=revision_uuid,
                    source_step_uuid=step_uuid,
                    priority_nice=filters.get("priority"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    active_only=bool(filters.get("active_only")),
                    unanchored_only=bool(filters.get("unanchored_only")),
                    project_id=project_uuid,
                    limit=pagination.limit,
                    offset=pagination.offset,
                    include_deleted=False,
                )
                return SuccessResult(data={"bugs": project_entities(bugs, view_value), "total": total, "limit": pagination.limit, "offset": pagination.offset})
        except Exception as exc:
            return map_exception(exc)
