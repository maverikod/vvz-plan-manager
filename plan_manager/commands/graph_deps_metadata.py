"""Metadata for the graph_deps command (C-009, C-023)."""
from __future__ import annotations


def get_graph_deps_metadata(cls) -> dict:
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
            "identified by step_id, and returns its dependency neighborhood: "
            "the steps it depends on and the steps that depend on it. Each "
            "step in the result is classified by its artifact path. The "
            "command is read-only and mutates nothing."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Target step, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The dependency neighborhood of the target step.",
                "data": {
                    "step": "Artifact path of the target step.",
                    "depends_on": "Artifact paths of steps the target step depends on.",
                    "dependents": "Artifact paths of steps that depend on the target step.",
                },
                "example": {
                    "step": "G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-003-status.yaml",
                    "depends_on": ["G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml"],
                    "dependents": [],
                },
            },
            "error": {
                "description": "Domain error returned when the plan or the step cannot be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND | AMBIGUOUS_STEP_ID",
                "message": "Human-readable message identifying the missing, or ambiguous, plan or step.",
                "details": "matches (sorted candidate canonical paths) for AMBIGUOUS_STEP_ID; none otherwise.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the dependency neighborhood of one step.",
                "command": {"plan": "plan_manager", "step_id": "T-007"},
                "explanation": "Returns the steps T-007 depends on and the steps depending on T-007.",
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
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID.",
            },
        },
        "best_practices": [
            "Resolve the plan tree first if the exact step_id is not already known.",
            "Treat depends_on and dependents as read-only classification, not as an edit surface.",
        ],
    }
