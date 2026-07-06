"""Command: attach an analysis-server project UUID to a plan."""

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_project_metadata import get_plan_project_attach_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.project_binding import attach_project
from plan_manager.runtime.context import db_connection


class PlanProjectAttachCommand(Command):
    name: ClassVar[str] = "plan_project_attach"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Attach an analysis-server project UUID to a plan."
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
                "project_id": {"type": "string", "description": "Analysis-server project UUID."},
                "primary": {"type": "boolean", "description": "Also set this project as primary.", "default": False},
            },
            "required": ["plan", "project_id"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        params["primary"] = params.get("primary", False)
        return params

    async def execute(self, plan: str, project_id: str, primary: bool = False, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                updated, already_exists = attach_project(conn, p, project_id, primary=primary)
                return SuccessResult(data={
                    "plan_uuid": str(updated.uuid),
                    "project_ids": updated.project_ids,
                    "primary_project_id": updated.primary_project_id,
                    "already_exists": already_exists,
                })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_project_attach_metadata(cls)
