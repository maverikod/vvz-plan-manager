"""Extended AI/documentation metadata for the relation_remove command."""

from typing import Any, Dict


def get_relation_remove_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for RelationRemoveCommand.

    Args:
        cls: The RelationRemoveCommand class (passed by its classmethod metadata()).

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
            "Removes an existing MRS relation (C-004) between two concepts. "
            "MRS entities are cascade-only (C-016) at any plan status: the "
            "call must carry the UUID of an already-open cascade in "
            "cascade_uuid, or it is rejected with CASCADE_CONFLICT. The "
            "removal is destructive: it is recorded as a cascade revision "
            "with a tombstone node snapshot (the pre-removal fields plus "
            "\"deleted\": true) and verified by re-reading the relation "
            "list after write to confirm the edge no longer appears. This "
            "command does not support dry_run; the reviewable, revertible "
            "unit is the open cascade itself (C-016), which can be aborted "
            "before commit."
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
                "description": "The removed relation confirmed by re-read, with its cascade revision.",
                "data": {
                    "from_concept": "Relation source endpoint concept_id that was removed.",
                    "to_concept": "Relation target endpoint concept_id that was removed.",
                    "type": "Relation type that was removed.",
                    "deleted": "Always true on success.",
                    "revision_uuid": "UUID of the cascade revision that recorded this removal.",
                },
                "example": {
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "type": "depends_on",
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
                "description": "Remove an existing relation under an open cascade.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "type": "depends_on",
                },
                "explanation": "Removes the depends_on edge from C-004 to C-003 under the given open cascade and confirms it no longer resolves.",
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
            "RELATION_NOT_FOUND": {
                "description": "No relation with the given from_concept, to_concept, and type exists.",
                "message": "relation not found: {from_concept}-{type}->{to_concept}",
                "solution": "Call relation_list and retry with a from_concept, to_concept, and type that match an existing edge.",
            },
        },
        "best_practices": [
            "Call relation_list before relation_remove to confirm the exact edge (from_concept, to_concept, type) exists.",
            "Begin a cascade before calling relation_remove; MRS entities are cascade-only at any plan status.",
            "relation_remove is destructive; re-check with relation_list after the cascade commits.",
        ],
    }
