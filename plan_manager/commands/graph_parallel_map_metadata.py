"""Metadata for the graph_parallel_map command (C-009, C-023, EIG block C)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params
from plan_manager.views.parallel_map_ext import MODE_EXPLICIT, MODE_VALUES

def get_graph_parallel_map_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves the plan against the catalog, loads the dependency "
            "projection (C-009) for the plan once, and partitions its "
            "steps into parallel waves by prerequisite depth: every step "
            "in a wave has all its prerequisites satisfied by steps in "
            "strictly earlier waves. Returns one paginated page of the "
            "top-level waves list (uniform offset/limit convention, "
            "default limit 50, max 200); pagination is applied to whole "
            "waves, never to the steps inside one wave. Each step is "
            "classified by its artifact path. The command is read-only and "
            "mutates nothing."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            **pagination_metadata_params(),
            "mode": {
                "description": (
                    "Wave computation mode. 'explicit' (default) computes waves over only the "
                    "declared/derived dependency edges (C-009 build_edges); the payload is "
                    "byte-identical to this command's payload before 'mode' existed -- "
                    "waves/total/limit/offset only. 'extended' computes waves over the COMBINED "
                    "edge set the execution_graph command exposes (explicit + file_order + "
                    "object_producer + verification_target) and additionally returns "
                    "placement_reasons, critical_path, wave_parallelism, and conflict_groups. "
                    "One of: " + ", ".join(MODE_VALUES) + "."
                ),
                "type": "string",
                "required": False,
                "enum": list(MODE_VALUES),
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "A page of the wave partition of the plan's steps by prerequisite depth, "
                    "plus total/limit/offset; mode='extended' additionally returns "
                    "placement_reasons, critical_path, wave_parallelism, and conflict_groups."
                ),
                "data": {
                    "waves": "List of waves in the requested page; each wave is a list of artifact paths that may run in parallel.",
                    "total": "Count of the full wave list before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                    "placement_reasons": (
                        "mode='extended' only. Dict from every step's artifact path to the "
                        "list of {from, type} incoming edges (over the combined edge set) "
                        "that pin it to its wave; empty for wave-0 steps."
                    ),
                    "critical_path": (
                        "mode='extended' only. One longest dependency chain over the combined "
                        "edge set, as an ordered list of artifact paths."
                    ),
                    "wave_parallelism": (
                        "mode='extended' only. List of wave sizes, one entry per wave in the "
                        "full (unpaginated) extended wave list."
                    ),
                    "conflict_groups": (
                        "mode='extended' only. Generalized conflict groups: "
                        "{type: 'same_file_writers', key: target_file, members} for target "
                        "files with 2+ level-5 writers, and {type: 'same_object_producers', "
                        "key: object, members} for block-B's ambiguous_dependencies."
                    ),
                },
                "example": {
                    "waves": [
                        ["G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml"],
                        ["G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml"],
                    ],
                    "total": 2,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Domain error returned when the plan cannot be resolved, the graph contains a cycle, mode is invalid, or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | CYCLE_DETECTED | INVALID_EXECUTION_MODE | INVALID_PAGINATION",
                "message": "Human-readable message identifying the missing plan, cycle, mode, or pagination error.",
                "details": "None for PLAN_NOT_FOUND; cycle diagnostics for CYCLE_DETECTED when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the first page of the parallel wave map of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of waves that may be executed in parallel.",
            },
            {
                "description": "Get the extended wave map with placement diagnostics.",
                "command": {"plan": "plan_manager", "mode": "extended"},
                "explanation": (
                    "Returns waves computed over the combined explicit+file_order+"
                    "object_producer+verification_target edge set, plus placement_reasons, "
                    "critical_path, wave_parallelism, and conflict_groups."
                ),
            },
        ],
        "error_cases": {
        "AS_SAME_FILE_ORDER_AMBIGUOUS": {
            "description": "Two atomic writers target the same file but no dependency path establishes their execution order.",
            "message": "ambiguous same-file writer order: {details}",
            "solution": "Add an explicit dependency between the affected TS/GS branches, then retry.",
        },
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "CYCLE_DETECTED": {
                "description": "The dependency graph (explicit-only, or combined when mode='extended') contains a cycle and cannot be partitioned into parallel waves.",
                "message": "cycle detected: {details}",
                "solution": "Inspect graph_order, graph_deps, or execution_graph output, break the cycle, and retry graph_parallel_map.",
            },
            "INVALID_EXECUTION_MODE": {
                "description": "The supplied mode value is not one of the two recognized values.",
                "message": "mode must be one of ['explicit', 'extended'], got {mode}",
                "solution": "Supply one of 'explicit' or 'extended', or omit mode for the default 'explicit'.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use graph_order instead when a single linear execution sequence is needed.",
            "Waves reflect prerequisite depth only; steps within one wave carry no further ordering guarantee.",
            "Compare offset+limit against total to detect additional pages of waves.",
            "Use mode='extended' to see the same combined edge set execution_graph reports (object-role and verification inference), plus placement_reasons/critical_path/wave_parallelism/conflict_groups diagnostics; mode='explicit' (default) stays byte-compatible with callers written before mode existed.",
        ],
    }
