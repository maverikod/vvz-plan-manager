"""Extended AI/documentation metadata for the concept_list command."""

from typing import Any, Dict

from plan_manager.commands.runtime_filtering import pagination_metadata_params

def get_concept_list_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptListCommand.

    Args:
        cls: The ConceptListCommand class (passed by its classmethod metadata()).

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
            "Returns one page of the MRS concept (C-003) list of a resolved plan, "
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
                "description": "A page of the concept list of the plan, plus total/limit/offset.",
                "data": {
                    "concepts": "List of concept objects, each with concept_id, name, definition, properties, source_labels.",
                    "total": "Count of the full concept set before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "concepts": [
                        {
                            "concept_id": "C-003",
                            "name": "Concept",
                            "definition": "MRS basis axis with canonical name, one-sentence definition, properties, and source labels.",
                            "properties": ["identifier pattern C-NNN, unique within plan"],
                            "source_labels": ["{f6s2}", "{k7r9}"],
                        },
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
                "description": "List every concept of a plan.",
                "command": {"plan": "plan-manager"},
                "explanation": "Returns the first page (default limit 50) of stored concepts of the resolved plan.",
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
            "Use concept_list before concept_get or concept_coverage to discover valid concept_id values.",
            "concept_list never mutates plan state; safe to call at any plan or cascade status.",
            "Compare offset+limit against total to detect additional pages.",
        ],
    }
