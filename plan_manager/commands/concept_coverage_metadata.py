"""Extended AI/documentation metadata for the concept_coverage command."""

from typing import Any, Dict


def get_concept_coverage_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptCoverageCommand.

    Args:
        cls: The ConceptCoverageCommand class (passed by its classmethod
            metadata()).

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
            "Answers the reverse coverage query (C-010) for one concept "
            "(C-003): which plan steps reference it, classified by artifact "
            "path, and which HRS paragraph labels justify it. Read-only: "
            "never mutates plan state. The coverage is computed on demand "
            "from the current tree state; nothing is stored as a matrix."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to resolve.",
                "type": "string",
                "required": True,
            },
            "concept_id": {
                "description": "Concept identifier to compute reverse coverage for.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The reverse coverage answer for concept_id.",
                "data": {
                    "concept_id": "The queried concept identifier.",
                    "steps": "Sorted list of artifact paths of every step that references concept_id.",
                    "paragraphs": "List of HRS paragraph labels justifying the concept.",
                },
                "example": {
                    "concept_id": "C-003",
                    "steps": ["G-001-domain-model.T-001-concept-model"],
                    "paragraphs": ["{f6s2}", "{k7r9}"],
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
                "description": "Find which steps and paragraphs justify a concept.",
                "command": {"plan": "plan-manager", "concept_id": "C-003"},
                "explanation": "Returns the artifact paths of every step referencing C-003 and the paragraph labels justifying it.",
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
            "Use concept_list to discover valid concept_id values before calling concept_coverage.",
            "concept_coverage never mutates plan state; safe to call at any plan or cascade status.",
            "An empty steps list with a non-empty paragraphs list means the concept is justified by the HRS but not yet referenced by any step.",
        ],
    }
