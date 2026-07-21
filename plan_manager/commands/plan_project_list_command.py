"""Command: list project UUIDs bound to a plan."""

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_project_metadata import get_plan_project_list_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection


class PlanProjectListCommand(Command):
    name: ClassVar[str] = "plan_project_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List project UUIDs bound to a plan."
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
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        plan: str,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                total = len(p.project_ids)
                page = p.project_ids[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "plan_uuid": str(p.uuid),
                    "project_ids": page,
                    "primary_project_id": p.primary_project_id,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_project_list_metadata(cls)
