"""Command: list a paginated page of project dependency edges with the group's own filters (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import list_project_dependencies

class ProjectDependencyListCommand(Command):
    name: ClassVar[str] = "project_dependency_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of project dependency edges filtered by dependent/depends-on project and active status."
    category: ClassVar[str] = "project_dependency"
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
                        "Plan identifier (name or UUID). Scopes the listing: only dependency "
                        "edges where AT LEAST ONE endpoint (dependent_project_id or "
                        "depends_on_project_id) is among the resolved plan's bound project "
                        "uuids (plan_project bindings) are returned. A plan with zero bound "
                        "projects yields an empty page."
                    ),
                },
                "dependent_project_id": {"type": "string", "description": "Filter: only edges where this project is the dependent."},
                "depends_on_project_id": {"type": "string", "description": "Filter: only edges where this project is depended on."},
                "active_only": {"type": "boolean", "description": "When true, only active edges are returned.", "default": False},
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
                    "Plan identifier (name or UUID). Scopes the listing: only dependency "
                    "edges where AT LEAST ONE endpoint (dependent_project_id or "
                    "depends_on_project_id) is among the resolved plan's bound project "
                    "uuids (plan_project bindings) are returned. A plan with zero bound "
                    "projects yields an empty page."
                ),
                "type": "string",
                "required": True,
            },
            "dependent_project_id": {"description": "Filter: only edges where this project is the dependent.", "type": "string", "required": False},
            "depends_on_project_id": {"description": "Filter: only edges where this project is depended on.", "type": "string", "required": False},
            "active_only": {"description": "When true, only active edges are returned; defaults to false.", "type": "boolean", "required": False},
            **pagination_metadata_params(),
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The filtered, paginated list of project dependency edge payloads, plus total/limit/offset."}},
            [{
                "description": "List active edges where a project is the dependent.",
                "command": {
                    "plan": "my-plan",
                    "dependent_project_id": "11111111-1111-1111-1111-111111111111",
                    "active_only": True,
                },
            }],
            best_practices=[
                "The required plan parameter scopes the listing to edges touching the plan's bound projects (plan_project bindings): an edge matches when at least one endpoint is a bound project uuid. A plan with zero bound projects always yields an empty page; bind projects with plan_project_attach first.",
                "A nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "Explicit dependent_project_id / depends_on_project_id filters intersect (AND) with the plan scope; they never widen it beyond the plan's bound projects.",
                "dependent_project_id and depends_on_project_id filters combine with AND when both are supplied.",
                "Soft-deleted edges are always excluded from results, regardless of active_only.",
                "total in the response is the full filtered count before pagination, not the returned page size.",
                "Results are ordered oldest-created first; use limit/offset to page through large edge sets.",
                "limit outside [1, 200] or a negative offset now raises INVALID_PAGINATION instead of being silently applied.",
            ],
        )

    async def execute(
        self,
        plan: str,
        dependent_project_id: str | None = None,
        depends_on_project_id: str | None = None,
        active_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                bound_project_uuids = [uuid.UUID(pid) for pid in p.project_ids]
                records = list_project_dependencies(
                    conn,
                    dependent_project_id=validate_uuid(dependent_project_id) if dependent_project_id else None,
                    depends_on_project_id=validate_uuid(depends_on_project_id) if depends_on_project_id else None,
                    active_only=active_only,
                    project_ids=bound_project_uuids,
                )
                total = len(records)
                page = records[pagination.offset: pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "project_dependencies": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
