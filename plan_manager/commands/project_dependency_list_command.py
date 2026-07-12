"""Command: list project dependency edges with the group's own filter/pagination params (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import list_project_dependencies


class ProjectDependencyListCommand(Command):
    name: ClassVar[str] = "project_dependency_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List project dependency edges filtered by dependent/depends-on project and active status."
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
                "plan": {"type": "string", "description": "Plan identifier."},
                "dependent_project_id": {"type": "string", "description": "Filter: only edges where this project is the dependent."},
                "depends_on_project_id": {"type": "string", "description": "Filter: only edges where this project is depended on."},
                "active_only": {"type": "boolean", "description": "When true, only active edges are returned.", "default": False},
                "limit": {"type": "integer", "description": "Maximum number of edges to return.", "minimum": 1, "maximum": 200, "default": 50},
                "offset": {"type": "integer", "description": "Number of edges to skip before returning results.", "minimum": 0, "default": 0},
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "dependent_project_id": {"description": "Filter: only edges where this project is the dependent.", "type": "string", "required": False},
            "depends_on_project_id": {"description": "Filter: only edges where this project is depended on.", "type": "string", "required": False},
            "active_only": {"description": "When true, only active edges are returned; defaults to false.", "type": "boolean", "required": False},
            "limit": {"description": "Maximum number of edges to return (1-200); defaults to 50.", "type": "integer", "required": False},
            "offset": {"description": "Number of edges to skip before returning results; defaults to 0.", "type": "integer", "required": False},
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
                "dependent_project_id and depends_on_project_id filters combine with AND when both are supplied.",
                "Soft-deleted edges are always excluded from results, regardless of active_only.",
                "total in the response is the full filtered count before pagination, not the returned page size.",
                "Results are ordered oldest-created first; use limit/offset to page through large edge sets.",
            ],
        )

    async def execute(
        self,
        plan: str,
        dependent_project_id: str | None = None,
        depends_on_project_id: str | None = None,
        active_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                records = list_project_dependencies(
                    conn,
                    dependent_project_id=uuid.UUID(dependent_project_id) if dependent_project_id else None,
                    depends_on_project_id=uuid.UUID(depends_on_project_id) if depends_on_project_id else None,
                    active_only=active_only,
                )
                total = len(records)
                page = records[offset: offset + limit]
                return SuccessResult(data={
                    "project_dependencies": [r.to_payload() for r in page],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                })
        except Exception as exc:
            return map_exception(exc)
