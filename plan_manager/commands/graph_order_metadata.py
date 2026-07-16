"""Metadata for the graph_order command (C-009, C-023, C-026)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params

def get_graph_order_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves the plan against the catalog, loads the dependency "
            "projection (C-009) for the plan once, and computes one "
            "paginated page of the topological execution order with the "
            "deterministic Kahn tie-break (uniform offset/limit convention, "
            "default limit 50, max 200). Each step in the order is "
            "classified by its artifact path. When the graph contains a "
            "cycle, ordering is impossible and the command returns the "
            "cycle-detected error listing the residual cycle members by "
            "artifact path instead of an order, before any pagination is "
            "applied. The command is read-only and mutates nothing."
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
                "description": "A page of the topological execution order of the plan's steps, plus total/limit/offset.",
                "data": {
                    "order": "Artifact paths of the requested page of steps, in execution order.",
                    "total": "Count of the full execution order before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "order": [
                        "G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml",
                        "G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml",
                    ],
                    "total": 2,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Domain error returned when the plan cannot be resolved, the graph has a cycle, or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | CYCLE_DETECTED | INVALID_PAGINATION",
                "message": "Human-readable message identifying the missing plan, the cycle, or the pagination error.",
                "details": "For CYCLE_DETECTED: {\"cycle\": [artifact paths of the residual cycle members]}.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the first page of the execution order of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of steps' artifact paths in deterministic topological order.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "CYCLE_DETECTED": {
                "description": "The dependency graph contains a cycle, so no total order exists.",
                "message": "dependency graph has a cycle",
                "solution": "Inspect the listed cycle members and remove or reorder the offending depends_on edges.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Treat CYCLE_DETECTED as a hard blocker: no partial order is returned when a cycle exists.",
            "Re-run after editing depends_on edges to confirm the cycle is resolved.",
            "Compare offset+limit against total to detect additional pages.",
        ],
    }
