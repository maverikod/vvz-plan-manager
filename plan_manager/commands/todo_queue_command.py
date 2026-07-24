"""Command: surface a paginated page of the TODO-derived portion of the unified runtime work queue (C-029, C-031).

Todo f47a2db0: the queue was global-only (no plan/project scoping), forcing every caller
to fetch everything and filter client-side. anchor_plan and project add server-side
scoping, composing with the existing availability/lock filters and with each other.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.work_queue import build_unified_queue
from plan_manager.runtime.work_item import WorkKind, ResourceAvailability

# anchor_plan is resolved separately (name-or-UUID via resolve_plan, matching todo_list's
# convention), not through parse_filters' strict uuid-format validation, which would
# reject a plan name.
_QUEUE_FILTER_FIELDS = ["anchor_plan", "project"]
_PARSE_FILTER_FIELDS = [name for name in _QUEUE_FILTER_FIELDS if name != "anchor_plan"]


class TodoQueueCommand(Command):
    name: ClassVar[str] = "todo_queue"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Surface a paginated page of the TODO-derived portion of the unified runtime work queue."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "available_models": {"type": "array", "items": {"type": "string"}, "description": "Model identifiers currently available (bare model name and/or provider/model form)."},
                "runtime_available": {"type": "boolean", "description": "Whether the runtime executor is currently available (default true)."},
                "vast_available": {"type": "boolean", "description": "Whether the Vast runtime is currently available (default true)."},
                "locked_files": {"type": "array", "items": {"type": "string"}, "description": "Project-relative file paths currently locked."},
                "locked_projects": {"type": "array", "items": {"type": "string"}, "description": "Project-id strings currently locked."},
                **filter_schema_properties(_QUEUE_FILTER_FIELDS),
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "available_models": {"description": "Model identifiers currently available.", "type": "array", "required": False},
            "runtime_available": {"description": "Whether the runtime executor is currently available (default true).", "type": "boolean", "required": False},
            "vast_available": {"description": "Whether the Vast runtime is currently available (default true).", "type": "boolean", "required": False},
            "locked_files": {"description": "Project-relative file paths currently locked.", "type": "array", "required": False},
            "locked_projects": {"description": "Project-id strings currently locked.", "type": "array", "required": False},
            **filter_metadata_params(_QUEUE_FILTER_FIELDS),
            **pagination_metadata_params(),
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "A page of the ordered TODO-derived WorkItem payloads, plus total/limit/offset."}},
            [{"description": "Fetch the TODO-derived queue with default availability.", "command": {}}],
            best_practices=[
                "Only TODOs with status in open, in_progress, blocked are ever surfaced — resolved/closed/cancelled items never appear here, and there is no override to include them.",
                "The queue is computed by building the FULL unified runtime queue (AS-ready items, bugs, fixes, propagations, verifications, reviews, escalations) and then filtering to work_kind==todo — ordering and pausing reflect cross-kind priority, not a todo-only recomputation.",
                "runtime_available and vast_available both default to True when omitted; pass explicit false to simulate unavailability rather than omitting the flag.",
                "available_models/locked_files/locked_projects default to empty — by default no model is considered available and no locks are held; this command never probes actual runtime state, it only orders against the availability facts you supply.",
                "anchor_plan (todo f47a2db0) accepts a plan name or UUID, resolved the same way as todo_list's anchor_plan; a well-formed but nonexistent name/uuid raises PLAN_NOT_FOUND. Matches on the item's plan_uuid (the TODO's anchor_plan_uuid).",
                "project (todo f47a2db0) filters on WorkItem.project_uuid: for a TODO this is its own anchor_project_id when set, else the anchor plan's primary_project_id when derivable from anchor_plan_uuid; a TODO anchored to neither a project nor a plan with a primary_project_id never matches a project filter. Malformed UUID raises INVALID_FILTER.",
                "anchor_plan and project compose with each other and with the existing availability/lock filters (AND semantics) and are applied AFTER the todo_kind filter but BEFORE pagination, so total reflects the fully filtered count.",
                "Read-only: it never mutates plan truth or TODO records, it only reads and orders them.",
                "Page boundaries slice the globally ordered queue: the full unified queue is computed with unchanged cross-kind priority ordering, then offset/limit select a contiguous window of the todo-filtered (and, if given, anchor_plan/project-filtered) sequence.",
                "total is the full length of the fully filtered queue before pagination; compare offset+limit against total to detect additional pages.",
            ],
        )

    async def execute(
        self,
        available_models: list[str] | None = None,
        runtime_available: bool | None = None,
        vast_available: bool | None = None,
        locked_files: list[str] | None = None,
        locked_projects: list[str] | None = None,
        anchor_plan: str | None = None,
        project: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                filters = parse_filters({"project": project}, _PARSE_FILTER_FIELDS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                # anchor_plan accepts a plan name or UUID (siblings resolve the same way via
                # resolve_plan); a well-formed but nonexistent name/uuid raises PLAN_NOT_FOUND
                # from resolve_plan itself.
                resolved_anchor_plan_uuid: uuid.UUID | None = None
                if anchor_plan is not None:
                    resolved_anchor_plan_uuid = resolve_plan(conn, anchor_plan).uuid
                project_value = filters.get("project")
                project_uuid = uuid.UUID(project_value) if project_value is not None else None
                availability = ResourceAvailability(
                    available_models=frozenset(available_models) if available_models else frozenset(),
                    runtime_available=runtime_available if runtime_available is not None else True,
                    vast_available=vast_available if vast_available is not None else True,
                    locked_files=frozenset(locked_files) if locked_files else frozenset(),
                    locked_projects=frozenset(locked_projects) if locked_projects else frozenset(),
                )
                items = build_unified_queue(conn, as_ready=[], availability=availability)
                todo_items = [it for it in items if it.work_kind == WorkKind.TODO.value]
                if resolved_anchor_plan_uuid is not None:
                    todo_items = [it for it in todo_items if it.plan_uuid == resolved_anchor_plan_uuid]
                if project_uuid is not None:
                    todo_items = [it for it in todo_items if it.project_uuid == project_uuid]
                total = len(todo_items)
                page = todo_items[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "queue": [it.to_payload() for it in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
