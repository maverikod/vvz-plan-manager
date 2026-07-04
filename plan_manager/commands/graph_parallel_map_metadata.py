"""Metadata for the graph_parallel_map command (C-009, C-023)."""
from __future__ import annotations


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
            "strictly earlier waves. Each step is classified by its "
            "artifact path. The command is read-only and mutates nothing."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The wave partition of the plan's steps by prerequisite depth.",
                "data": {
                    "waves": "List of waves; each wave is a list of artifact paths that may run in parallel.",
                },
                "example": {
                    "waves": [
                        ["G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml"],
                        ["G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml"],
                    ]
                },
            },
            "error": {
                "description": "Domain error returned when the plan cannot be resolved or the graph contains a cycle.",
                "code": "PLAN_NOT_FOUND | CYCLE_DETECTED",
                "message": "Human-readable message identifying the missing plan or cycle.",
                "details": "None for PLAN_NOT_FOUND; cycle diagnostics for CYCLE_DETECTED when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the parallel wave map of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the steps grouped into waves that may be executed in parallel.",
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
        },
        "best_practices": [
            "Use graph_order instead when a single linear execution sequence is needed.",
            "Waves reflect prerequisite depth only; steps within one wave carry no further ordering guarantee.",
        ],
    }
