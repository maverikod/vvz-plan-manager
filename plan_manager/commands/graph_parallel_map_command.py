"""Graph command: paginated page of the parallel wave partition of a plan's steps (C-009, EIG block C)."""
from __future__ import annotations

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.graph_parallel_map_metadata import (
    get_graph_parallel_map_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    Pagination,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import build_edges, load_steps, waves
from plan_manager.views.parallel_map_ext import (
    MODE_EXPLICIT,
    MODE_EXTENDED,
    MODE_VALUES,
    build_conflict_groups,
    build_critical_path,
    build_placement_reasons,
    extended_edges,
)


def _paginate_waves(
    full_waves: list[list[str]], pagination: Pagination
) -> tuple[list[list[str]], int]:
    """Slice whole waves per the uniform offset/limit convention; return (page, total)."""
    total = len(full_waves)
    page = full_waves[pagination.offset : pagination.offset + pagination.limit]
    return page, total


class GraphParallelMapCommand(Command):
    """Return a paginated page of the parallel wave partition of a plan's steps by prerequisite depth."""

    name = "graph_parallel_map"
    version = "1.0.0"
    descr = "Return a paginated page of the parallel wave partition of a plan's steps by prerequisite depth."
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
                "mode": {
                    "type": "string",
                    "enum": list(MODE_VALUES),
                    "default": MODE_EXPLICIT,
                    "description": (
                        "Wave computation mode. 'explicit' (default) computes waves over "
                        "only the declared/derived dependency edges (C-009 build_edges: "
                        "depends_on plus same-file priority order); the payload is "
                        "byte-identical to this command's payload before 'mode' existed "
                        "-- waves/total/limit/offset only. 'extended' computes waves over "
                        "the COMBINED edge set block B's execution_graph command exposes "
                        "(explicit + file_order + object_producer + verification_target) "
                        "and additionally returns placement_reasons, critical_path, "
                        "wave_parallelism, and conflict_groups alongside the same "
                        "paginated waves/total/limit/offset. One of: "
                        + ", ".join(MODE_VALUES) + "."
                    ),
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
            raw_mode = kwargs.get("mode")
            if raw_mode is None:
                mode = MODE_EXPLICIT
            elif raw_mode in MODE_VALUES:
                mode = raw_mode
            else:
                raise DomainCommandError(
                    "INVALID_EXECUTION_MODE",
                    f"mode must be one of {list(MODE_VALUES)}, got {raw_mode!r}",
                )
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": kwargs.get("limit"), "offset": kwargs.get("offset")})
                nodes = load_steps(conn, plan_obj.uuid)
                if mode == MODE_EXTENDED:
                    uuid_edges, edge_dicts, graph = extended_edges(nodes)
                    try:
                        w = waves(nodes, uuid_edges)
                    except ValueError as exc:
                        return domain_error("CYCLE_DETECTED", str(exc))
                    full_waves = [
                        [artifact_path_of(nodes, nodes[u]) for u in wave]
                        for wave in w
                    ]
                    page, total = _paginate_waves(full_waves, pagination)
                    data = {
                        "waves": page,
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                        "placement_reasons": build_placement_reasons(nodes, edge_dicts),
                        "critical_path": build_critical_path(nodes, uuid_edges),
                        "wave_parallelism": [len(wave) for wave in full_waves],
                        "conflict_groups": build_conflict_groups(nodes, graph),
                    }
                else:
                    edges = build_edges(nodes)
                    try:
                        w = waves(nodes, edges)
                    except ValueError as exc:
                        return domain_error("CYCLE_DETECTED", str(exc))
                    full_waves = [
                        [artifact_path_of(nodes, nodes[u]) for u in wave]
                        for wave in w
                    ]
                    page, total = _paginate_waves(full_waves, pagination)
                    data = {
                        "waves": page,
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                    }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
