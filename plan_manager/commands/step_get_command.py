"""Command: return one step of a plan with its resolved context."""

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_ref import (
    canonical_step_path,
    parent_canonical_path,
    parent_uuid,
    resolve_step_ref,
)
from plan_manager.commands.step_get_metadata import get_step_get_metadata
from plan_manager.domain.step_runtime import get_runtime_record
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import load_steps


class StepGetCommand(Command):
    """Return one step of a plan with resolved parent context."""

    name: ClassVar[str] = "step_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return one step of a plan identified by step_id, with resolved parent context."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_get.

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
                "step_id": {
                    "type": "string",
                    "description": "Human-readable step identifier (e.g. G-001, T-006, A-003) to look up within the plan.",
                },
                "include_runtime": {
                    "type": "boolean",
                    "description": "When true, include the step's runtime parameters in the response.",
                    "default": False,
                },
            },
            "required": ["plan", "step_id"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_get parameters.

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
        step_id: str,
        include_runtime: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return one step of the plan with its resolved parent path.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable step identifier to look up.
            include_runtime: Whether to include runtime parameters.

        Returns:
            SuccessResult with the step's fields on success, or ErrorResult
            with a stable domain error code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_step_ref(nodes, step_id)
                data = {
                    "uuid": str(target.uuid),
                    "step_id": target.step_id,
                    "slug": target.slug,
                    "level": target.level,
                    "project_id": target.project_id,
                    "status": target.status,
                    "parent_path": parent_canonical_path(nodes, target),
                    "parent_uuid": parent_uuid(nodes, target),
                    "fields": target.fields,
                    "depends_on": target.depends_on,
                    "concepts": target.concepts,
                    "path": canonical_step_path(nodes, target),
                    "artifact_path": artifact_path_of(nodes, target),
                }
                if include_runtime:
                    data["runtime"] = get_runtime_record(conn, p.uuid, target.uuid)
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_get.

        Returns:
            The dict produced by `get_step_get_metadata(cls)`.
        """
        return get_step_get_metadata(cls)
