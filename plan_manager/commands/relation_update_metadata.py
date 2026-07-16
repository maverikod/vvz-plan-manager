"""Extended AI/documentation metadata for the relation_update command."""

from typing import Any, Dict

def get_relation_update_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for RelationUpdateCommand.

    Args:
        cls: The RelationUpdateCommand class (passed by its classmethod metadata()).

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
            "Updates the type of an existing MRS relation (C-004) between two "
            "concepts, replacing its current type with a new one for the same "
            "from_concept/to_concept pair. MRS entities are cascade-only "
            "(C-016) at any plan status: the call must carry the UUID of an "
            "already-open cascade in cascade_uuid, or it is rejected with "
            "CASCADE_CONFLICT. The write enforces the seven allowed relation "
            "types for new_type and requires an existing row matching "
            "from_concept, to_concept, and the current type; the mutation is "
            "recorded as a cascade revision with the full post-change node "
            "snapshot and verified by re-reading the relation list after "
            "write to confirm the new type resolves and the old type no "
            "longer does. This command does not support dry_run, matching "
            "the cascade-only write discipline of C-016."
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
                "description": "Current relation type of the existing edge to update.",
                "type": "string",
                "required": True,
                "enum": ["uses", "owns", "implements", "extends", "depends_on", "produces", "consumes"],
            },
            "new_type": {
                "description": "New relation type to write in place of type.",
                "type": "string",
                "required": True,
                "enum": ["uses", "owns", "implements", "extends", "depends_on", "produces", "consumes"],
            },
        },
        "return_value": {
            "success": {
                "description": "The updated relation verified by re-read, with its cascade revision.",
                "data": {
                    "from_concept": "Relation source endpoint concept_id.",
                    "to_concept": "Relation target endpoint concept_id.",
                    "previous_type": "Relation type before the update.",
                    "type": "Relation type after the update (equal to new_type).",
                    "revision_uuid": "UUID of the cascade revision that recorded this write.",
                },
                "example": {
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "previous_type": "uses",
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
                "description": "Update an existing relation's type under an open cascade.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "from_concept": "C-004",
                    "to_concept": "C-003",
                    "type": "uses",
                    "new_type": "depends_on",
                },
                "explanation": "Rewrites the uses edge from C-004 to C-003 as a depends_on edge under the given open cascade and returns it verified by re-read.",
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
                "description": "No relation with the given from_concept, to_concept, and current type exists.",
                "message": "relation not found: {from_concept}-{type}->{to_concept}",
                "solution": "Call relation_list and retry with a from_concept, to_concept, and type that match an existing edge.",
            },
            "IMPORT_INVALID": {
                "description": "new_type is not one of the seven allowed relation types.",
                "message": "invalid relation payload: {details}",
                "solution": "Supply new_type as one of uses, owns, implements, extends, depends_on, produces, consumes.",
            },
        },
        "best_practices": [
            "Call relation_list before relation_update to confirm the exact current edge (from_concept, to_concept, type) exists.",
            "Begin a cascade before calling relation_update; MRS entities are cascade-only at any plan status.",
            "type identifies the existing edge to change; new_type is the value it becomes -- they must both be supplied even when only one differs from the other.",
            "Re-read with relation_list after the cascade commits to confirm the final state.",
        ],
    }
