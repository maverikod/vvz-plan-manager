"""Graph command: paginated page of the transitive dependency-edge closure of one step (A-005)."""
from __future__ import annotations

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.graph_dependents_metadata import (
    get_graph_dependents_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import build_edges, load_steps
from plan_manager.views.dependents_closure import (
    DEFAULT_DEPTH_LIMIT,
    MAX_DEPTH_LIMIT,
    transitive_closure,
)


class GraphDependentsCommand(Command):
    """Return a paginated page of the transitive dependency-edge closure of one step."""

    name = "graph_dependents"
    version = "1.0.0"
    descr = "Return a paginated page of the transitive dependency-edge closure of one step."
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
                    "description": "Origin step, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                },
                "direction": {
                    "type": "string",
                    "description": "Direction of dependency traversal: dependents or dependencies.",
                    "enum": ["dependents", "dependencies"],
                },
                "depth_limit": {
                    "type": "integer",
                    "description": "Maximum depth of transitive closure traversal.",
                    "minimum": 1,
                    "maximum": MAX_DEPTH_LIMIT,
                    "default": DEFAULT_DEPTH_LIMIT,
                },
                **pagination_schema_properties(),
            },
            "required": ["plan", "step_id", "direction"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_graph_dependents_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            step_id = kwargs["step_id"]
            direction = kwargs["direction"]
            depth_limit = kwargs.get("depth_limit", DEFAULT_DEPTH_LIMIT)
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                pagination = parse_pagination(
                    {"limit": kwargs.get("limit"), "offset": kwargs.get("offset")}
                )
                nodes = load_steps(conn, plan_obj.uuid)
                edges = build_edges(nodes)
                origin = resolve_step_ref(nodes, step_id)
                closure = transitive_closure(
                    nodes, edges, origin.uuid, direction, depth_limit
                )
                total = len(closure)
                page = closure[pagination.offset : pagination.offset + pagination.limit]
                data = {
                    "step": artifact_path_of(nodes, origin),
                    "direction": direction,
                    "depth_limit": depth_limit,
                    "steps": [artifact_path_of(nodes, nodes[u]) for u in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
