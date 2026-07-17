"""Command: list TODO work items with uniform filtering and pagination (C-029, C-030, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.todo_command_metadata import todo_metadata
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
    parse_filters,
    parse_pagination,
)
from plan_manager.domain.todo import TODO_KINDS, TODO_STATUSES, TodoKind, TodoStatus
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import list_todos_page

TODO_LIST_FILTER_FIELDS = ["project", "file", "anchor_plan", "revision", "step", "status", "kind", "priority", "owner", "assignee", "model", "created_after", "created_before", "active_only", "unanchored_only"]

# anchor_plan is resolved separately (name-or-UUID via resolve_plan), not through parse_filters'
# uuid-format validation, which would reject a plan name.
_PARSE_FILTER_FIELDS = [name for name in TODO_LIST_FILTER_FIELDS if name != "anchor_plan"]

_FILTER_ENUMS = {"status": TODO_STATUSES, "kind": TODO_KINDS}

# Ordered vocabularies published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error.
_ENUM_OVERRIDES = {
    "status": [e.value for e in TodoStatus],
    "kind": [e.value for e in TodoKind],
}

# The SQL predicate now lives in todo_store.list_todos_page (_ACTIVE_TODO_STATUSES);
# this copy is kept as the documented, importable vocabulary for callers/tests.
_ACTIVE_STATUSES = frozenset({"open", "in_progress", "blocked"})


class TodoListCommand(Command):
    name: ClassVar[str] = "todo_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List TODO work items with uniform filtering and pagination."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        properties = {
            **filter_schema_properties(TODO_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_schema_properties(),
        }
        return {
            "type": "object",
            "properties": properties,
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **filter_metadata_params(TODO_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_metadata_params(),
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "A page of TodoItem payloads plus total (the full match count before pagination), limit, and offset."}},
            [{"description": "List active TODO items owned by an owner.", "command": {"active_only": True, "owner": "agent-1", "limit": 20}}],
            best_practices=[
                "active_only restricts results to statuses open, in_progress, blocked, excluding resolved/closed/cancelled — combine with owner or assignee to build a personal work queue.",
                "unanchored_only restricts to primary_anchor_type == none, useful for finding TODOs still needing a primary anchor assigned.",
                "status, kind, project, file, anchor_plan, revision, step, priority, owner, assignee, created_after/before, active_only, and unanchored_only are all pushed down to SQL as WHERE clauses -- none is applied by post-fetch, in-memory filtering.",
                "The project filter matches transitively: a TODO whose anchor_project_id equals the filter value matches directly, and a TODO with anchor_project_id NULL still matches when its anchor_plan_uuid is bound to that project (plan.project_ids).",
                "The model filter parameter is accepted in the schema but is not currently applied to the result set — passing it has no filtering effect.",
                "total reflects the filtered count before pagination is applied, not the page size — use it, together with limit and offset, to detect additional pages.",
            ],
        )

    async def execute(
        self,
        project: str | None = None,
        file: str | None = None,
        anchor_plan: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        priority: int | None = None,
        owner: str | None = None,
        assignee: str | None = None,
        model: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        active_only: bool | None = None,
        unanchored_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                raw_params: dict[str, Any] = {
                    "project": project, "file": file,
                    "revision": revision, "step": step, "status": status, "kind": kind,
                    "priority": priority, "owner": owner, "assignee": assignee, "model": model,
                    "created_after": created_after, "created_before": created_before,
                    "active_only": active_only, "unanchored_only": unanchored_only,
                }
                filters = parse_filters(raw_params, _PARSE_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                # anchor_plan accepts a plan name or UUID (siblings resolve the same way via resolve_plan);
                # a well-formed but nonexistent name/uuid raises PLAN_NOT_FOUND from resolve_plan itself.
                resolved_anchor_plan_uuid: uuid.UUID | None = None
                if anchor_plan is not None:
                    resolved_anchor_plan_uuid = resolve_plan(conn, anchor_plan).uuid
                project_value = filters.get("project")
                project_uuid = uuid.UUID(project_value) if project_value is not None else None
                revision_value = filters.get("revision")
                revision_uuid = validate_uuid(revision_value) if revision_value is not None else None
                step_value = filters.get("step")
                step_uuid = validate_uuid(step_value) if step_value is not None else None
                records, total = list_todos_page(
                    conn,
                    status=filters.get("status"),
                    kind=filters.get("kind"),
                    anchor_file_path=filters.get("file"),
                    anchor_plan_uuid=resolved_anchor_plan_uuid,
                    anchor_revision_uuid=revision_uuid,
                    anchor_step_uuid=step_uuid,
                    priority_nice=filters.get("priority"),
                    owner=filters.get("owner"),
                    assignee=filters.get("assignee"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    active_only=bool(filters.get("active_only")),
                    unanchored_only=bool(filters.get("unanchored_only")),
                    project_id=project_uuid,
                    limit=pagination.limit,
                    offset=pagination.offset,
                    include_deleted=False,
                )
                return SuccessResult(data={
                    "todos": [r.to_payload() for r in records],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
