"""Metadata for step_runtime_list."""

from __future__ import annotations


def get_step_runtime_list_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Lists runtime records for every step in a whole plan, one "
            "G-NNN scope, or one G-NNN/T-NNN scope. The command returns an "
            "entry for every step in scope, including steps that have no "
            "runtime row yet; those receive an empty runtime record."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "Runtime records keyed by step artifact path.",
                "data": {
                    "runtime": "Map from artifact path to {step_id, runtime}.",
                },
                "example": {
                    "runtime": {
                        "G-001/T-001/A-001": {
                            "step_id": "A-001",
                            "runtime": {
                                "activations": [],
                                "execution_attempts": [],
                                "journal_aggregates": None,
                                "authoring": None,
                            },
                        }
                    }
                },
            },
            "error": {
                "description": "Plan or scope could not be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND",
                "message": "Human-readable error message.",
                "details": "Domain error details when available.",
            },
        },
        "usage_examples": [
            {
                "description": "List runtime records for one tactical branch.",
                "command": {"plan": "plan_manager", "scope": "G-001/T-001"},
                "explanation": "Returns the tactical step and its atomic children.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan.",
            },
            "STEP_NOT_FOUND": {
                "description": "The scope is invalid or missing.",
                "message": "scope not found: {scope}",
                "solution": "Call step_tree to discover valid scope identifiers.",
            },
        },
        "best_practices": [
            "Use scope for dashboards focused on one branch.",
            "Do not treat absence of runtime rows as absence of steps; empty records are intentional.",
        ],
    }
