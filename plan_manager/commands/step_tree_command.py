"""Command: return the full step tree of a plan."""

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_ref import (
    canonical_step_path,
    parent_canonical_path,
    parent_uuid,
)
from plan_manager.commands.step_tree_metadata import get_step_tree_metadata
from plan_manager.domain.step_runtime import get_runtime_record
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import load_steps


class StepTreeCommand(Command):
    """Return the plan's full step tree with statuses."""

    name: ClassVar[str] = "step_tree"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return the plan's full step tree as a flat, sorted list with statuses."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_tree.

        Returns:
            A JSON-Schema-shaped dict with `type`, `properties`, `required`,
            and `additionalProperties` keys.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
                },
                "include_runtime": {
                    "type": "boolean",
                    "description": "When true, include each step's runtime parameters in the response.",
                    "default": False,
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_tree parameters.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.
        """
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        include_runtime: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return the plan's full step tree as a flat, sorted list.

        Args:
            plan: Plan identifier (UUID or name).
            include_runtime: Whether to include runtime parameters.

        Returns:
            SuccessResult with data {"tree": [...]} on success, where each
            tree entry is {"path", "step_id", "slug", "level", "status"}
            sorted by (level, path); ErrorResult with a stable domain error
            code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                tree = []
                for s in nodes.values():
                    entry = {
                        "uuid": str(s.uuid),
                        "path": canonical_step_path(nodes, s),
                        "step_id": s.step_id,
                        "slug": s.slug,
                        "level": s.level,
                        "project_id": s.project_id,
                        "status": s.status,
                        "parent_path": parent_canonical_path(nodes, s),
                        "parent_uuid": parent_uuid(nodes, s),
                        "artifact_path": artifact_path_of(nodes, s),
                    }
                    if include_runtime:
                        entry["runtime"] = get_runtime_record(conn, p.uuid, s.uuid)
                    tree.append(entry)
                tree.sort(key=lambda entry: (entry["level"], entry["path"]))
                return SuccessResult(data={"tree": tree})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_tree.

        Returns:
            The dict produced by `get_step_tree_metadata(cls)`.
        """
        return get_step_tree_metadata(cls)
