"""Command: set the primary project UUID for a plan."""

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_project_metadata import get_plan_project_set_primary_metadata
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.domain.project_binding import set_primary_project
from plan_manager.runtime.context import db_connection


class PlanProjectSetPrimaryCommand(Command):
    name: ClassVar[str] = "plan_project_set_primary"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Set the primary project UUID for a plan."
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier: UUID or unique name."},
                "project_id": {"type": "string", "description": "Already attached analysis-server project UUID."},
            },
            "required": ["plan", "project_id"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        return params

    async def execute(self, plan: str, project_id: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                updated = set_primary_project(conn, p, project_id)
                return SuccessResult(data={
                    "plan_uuid": str(updated.uuid),
                    "project_ids": updated.project_ids,
                    "primary_project_id": updated.primary_project_id,
                })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_project_set_primary_metadata(cls)
