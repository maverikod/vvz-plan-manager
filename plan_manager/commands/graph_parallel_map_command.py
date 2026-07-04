"""Graph command: parallel wave partition of a plan's steps (C-009)."""
from __future__ import annotations

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.graph_parallel_map_metadata import (
    get_graph_parallel_map_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import build_edges, load_steps, waves


class GraphParallelMapCommand(Command):
    """Return the parallel wave partition of a plan's steps by prerequisite depth."""

    name = "graph_parallel_map"
    version = "1.0.0"
    descr = "Return the parallel wave partition of a plan's steps by prerequisite depth."
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
        return get_graph_parallel_map_metadata(cls)

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
                try:
                    w = waves(nodes, edges)
                except ValueError as exc:
                    return domain_error("CYCLE_DETECTED", str(exc))
                data = {
                    "waves": [
                        [artifact_path_of(nodes, nodes[u]) for u in wave]
                        for wave in w
                    ]
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
