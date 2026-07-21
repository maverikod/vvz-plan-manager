"""Command: discover the transitive reverse-dependent (suspected impact) project set for a source project (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import discover_suspected_targets


class ProjectDependencyDiscoverCommand(Command):
    name: ClassVar[str] = "project_dependency_discover"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Discover the transitive reverse-dependent project set (suspected impact set) for a source project."
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
                "source_project_id": {"type": "string", "description": "External analysis-server UUID of the project where the bug/defect originates (C-032)."},
            },
            "required": ["plan", "source_project_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "source_project_id": {"description": "External analysis-server UUID of the project where the bug/defect originates (C-032).", "type": "string", "required": True},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The transitive reverse-dependent project id list (the automatically-built suspected impact set), excluding the source project."}},
            [{
                "description": "Discover the suspected impact set for a source project.",
                "command": {
                    "plan": "my-plan",
                    "source_project_id": "22222222-2222-2222-2222-222222222222",
                },
            }],
            best_practices=[
                "Traverses only active, non-deleted edges; removed or inactive edges are not part of the impact set.",
                "Returns the full transitive closure of reverse dependents (multi-hop), not just direct dependents.",
                "The source_project_id itself is always excluded from the result, even under a cycle.",
                "Recomputed fresh from current edges on every call; nothing is cached or persisted.",
            ],
        )

    async def execute(
        self,
        plan: str,
        source_project_id: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                targets = discover_suspected_targets(conn, validate_uuid(source_project_id))
                return SuccessResult(data={"suspected_impact_project_ids": [str(t) for t in targets]})
        except Exception as exc:
            return map_exception(exc)
