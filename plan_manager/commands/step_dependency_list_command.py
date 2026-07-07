"""Command: list one step's dependencies and reverse dependencies."""
from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_dependency_list_metadata import (
    get_step_dependency_list_metadata,
)
from plan_manager.commands.step_dependency_ops import (
    dependents_paths,
    head_revision_str,
    render_depends,
    resolve_target,
)
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class StepDependencyListCommand(Command):
    """Return the direct dependencies and dependents of one step."""

    name: ClassVar[str] = "step_dependency_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "List one step's top-level depends_on edges and the sibling steps that "
        "depend on it."
    )
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID).",
                },
                "step_id": {
                    "type": "string",
                    "description": "Canonical step path, bare step id if unambiguous, or step UUID.",
                },
                "include_dependents": {
                    "type": "boolean",
                    "description": "Include the reverse dependency (dependents) list.",
                    "default": True,
                },
            },
            "required": ["plan", "step_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_dependency_list_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return super().validate_params(params)

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            step_id = kwargs["step_id"]
            include_dependents = kwargs.get("include_dependents", True)
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_target(nodes, step_id)
                data: dict[str, Any] = {
                    "step": canonical_step_path(nodes, target),
                    "depends_on": render_depends(nodes, target, list(target.depends_on)),
                    "revision_uuid": head_revision_str(conn, p),
                }
                if include_dependents:
                    data["dependents"] = dependents_paths(nodes, target)
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
