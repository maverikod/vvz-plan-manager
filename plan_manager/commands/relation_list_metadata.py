"""Extended AI/documentation metadata for the relation_list command."""

from typing import Any, Dict

from plan_manager.commands.runtime_filtering import pagination_metadata_params

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
            "Returns one page of the MRS relation (C-004) list of a resolved plan, "
            "paginated with the uniform offset/limit convention (default limit 50, "
            "max 200). Read-only: never mutates plan state."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to resolve.",
                "type": "string",
                "required": True,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of the relation list of the plan, plus total/limit/offset.",
                "data": {
                    "relations": "List of relation objects, each with from_concept, to_concept, type.",
                    "total": "Count of the full relation set before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "relations": [
                        {"from_concept": "C-004", "to_concept": "C-003", "type": "depends_on"},
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Error result with a stable domain code.",
                "code": "stable error code string (PLAN_NOT_FOUND or INVALID_PAGINATION)",
                "message": "human-readable message",
                "details": "additional diagnostic fields when available",
            },
        },
        "usage_examples": [
            {
                "description": "List every relation of a plan.",
                "command": {"plan": "plan-manager"},
                "explanation": "Returns the first page (default limit 50) of stored relations of the resolved plan.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "List plans and retry with a valid plan identifier or UUID.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use relation_list to discover existing edges before calling relation_add or relation_remove.",
            "relation_list never mutates plan state; safe to call at any plan or cascade status.",
            "Compare offset+limit against total to detect additional pages.",
        ],
    }
