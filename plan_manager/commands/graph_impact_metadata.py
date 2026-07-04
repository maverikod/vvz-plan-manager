"""Metadata for the graph_impact command (C-009, C-023)."""
from __future__ import annotations


def get_graph_impact_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves the plan against the catalog, loads the dependency "
            "projection (C-009) for the plan once, locates the step "
            "identified by step_id, and returns its transitive impact set: "
            "every step that transitively depends on the target step, per "
            "the invalidation rule. Each step is classified by its "
            "artifact path. This is a read-only invalidation projection: "
            "the command does not change the status of any step."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "step_id of the target step within the plan.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The transitive impact set of the target step.",
                "data": {
                    "step": "Artifact path of the target step.",
                    "impact": "Artifact paths of every step transitively depending on the target step.",
                },
                "example": {
                    "step": "G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml",
                    "impact": [
                        "G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml"
                    ],
                },
            },
            "error": {
                "description": "Domain error returned when the plan or the step cannot be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND",
                "message": "Human-readable message identifying the missing plan or step.",
                "details": "None for these error codes.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the transitive impact set of one step.",
                "command": {"plan": "plan_manager", "step_id": "T-001"},
                "explanation": "Returns every step's artifact path that transitively depends on T-001.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "No step with the given step_id exists in the resolved plan.",
                "message": "step not found: {step_id}",
                "solution": "Inspect the plan tree to find a valid step_id and retry.",
            },
        },
        "best_practices": [
            "Use the impact set to decide which downstream steps need re-review before a change is made.",
            "This command never changes status; combine with the step status command to act on the result.",
        ],
    }
