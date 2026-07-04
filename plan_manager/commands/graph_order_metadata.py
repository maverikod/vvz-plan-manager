"""Metadata for the graph_order command (C-009, C-023, C-026)."""
from __future__ import annotations


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
            "projection (C-009) for the plan once, and computes the "
            "topological execution order with the deterministic Kahn "
            "tie-break. Each step in the order is classified by its "
            "artifact path. When the graph contains a cycle, ordering is "
            "impossible and the command returns the cycle-detected error "
            "listing the residual cycle members by artifact path instead "
            "of an order. The command is read-only and mutates nothing."
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
                "description": "The full topological execution order of the plan's steps.",
                "data": {
                    "order": "Artifact paths of every step, in execution order.",
                },
                "example": {
                    "order": [
                        "G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml",
                        "G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml",
                    ]
                },
            },
            "error": {
                "description": "Domain error returned when the plan cannot be resolved or the graph has a cycle.",
                "code": "PLAN_NOT_FOUND | CYCLE_DETECTED",
                "message": "Human-readable message identifying the missing plan or the cycle.",
                "details": "For CYCLE_DETECTED: {\"cycle\": [artifact paths of the residual cycle members]}.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the full execution order of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns every step's artifact path in deterministic topological order.",
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
        },
        "best_practices": [
            "Treat CYCLE_DETECTED as a hard blocker: no partial order is returned when a cycle exists.",
            "Re-run after editing depends_on edges to confirm the cycle is resolved.",
        ],
    }
