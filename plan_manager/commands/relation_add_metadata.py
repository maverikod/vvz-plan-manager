"""Extended AI/documentation metadata for the relation_add command."""

from typing import Any, Dict


def get_relation_add_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for RelationAddCommand.

    Args:
        cls: The RelationAddCommand class (passed by its classmethod metadata()).

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
            "Adds a new MRS relation (C-004) between two existing concepts. "
            "MRS entities are cascade-only (C-016) at any plan status: the "
            "call must carry the UUID of an already-open cascade in "
            "cascade_uuid, or it is rejected with CASCADE_CONFLICT. The "
            "write enforces the seven allowed relation types and the "
            "existence of both endpoint concepts, so a mechanically invalid "
            "MRS entry cannot be written; the store has no duplicate-"
            "relation rule, so re-adding an existing edge succeeds again "
            "rather than erroring. The mutation is recorded as a "
            "cascade revision with the full node snapshot and verified by "
            "re-reading the relation list after write; this command does "
            "not support dry_run, matching the cascade-only write "
            "discipline of C-016."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to resolve.",
                "type": "string",
                "required": True,
            },
            "cascade_uuid": {
                "description": "UUID of the open cascade admitting this mutation.",
                "type": "string",
                "required": True,
            },
            "from_concept": {
                "description": "Concept identifier of the relation source endpoint.",
                "type": "string",
                "required": True,
            },
            "to_concept": {
                "description": "Concept identifier of the relation target endpoint.",
                "type": "string",
                "required": True,
            },
            "type": {
                "description": "Relation type; one of the seven allowed types.",
                "type": "string",
                "required": True,
                "enum": ["uses", "owns", "implements", "extends", "depends_on", "produces", "consumes"],
            },
        },
        "return_value": {
            "success": {
                "description": "The written relation verified by re-read, with its cascade revision.",
                "data": {
                    "from_concept": "Relation source endpoint concept_id.",
                    "to_concept": "Relation target endpoint concept_id.",
                    "type": "Relation type.",
                    "revision_uuid": "UUID of the cascade revision that recorded this write.",
                },
                "example": {
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "type": "depends_on",
                    "revision_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
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
                "description": "Add a new relation under an open cascade.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "type": "depends_on",
                },
                "explanation": "Writes a new relation row under the given open cascade and returns it verified by re-read.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "List plans and retry with a valid plan identifier or UUID.",
            },
            "CASCADE_CONFLICT": {
                "description": "cascade_uuid does not identify the plan's currently open cascade.",
                "message": "cascade admission rejected: {details}",
                "solution": "Begin a cascade and pass its cascade_uuid, or use the plan's currently open cascade.",
            },
            "CONCEPT_NOT_FOUND": {
                "description": "from_concept or to_concept does not exist in the plan.",
                "message": "concept not found: {concept_id}",
                "solution": "Call concept_list and retry with valid concept_id values for both endpoints.",
            },
            "IMPORT_INVALID": {
                "description": "The relation payload is structurally invalid and cannot be written.",
                "message": "invalid relation payload: {details}",
                "solution": "Use valid endpoint concept identifiers and one of the allowed relation types.",
            },
        },
        "best_practices": [
            "Begin a cascade before calling relation_add; MRS entities are cascade-only at any plan status.",
            "Verify both endpoints exist via concept_get or concept_list before writing the relation.",
            "Call relation_list before relation_add to avoid writing a duplicate edge; the store has no duplicate-relation rule and will not reject one.",
            "Re-read with relation_list after the cascade commits to confirm the final state.",
        ],
    }
