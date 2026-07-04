"""Extended AI/documentation metadata for the step_update command."""

from typing import Any


def get_step_update_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepUpdateCommand.

    Args:
        cls: The StepUpdateCommand class object, used to source identity
            attributes (name, version, category, author, email) so the
            metadata dictionary never drifts from the class definition.

    Returns:
        A dictionary with the required metadata fields: name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases,
        best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Patches level-specific fields of an existing step under its "
            "declarative level schema, re-validating every touched "
            "reference. This is a mutating command that runs under the "
            "mutation admission regime: direct execution is admitted only "
            "when the target step is not frozen; otherwise the command "
            "returns CASCADE_REQUIRED, or CASCADE_CONFLICT when a "
            "cascade_uuid was supplied but does not admit the mutation, or "
            "FROZEN_ARTIFACT when the target is frozen at or below the "
            "change point. The command verifies its own result by "
            "re-reading the patched step after writing the revision."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Human-readable identifier of the step to patch.",
                "type": "string",
                "required": True,
            },
            "fields": {
                "description": "Non-empty level-specific field patch applied to the step's fields dict.",
                "type": "object",
                "required": True,
            },
            "cascade_uuid": {
                "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The patched step's identity, fields, status, and the revision that recorded it.",
                "data": {
                    "uuid": "Immutable UUID identity of the step, as a string.",
                    "step_id": "Human-readable step identifier.",
                    "fields": "The step's fields dict after the patch, as re-read from storage.",
                    "status": "Current lifecycle status of the step.",
                    "revision_uuid": "UUID of the version-store revision that recorded the patch, as a string.",
                },
                "example": {
                    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "step_id": "T-006",
                    "fields": {"name": "step-commands"},
                    "status": "draft",
                    "revision_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef",
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "Stable domain error code (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Patch a single level-specific field on an existing step.",
                "command": {"plan": "plan_manager", "step_id": "T-006", "fields": {"name": "step-commands"}},
                "explanation": "Applies the given field patch to T-006 and returns the re-read result.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "No step with the given step_id exists in the resolved plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree to list valid step_id values for the plan.",
            },
            "CASCADE_REQUIRED": {
                "description": "The target step is not directly mutable and no cascade_uuid was supplied.",
                "message": "cascade required to update this step",
                "solution": "Begin a cascade and retry with its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this mutation.",
                "message": "cascade_uuid does not admit this mutation",
                "solution": "Verify the cascade is open, targets this plan, and retry with the correct cascade_uuid.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The target step is frozen at or below the change point and no admitting cascade was supplied.",
                "message": "target is frozen at or below the change point",
                "solution": "Begin a cascade to mutate a frozen step.",
            },
        },
        "best_practices": [
            "Call step_get first to confirm the current fields before patching.",
            "Omit cascade_uuid for direct-mode updates on non-frozen steps; supply it only when working inside an open cascade.",
            "Re-read the step with step_get after the call to confirm the patch was applied as expected.",
        ],
    }
