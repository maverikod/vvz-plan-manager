"""Command: list a paginated page of runtime parameters for a plan or branch scope."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.commands.step_runtime_list_metadata import get_step_runtime_list_metadata
from plan_manager.domain.step_runtime import get_runtime_record
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.step_runtime_scope import scoped_steps

class StepRuntimeListCommand(Command):
    """List a paginated, artifact_path-sorted page of runtime records for every step in a scope."""

    name: ClassVar[str] = "step_runtime_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated, artifact_path-sorted page of runtime parameters for plan steps in a scope."
    category: ClassVar[str] = "step"
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
                "scope": {
                    "type": "string",
                    "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                },
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_runtime_list_metadata(cls)

    async def execute(
        self,
        plan: str,
        scope: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                nodes = load_steps(conn, p.uuid)
                try:
                    steps = scoped_steps(nodes, scope)
                except ValueError as exc:
                    return domain_error("STEP_NOT_FOUND", str(exc))
                items = sorted(
                    (
                        {
                            "artifact_path": artifact_path_of(nodes, step),
                            "step_id": step.step_id,
                            "runtime": get_runtime_record(conn, p.uuid, step.uuid),
                        }
                        for step in steps
                    ),
                    key=lambda item: item["artifact_path"],
                )
                total = len(items)
                page = items[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "runtime": page,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
