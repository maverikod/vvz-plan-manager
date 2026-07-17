"""Command: list the direct reverse-dependency edges (projects that depend on a given project) (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import list_reverse_dependents


class ProjectDependentsCommand(Command):
    name: ClassVar[str] = "project_dependents"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List the projects that directly depend on a given project (reverse-dependency lookup)."
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
                        "Plan identifier (name or UUID), optional. project_dependency edges carry "
                        "no plan column, so a supplied plan is only checked for existence "
                        "(PLAN_NOT_FOUND if it does not resolve); it never further filters the "
                        "reverse-dependency result. When omitted, no existence check is performed."
                    ),
                },
                "project_id": {"type": "string", "description": "External analysis-server UUID of the project whose dependents are requested (C-032)."},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": (
                    "Plan identifier (name or UUID), optional. project_dependency edges carry "
                    "no plan column, so a supplied plan is only checked for existence "
                    "(PLAN_NOT_FOUND if it does not resolve); it never further filters the "
                    "reverse-dependency result. When omitted, no existence check is performed."
                ),
                "type": "string",
                "required": False,
            },
            "project_id": {"description": "External analysis-server UUID of the project whose dependents are requested (C-032).", "type": "string", "required": True},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The direct reverse-dependency edge payload list: active edges whose depends_on_project_id equals project_id."}},
            [{
                "description": "List the direct dependents of a project.",
                "command": {
                    "plan": "my-plan",
                    "project_id": "22222222-2222-2222-2222-222222222222",
                },
            }],
            best_practices=[
                "Direct reverse lookup only (one hop); use project_dependency_discover for the transitive impact set.",
                "Only active, non-deleted edges are returned.",
                "Returns full edge payloads (dependency_type, confidence, version_constraint), unlike discover's bare id list.",
                "plan is optional and, when supplied, is checked only for existence (project_dependency has no plan column to filter by); a nonexistent plan still raises PLAN_NOT_FOUND.",
            ],
        )

    async def execute(
        self,
        project_id: str,
        plan: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                if plan is not None:
                    resolve_plan(conn, plan)
                records = list_reverse_dependents(conn, validate_uuid(project_id))
                return SuccessResult(data={"reverse_dependents": [r.to_payload() for r in records]})
        except Exception as exc:
            return map_exception(exc)
