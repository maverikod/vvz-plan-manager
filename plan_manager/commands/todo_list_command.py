"""Command: list TODO work items with uniform filtering and pagination (C-029, C-030, C-031)."""

from __future__ import annotations

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
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import list_todos

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

_ACTIVE_STATUSES = frozenset({"open", "ready", "in_progress", "blocked"})


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
            {"success": {"description": "A page of TodoItem payloads plus the total match count before pagination."}},
            [{"description": "List active TODO items owned by an owner.", "command": {"active_only": True, "owner": "agent-1", "limit": 20}}],
            best_practices=[
                "active_only restricts results to statuses open, ready, in_progress, blocked, excluding resolved/closed/cancelled — combine with owner or assignee to build a personal work queue.",
                "unanchored_only restricts to primary_anchor_type == none, useful for finding TODOs still needing a primary anchor assigned.",
                "status and kind are pushed down to SQL as exact-match filters; all other filters (project, file, anchor_plan, revision, step, priority, owner, assignee, created_after/before) are applied in-memory after fetch.",
                "The model filter parameter is accepted in the schema but is not currently applied to the result set — passing it has no filtering effect.",
                "total_count reflects the filtered count before pagination is applied, not the page size — use it to detect additional pages.",
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
                resolved_anchor_plan_uuid: str | None = None
                if anchor_plan is not None:
                    resolved_anchor_plan_uuid = str(resolve_plan(conn, anchor_plan).uuid)
                records = list_todos(conn, status=filters.get("status"), kind=filters.get("kind"))
                filtered = []
                for item in records:
                    if "project" in filters.values and str(item.anchor_project_id) != filters.get("project"):
                        continue
                    if "file" in filters.values and item.anchor_file_path != filters.get("file"):
                        continue
                    if resolved_anchor_plan_uuid is not None and str(item.anchor_plan_uuid) != resolved_anchor_plan_uuid:
                        continue
                    if "revision" in filters.values and str(item.anchor_revision_uuid) != filters.get("revision"):
                        continue
                    if "step" in filters.values and str(item.anchor_step_uuid) != filters.get("step"):
                        continue
                    if "priority" in filters.values and item.priority_nice != filters.get("priority"):
                        continue
                    if "owner" in filters.values and item.created_by != filters.get("owner"):
                        continue
                    if "assignee" in filters.values and item.assigned_to != filters.get("assignee"):
                        continue
                    if "created_after" in filters.values and item.created_at < filters.get("created_after"):
                        continue
                    if "created_before" in filters.values and item.created_at > filters.get("created_before"):
                        continue
                    if filters.get("active_only") and item.status not in _ACTIVE_STATUSES:
                        continue
                    if filters.get("unanchored_only") and item.primary_anchor_type != "none":
                        continue
                    filtered.append(item)
                total_count = len(filtered)
                page = filtered[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "todos": [r.to_payload() for r in page],
                    "total_count": total_count,
                })
        except Exception as exc:
            return map_exception(exc)
