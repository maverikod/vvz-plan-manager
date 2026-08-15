"""Read-only command: propose depends_on edges from the unambiguous inferred
execution graph (EIG block D, todo 004cd507). Never writes."""
from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.execution_dependency_ops import compute_suggested_changes
from plan_manager.commands.execution_dependency_suggest_metadata import (
    get_execution_dependency_suggest_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class ExecutionDependencySuggestCommand(Command):
    """Propose depends_on additions for a plan's unambiguous inferred execution-graph edges."""

    name: ClassVar[str] = "execution_dependency_suggest"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Compute the unambiguous object_producer/verification_target inferred edges "
        "of a plan that are not already implied by its explicit dependency graph, and "
        "return them as a step_dependency_apply-compatible depends_on proposal. Read-only."
    )
    category: ClassVar[str] = "graph"
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
                    "description": "Plan identifier (name or uuid) resolved against the catalog.",
                },
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_execution_dependency_suggest_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return super().validate_params(params)

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": kwargs.get("limit"), "offset": kwargs.get("offset")})
                nodes = load_steps(conn, p.uuid)
                proposal = compute_suggested_changes(nodes)
                edges = proposal["proposed_edges"]
                total = len(edges)
                page = edges[pagination.offset : pagination.offset + pagination.limit]
                data: dict[str, Any] = {
                    "proposed_changes": proposal["proposed_changes"],
                    "proposed_edges": page,
                    "total_proposed_edges": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                    "ambiguous_dependencies": proposal["ambiguous_dependencies"],
                    "missing_producers": proposal["missing_producers"],
                    "summary": {
                        "proposed_edge_count": total,
                        "proposed_step_count": len(proposal["proposed_changes"]),
                        "ambiguous_dependency_count": len(proposal["ambiguous_dependencies"]),
                        "missing_producer_count": len(proposal["missing_producers"]),
                    },
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
