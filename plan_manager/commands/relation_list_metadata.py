"""Extended AI/documentation metadata for the relation_list command."""

from typing import Any, Dict


def get_relation_list_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for RelationListCommand.

    Args:
        cls: The RelationListCommand class (passed by its classmethod metadata()).

    Returns:
        A metadata dictionary with keys name, version, description, category,
        author, email, detailed_description, parameters, return_value,
        usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the full MRS relation (C-004) list of a resolved plan. "
            "Read-only: never mutates plan state."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to resolve.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The relation list of the plan.",
                "data": {
                    "relations": "List of relation objects, each with from_concept, to_concept, type.",
                },
                "example": {
                    "relations": [
                        {"from_concept": "C-004", "to_concept": "C-003", "type": "depends_on"},
                    ],
                },
            },
            "error": {
                "description": "Error result with a stable domain code.",
                "code": "stable error code string",
                "message": "human-readable message",
                "details": "additional diagnostic fields when available",
            },
        },
        "usage_examples": [
            {
                "description": "List every relation of a plan.",
                "command": {"plan": "plan-manager"},
                "explanation": "Returns all stored relations of the resolved plan.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "List plans and retry with a valid plan identifier or UUID.",
            },
        },
        "best_practices": [
            "Use relation_list to discover existing edges before calling relation_add or relation_remove.",
            "relation_list never mutates plan state; safe to call at any plan or cascade status.",
        ],
    }
