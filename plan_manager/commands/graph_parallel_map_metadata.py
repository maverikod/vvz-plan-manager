"""Metadata for the graph_parallel_map command (C-009, C-023)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params

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
        },
        "return_value": {
            "success": {
                "description": "A page of the wave partition of the plan's steps by prerequisite depth, plus total/limit/offset.",
                "data": {
                    "waves": "List of waves in the requested page; each wave is a list of artifact paths that may run in parallel.",
                    "total": "Count of the full wave list before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
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
                "description": "Domain error returned when the plan cannot be resolved, the graph contains a cycle, or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | CYCLE_DETECTED | INVALID_PAGINATION",
                "message": "Human-readable message identifying the missing plan, cycle, or pagination error.",
                "details": "None for PLAN_NOT_FOUND; cycle diagnostics for CYCLE_DETECTED when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the first page of the parallel wave map of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of waves that may be executed in parallel.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "CYCLE_DETECTED": {
                "description": "The dependency graph contains a cycle and cannot be partitioned into parallel waves.",
                "message": "cycle detected: {details}",
                "solution": "Inspect graph_order or graph_deps output, break the cycle, and retry graph_parallel_map.",
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
        ],
    }
