"""Metadata for step_runtime_get."""

from __future__ import annotations


def get_step_runtime_get_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the runtime parameters stored for one plan step. "
            "Runtime data is separate from the plan definition: reading it "
            "does not inspect cascades, revisions, gates, or scores. Steps "
            "without reported runtime data return an empty record containing "
            "all four field groups: activations, execution_attempts, "
            "journal_aggregates, and authoring."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step identifier to resolve within the plan.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "Runtime record for the resolved step.",
                "data": {
                    "step_id": "Resolved step identifier.",
                    "runtime": "RuntimeRecord with activations, execution_attempts, journal_aggregates, authoring.",
                },
                "example": {
                    "step_id": "A-001",
                    "runtime": {
                        "activations": [],
                        "execution_attempts": [],
                        "journal_aggregates": None,
                        "authoring": None,
                    },
                },
            },
            "error": {
                "description": "Plan or step could not be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND",
                "message": "Human-readable error message.",
                "details": "Domain error details when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Read runtime data for one step.",
                "command": {"plan": "plan_manager", "step_id": "A-001"},
                "explanation": "Returns an empty runtime record when no runtime data has been reported.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan.",
            },
            "STEP_NOT_FOUND": {
                "description": "The step_id does not resolve in the plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree to discover valid step ids.",
            },
        },
        "best_practices": [
            "Use step_runtime_list when a dashboard needs runtime data for many steps.",
            "Treat runtime data as operational history, not as gate or scoring input.",
        ],
    }
