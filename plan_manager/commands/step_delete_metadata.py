"""Extended AI/documentation metadata for the step_delete command."""

from typing import Any


def get_step_delete_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepDeleteCommand.

    Args:
        cls: The StepDeleteCommand class object, used to source identity
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
            "Removes an existing step. This is a destructive, mutating "
            "command that defaults to a dry run: dry_run is True unless "
            "explicitly set to False, and a dry run returns the impact set "
            "without writing anything. A real run is refused with "
            "INVALID_TRANSITION — deletion refused for a step that still "
            "has children — when the target step still has children; "
            "delete or move them first. Otherwise a real run runs under the "
            "mutation admission regime: direct execution is admitted only "
            "when the target step is not frozen; otherwise the command "
            "returns CASCADE_REQUIRED, or CASCADE_CONFLICT when a "
            "cascade_uuid was supplied but does not admit the mutation, or "
            "FROZEN_ARTIFACT when the target is frozen at or below the "
            "change point. A real run records a tombstone snapshot (the "
            "pre-delete step snapshot with an added \"deleted\": true key) "
            "as the revision change, then deletes the step, then verifies "
            "the deletion by confirming the step is absent on re-read."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Human-readable identifier of the step to delete.",
                "type": "string",
                "required": True,
            },
            "cascade_uuid": {
                "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                "type": "string",
                "required": False,
            },
            "dry_run": {
                "description": "When true (the default), report the delete's impact without writing anything. Set to false to perform the deletion.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
        },
        "return_value": {
            "success": {
                "description": "A dry-run impact report, or the confirmed deletion result.",
                "data": {
                    "dry_run": "True for a dry-run report, False for a completed deletion.",
                    "would_delete": "Artifact path of the step that would be deleted (dry run only).",
                    "impact": "List of artifact paths of steps that would be invalidated by the delete (dry run only).",
                    "deleted_step_id": "The step_id that was deleted (real run only).",
                    "revision_uuid": "UUID of the version-store revision that recorded the tombstone, as a string (real run only).",
                },
                "example": {
                    "dry_run": True,
                    "would_delete": "docs/plans/example/G-005-api-surface/T-006-step-commands/README.yaml",
                    "impact": ["docs/plans/example/G-005-api-surface/README.yaml"],
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
                "description": "Preview the impact of deleting a step without deleting it.",
                "command": {"plan": "plan_manager", "step_id": "T-006"},
                "explanation": "dry_run defaults to true; returns the would-be-deleted path and its impact set only.",
            },
            {
                "description": "Actually delete a step after reviewing the dry-run impact.",
                "command": {"plan": "plan_manager", "step_id": "T-006", "dry_run": False},
                "explanation": "Writes the tombstone revision, deletes the step, and verifies its absence by re-read.",
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
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID.",
            },
            "INVALID_TRANSITION": {
                "description": "deletion refused for a step that still has children",
                "message": "step {step_id} has children; delete or move them first",
                "solution": "Delete or move the step's children first, or move this step to a leaf position, then retry.",
            },
            "CASCADE_REQUIRED": {
                "description": "The target step is not directly mutable and no cascade_uuid was supplied.",
                "message": "cascade required to delete this step",
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
                "solution": "Begin a cascade to delete a frozen step.",
            },
        },
        "best_practices": [
            "Always call with dry_run true (or omit dry_run) first to review the impact set before deleting.",
            "Omit cascade_uuid for direct-mode deletion on non-frozen steps; supply it only when working inside an open cascade.",
            "This command deletes plan data irreversibly outside the version store's tombstone snapshot; use only on plans you intend to change.",
        ],
    }
