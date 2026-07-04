"""Extended AI/documentation metadata for the concept_get command."""

from typing import Any, Dict


def get_concept_get_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptGetCommand.

    Args:
        cls: The ConceptGetCommand class (passed by its classmethod metadata()).

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
            "Returns one MRS concept (C-003) of a resolved plan by its "
            "concept_id. Read-only: never mutates plan state."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to resolve.",
                "type": "string",
                "required": True,
            },
            "concept_id": {
                "description": "Concept identifier in pattern C-NNN.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The concept fields.",
                "data": {
                    "concept_id": "Concept identifier, pattern C-NNN.",
                    "name": "Concept canonical name.",
                    "definition": "Concept one-sentence definition.",
                    "properties": "List of free-form property statements.",
                    "source_labels": "List of HRS paragraph labels justifying the concept.",
                },
                "example": {
                    "concept_id": "C-003",
                    "name": "Concept",
                    "definition": "MRS basis axis with canonical name, one-sentence definition, properties, and source labels.",
                    "properties": ["identifier pattern C-NNN, unique within plan"],
                    "source_labels": ["{f6s2}", "{k7r9}"],
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
                "description": "Fetch one concept by id.",
                "command": {"plan": "plan-manager", "concept_id": "C-003"},
                "explanation": "Returns the stored fields of concept C-003.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "List plans and retry with a valid plan identifier or UUID.",
            },
            "CONCEPT_NOT_FOUND": {
                "description": "No concept with concept_id exists in the plan MRS.",
                "message": "concept not found: {concept_id}",
                "solution": "Call concept_list and retry with a valid concept_id.",
            },
        },
        "best_practices": [
            "Use concept_list to discover valid concept_id values before calling concept_get.",
            "concept_get never mutates plan state; safe to call at any plan or cascade status.",
        ],
    }
