"""Extended AI/documentation metadata for the concept_update command."""

from typing import Any, Dict


def get_concept_update_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptUpdateCommand.

    Args:
        cls: The ConceptUpdateCommand class (passed by its classmethod metadata()).

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
            "Updates one or more fields of an existing MRS concept (C-003). "
            "MRS entities are cascade-only (C-016) at any plan status: the "
            "call must carry the UUID of an already-open cascade in "
            "cascade_uuid, or it is rejected with CASCADE_CONFLICT. fields "
            "must be a non-empty object whose keys are a subset of name, "
            "definition, properties, source_labels; every touched field is "
            "re-validated at write time, including resolution of any new "
            "source_labels to a stored binding paragraph. The mutation is "
            "recorded as a cascade revision with the full node snapshot and "
            "verified by re-reading the concept after write; this command "
            "does not support dry_run, matching the cascade-only write "
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
            "concept_id": {
                "description": "Concept identifier of the concept to update.",
                "type": "string",
                "required": True,
            },
            "fields": {
                "description": "Partial field set to update; keys must be a non-empty subset of name, definition, properties, source_labels.",
                "type": "object",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The updated concept verified by re-read, with its cascade revision.",
                "data": {
                    "uuid": "Concept row UUID.",
                    "plan_uuid": "Owning plan UUID.",
                    "concept_id": "Concept identifier, pattern C-NNN.",
                    "name": "Concept canonical name.",
                    "definition": "Concept one-sentence definition.",
                    "properties": "List of free-form property statements.",
                    "source_labels": "List of HRS paragraph labels justifying the concept.",
                    "revision_uuid": "UUID of the cascade revision that recorded this write.",
                },
                "example": {
                    "uuid": "5c1f9b0a-2e3d-4b8a-9c7a-1a2b3c4d5e6f",
                    "plan_uuid": "1a2b3c4d-5e6f-4a1b-8c2d-9e0f1a2b3c4d",
                    "concept_id": "C-003",
                    "name": "Concept",
                    "definition": "Updated one-sentence definition.",
                    "properties": ["identifier pattern C-NNN, unique within plan"],
                    "source_labels": ["{f6s2}"],
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
                "description": "Update the definition of an existing concept.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "concept_id": "C-003",
                    "fields": {"definition": "Updated one-sentence definition."},
                },
                "explanation": "Writes the new definition under the given open cascade and returns the concept verified by re-read.",
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
            "PARAGRAPH_NOT_FOUND": {
                "description": "One of the updated source_labels does not resolve to a stored binding paragraph.",
                "message": "unresolved source label: {label}",
                "solution": "Call paragraph listing to find valid labels and retry with resolvable source_labels.",
            },
            "IMPORT_INVALID": {
                "description": "The requested fields object is structurally invalid and cannot be written.",
                "message": "invalid concept update payload: {details}",
                "solution": "Pass a non-empty fields object whose keys and values satisfy the concept validation rules.",
            },
        },
        "best_practices": [
            "Pass only the fields that actually change; fields keys are validated against name, definition, properties, source_labels.",
            "Begin a cascade before calling concept_update; MRS entities are cascade-only at any plan status.",
            "Re-read with concept_get after the cascade commits to confirm the final state.",
        ],
    }
