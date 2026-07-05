"""Extended AI/documentation metadata for the step_tree command."""

from typing import Any


def get_step_tree_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepTreeCommand.

    Args:
        cls: The StepTreeCommand class object, used to source identity
            attributes (name, version, category, author, email) so the
            metadata dictionary never drifts from the class definition.

    Returns:
        A dictionary with the required metadata fields: name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases,
        best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the full step tree of a plan: every level 3, 4, and 5 "
            "step as a flat list of {path, step_id, slug, level, status} "
            "entries, sorted by (level, path). This is a read-only command: "
            "it never mutates the plan and performs no admission or cascade "
            "checks."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "include_runtime": {
                "description": "Optional flag; when true, include each step's runtime parameters.",
                "type": "boolean",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The plan's full step tree as a flat, sorted list.",
                "data": {
                    "tree": "List of {path, step_id, slug, level, status} entries, sorted by (level, path). Entries include runtime when include_runtime is true.",
                },
                "example": {
                    "tree": [
                        {
                            "path": "docs/plans/example/G-005-api-surface/README.yaml",
                            "step_id": "G-005",
                            "slug": "api-surface",
                            "level": 3,
                            "status": "draft",
                        },
                        {
                            "path": "docs/plans/example/G-005-api-surface/T-006-step-commands/README.yaml",
                            "step_id": "T-006",
                            "slug": "step-commands",
                            "level": 4,
                            "status": "draft",
                        },
                    ],
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "Stable domain error code (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "List the full step tree of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns every step of the plan as a flat, sorted list with statuses.",
            },
            {
                "description": "List the step tree with runtime parameters.",
                "command": {"plan": "plan_manager", "include_runtime": True},
                "explanation": "Includes runtime only when explicitly requested.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
        },
        "best_practices": [
            "Use step_tree to discover valid step_id values before calling step_get, step_update, step_move, step_delete, or step_set_status.",
            "This command never mutates state; it is safe to call at any time and any status.",
            "Leave include_runtime false for ordinary topology reads and use it only when operational runtime data is needed.",
        ],
    }
