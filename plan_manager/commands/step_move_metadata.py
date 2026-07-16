"""Extended AI/documentation metadata for the step_move command."""

from typing import Any


def get_step_move_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepMoveCommand.

    Args:
        cls: The StepMoveCommand class object, used to source identity
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
            "Moves an existing step to a new parent, re-assigning its "
            "human-readable step_id within the new parent's scope and "
            "rewriting every reference to the moved identifier in one "
            "operation; the step's uuid identity never changes, but its "
            "step_id after the move may differ from the step_id before the "
            "move. This is a mutating command that runs under the mutation "
            "admission regime and enforces the frozen-subtree membership "
            "invariant on BOTH ends of the move: direct execution is "
            "admitted only when the moved step is not frozen at or below "
            "the change point, has no frozen ancestor, and the new parent "
            "is likewise not frozen at or below the change point and has "
            "no frozen ancestor; otherwise the command returns "
            "CASCADE_REQUIRED, or CASCADE_CONFLICT when a cascade_uuid was "
            "supplied but does not admit the mutation, or FROZEN_ARTIFACT "
            "when the moved step OR the new parent is frozen at or below "
            "the change point or has a frozen ancestor. The command "
            "verifies its own result by re-reading the moved step after "
            "writing the revision."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Human-readable identifier of the step to move.",
                "type": "string",
                "required": True,
            },
            "new_parent_step_id": {
                "description": "Human-readable step_id of the new parent step.",
                "type": "string",
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
                "description": "The moved step's identity, its old and re-assigned step_id, new parent, path, status, and the revision that recorded it.",
                "data": {
                    "uuid": "Immutable UUID identity of the moved step, as a string.",
                    "old_step_id": "Human-readable step identifier the step had before the move.",
                    "new_step_id": "Human-readable step identifier re-assigned to the step within the new parent's scope.",
                    "parent_step_uuid": "UUID of the new parent step, as a string, or null for a level-3 step.",
                    "path": "Artifact path of the step at its new location.",
                    "status": "Current lifecycle status of the moved step.",
                    "revision_uuid": "UUID of the version-store revision that recorded the move, as a string.",
                },
                "example": {
                    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "old_step_id": "T-006",
                    "new_step_id": "T-002",
                    "parent_step_uuid": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "path": "docs/plans/example/G-006-other/T-002-step-commands/README.yaml",
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
                "description": "Move a tactical step under a different global step.",
                "command": {"plan": "plan_manager", "step_id": "T-006", "new_parent_step_id": "G-006"},
                "explanation": "Re-parents T-006 under G-006, re-assigning its step_id within the new parent's scope, and rewrites every reference to the old id in one operation.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "step_id or new_parent_step_id does not match any step in the plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree to list valid step_id values for the plan.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID.",
            },
            "AMBIGUOUS_PARENT_STEP_ID": {
                "description": "A bare local new_parent_step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {new_parent_step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID for new_parent_step_id.",
            },
            "CASCADE_REQUIRED": {
                "description": "The moved step is not directly mutable and no cascade_uuid was supplied.",
                "message": "cascade required to move this step",
                "solution": "Begin a cascade and retry with its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this mutation.",
                "message": "cascade_uuid does not admit this mutation",
                "solution": "Verify the cascade is open, targets this plan, and retry with the correct cascade_uuid.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The moved step OR the new parent is frozen at or below the change point, or has a frozen ancestor, and no admitting cascade was supplied.",
                "message": "target is frozen at or below the change point",
                "solution": "Begin a cascade to move a step into, out of, or within a frozen subtree.",
            },
        },
        "best_practices": [
            "Call step_tree first to confirm both step_id and new_parent_step_id exist.",
            "Omit cascade_uuid for direct-mode moves on non-frozen steps; supply it only when working inside an open cascade.",
            "Re-read the moved step and its former and new parents with step_get to confirm the move's effect.",
            "Use the returned new_step_id, not the pre-move step_id, for any subsequent step_get, step_update, step_move, step_delete, or step_set_status call against the moved step.",
            "The frozen-subtree membership invariant is checked on both the moved step and new_parent_step_id: moving a step into or out of a frozen subtree, or within one, requires an admitting cascade_uuid.",
        ],
    }
