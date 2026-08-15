"""Read-only command: extended execution graph of a plan (EIG block B, todo 16853f27)."""
from __future__ import annotations

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.execution_graph_metadata import get_execution_graph_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.execution_graph import build_execution_graph


class ExecutionGraphCommand(Command):
    """Return the extended execution graph (explicit + inferred edges) of a plan's steps."""

    name = "execution_graph"
    version = "1.0.0"
    descr = "Return the extended execution graph (explicit + inferred edges) of a plan's steps."
    category = "graph"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
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
    def metadata(cls) -> dict:
        return get_execution_graph_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": kwargs.get("limit"), "offset": kwargs.get("offset")})
                nodes = load_steps(conn, plan_obj.uuid)
                graph = build_execution_graph(nodes)
                combined_edges = graph["explicit_edges"] + graph["inferred_edges"]
                total = len(combined_edges)
                page = combined_edges[pagination.offset : pagination.offset + pagination.limit]
                data = {
                    "edges": page,
                    "total_edges": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                    "summary": {
                        "explicit_edge_count": len(graph["explicit_edges"]),
                        "inferred_edge_count": len(graph["inferred_edges"]),
                        "missing_producer_count": len(graph["missing_producers"]),
                        "ambiguous_dependency_count": len(graph["ambiguous_dependencies"]),
                        "cycle_count": len(graph["cycles"]),
                    },
                    "missing_producers": graph["missing_producers"],
                    "ambiguous_dependencies": graph["ambiguous_dependencies"],
                    "cycles": graph["cycles"],
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
