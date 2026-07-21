"""Command: detach an analysis-server project UUID from a plan."""

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_project_metadata import get_plan_project_detach_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.project_binding import detach_project
from plan_manager.runtime.context import db_connection


class PlanProjectDetachCommand(Command):
    name: ClassVar[str] = "plan_project_detach"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Detach a project UUID from a plan and clear matching step bindings."
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
                "project_id": {"type": "string", "description": "Analysis-server project UUID to detach."},
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
                return SuccessResult(data=detach_project(conn, p, project_id))
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_project_detach_metadata(cls)
