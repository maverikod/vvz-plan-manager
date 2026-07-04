"""Extended AI/documentation metadata for the concept_add command."""

from typing import Any, Dict


def get_concept_add_metadata(cls) -> Dict[str, Any]:
    """Return extended metadata for ConceptAddCommand.

    Args:
        cls: The ConceptAddCommand class (passed by its classmethod metadata()).

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
            "Adds a new MRS concept (C-003) to a resolved plan. MRS entities "
            "are cascade-only (C-016) at any plan status: the call must carry "
            "the UUID of an already-open cascade in cascade_uuid, or it is "
            "rejected with CASCADE_CONFLICT. The write enforces the C-NNN "
            "identifier pattern, uniqueness, non-empty name and definition, "
            "and resolution of every source label to a stored binding "
            "paragraph, so a mechanically invalid MRS entry cannot be "
            "written. The mutation is recorded as a cascade revision with "
            "the full node snapshot and verified by re-reading the concept "
            "after write; this command does not support dry_run, matching "
            "the cascade-only write discipline of C-016 (the cascade itself "
            "is the reviewable, revertible unit, not a per-call preview)."
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
                "description": "New concept identifier in pattern C-NNN. Must be unique within the plan.",
                "type": "string",
                "required": True,
            },
            "name": {
                "description": "Concept canonical name.",
                "type": "string",
                "required": True,
            },
            "definition": {
                "description": "Concept one-sentence definition.",
                "type": "string",
                "required": True,
            },
            "properties": {
                "description": "Free-form property statements of the concept.",
                "type": "array",
                "required": False,
                "default": [],
            },
            "source_labels": {
                "description": "HRS paragraph labels that justify this concept; each must resolve to a stored binding paragraph.",
                "type": "array",
                "required": False,
                "default": [],
            },
        },
        "return_value": {
            "success": {
                "description": "The written concept verified by re-read, with its cascade revision.",
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
                    "concept_id": "C-037",
                    "name": "ExampleConcept",
                    "definition": "An example concept added for illustration.",
                    "properties": [],
                    "source_labels": ["{a1b2}"],
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
                "description": "Add a new concept under an open cascade.",
                "command": {
                    "plan": "plan-manager",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "concept_id": "C-037",
                    "name": "ExampleConcept",
                    "definition": "An example concept added for illustration.",
                    "source_labels": ["{a1b2}"],
                },
                "explanation": "Writes a new concept row under the given open cascade and returns it verified by re-read.",
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
            "DUPLICATE_ID": {
                "description": "concept_id already exists in the plan.",
                "message": "duplicate concept id: {concept_id}",
                "solution": "Choose an unused concept_id or use concept_update to modify the existing concept.",
            },
            "PARAGRAPH_NOT_FOUND": {
                "description": "One of source_labels does not resolve to a stored binding paragraph.",
                "message": "unresolved source label: {label}",
                "solution": "Call paragraph listing to find valid labels and retry with resolvable source_labels.",
            },
            "IMPORT_INVALID": {
                "description": "The concept payload is structurally invalid and cannot be written.",
                "message": "invalid concept payload: {details}",
                "solution": "Fix concept_id, name, definition, properties, and source_labels so they satisfy the MRS validation rules.",
            },
        },
        "best_practices": [
            "Begin a cascade before calling concept_add; MRS entities are cascade-only at any plan status.",
            "Verify every source_labels entry resolves via the paragraph listing before writing.",
            "Re-read with concept_get after the cascade commits to confirm the final state.",
        ],
    }
