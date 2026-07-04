"""Extended AI/documentation metadata for the concept_remove command."""

from typing import Any, Dict


def get_concept_remove_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptRemoveCommand.

    Args:
        cls: The ConceptRemoveCommand class (passed by its classmethod metadata()).

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
            "Removes an existing MRS concept (C-003) from a resolved plan. "
            "MRS entities are cascade-only (C-016) at any plan status: the "
            "call must carry the UUID of an already-open cascade in "
            "cascade_uuid, or it is rejected with CASCADE_CONFLICT. The "
            "removal is destructive: it is recorded as a cascade revision "
            "with a tombstone node snapshot (the pre-removal fields plus "
            "\"deleted\": true) and verified by re-reading the concept after "
            "write to confirm it no longer resolves. This command does not "
            "support dry_run; the reviewable, revertible unit is the open "
            "cascade itself (C-016), which can be aborted before commit."
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
            "concept_id": {
                "description": "Concept identifier of the concept to remove.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The removed concept identifier, confirmed by re-read, with its cascade revision.",
                "data": {
                    "concept_id": "Concept identifier that was removed.",
                    "deleted": "Always true on success.",
                    "revision_uuid": "UUID of the cascade revision that recorded this removal.",
                },
                "example": {
                    "concept_id": "C-037",
                    "deleted": True,
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
                "description": "Remove an existing concept under an open cascade.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "concept_id": "C-037",
                },
                "explanation": "Removes concept C-037 under the given open cascade and confirms it no longer resolves.",
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
                "description": "concept_id does not exist in the plan.",
                "message": "concept not found: {concept_id}",
                "solution": "Call concept_list and retry with a valid concept_id.",
            },
        },
        "best_practices": [
            "Confirm no relation still references concept_id before removal, or expect relation_list to still show stale references until cleaned up.",
            "Begin a cascade before calling concept_remove; MRS entities are cascade-only at any plan status.",
            "concept_remove is destructive; verify concept_id with concept_get before calling it.",
        ],
    }
