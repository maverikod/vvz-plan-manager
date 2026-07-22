"""Graph command: dependency neighborhood of one step (C-009)."""
from __future__ import annotations

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.graph_deps_metadata import get_graph_deps_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import (
    build_edges,
    dependents_of,
    load_steps,
    prerequisites_of,
)


class GraphDepsCommand(Command):
    """Return the dependency neighborhood (depends_on and dependents) of one step."""

    name = "graph_deps"
    version = "1.0.0"
    descr = "Return the dependency neighborhood (depends_on and dependents) of one step."
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
                "step_id": {
                    "type": "string",
                    "description": "Target step, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                },
            },
            "required": ["plan", "step_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_graph_deps_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            step_id = kwargs["step_id"]
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                nodes = load_steps(conn, plan_obj.uuid)
                target = resolve_step_ref(nodes, step_id)
                edges = build_edges(nodes)
                data = {
                    "step": artifact_path_of(nodes, target),
                    "depends_on": [
                        artifact_path_of(nodes, nodes[u])
                        for u in prerequisites_of(nodes, edges, target.uuid)
                    ],
                    "dependents": [
                        artifact_path_of(nodes, nodes[u])
                        for u in dependents_of(nodes, edges, target.uuid)
                    ],
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
