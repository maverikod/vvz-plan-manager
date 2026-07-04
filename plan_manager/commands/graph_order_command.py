"""Graph command: topological execution order of a plan's steps (C-009)."""
from __future__ import annotations

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.graph_order_metadata import get_graph_order_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import (
    build_edges,
    load_steps,
    topological_order,
)


class GraphOrderCommand(Command):
    """Return the topological execution order of a plan's steps."""

    name = "graph_order"
    version = "1.0.0"
    descr = "Return the topological execution order of a plan's steps."
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
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_graph_order_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                nodes = load_steps(conn, plan_obj.uuid)
                edges = build_edges(nodes)
                order, residual = topological_order(nodes, edges)
                if residual:
                    return domain_error(
                        "CYCLE_DETECTED",
                        "dependency graph has a cycle",
                        {
                            "cycle": [
                                artifact_path_of(nodes, nodes[u]) for u in residual
                            ]
                        },
                    )
                data = {
                    "order": [artifact_path_of(nodes, nodes[u]) for u in order]
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
