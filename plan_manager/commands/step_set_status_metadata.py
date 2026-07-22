"""Extended AI/documentation metadata for the step_set_status command."""

from typing import Any

from plan_manager.domain.status_model import (
    ATOMIC_ONLY_STATUSES,
    LEGAL_TRANSITIONS,
    STATUSES,
)


def _direct_targets(status: str) -> list[str]:
    targets = set(LEGAL_TRANSITIONS[status])
    if status == "frozen":
        targets.add("in_progress")
    return sorted(targets)


def get_step_set_status_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepSetStatusCommand.

    Args:
        cls: The StepSetStatusCommand class object, used to source identity
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
            "Drives a step through the lifecycle state machine, refusing "
            "illegal transitions and the transitions reserved for cascade "
            "propagation (needs_review can never be set directly). This is "
            "a mutating command that runs under the mutation admission "
            "regime: direct execution is admitted only when the target step "
            "is not frozen; otherwise the command returns CASCADE_REQUIRED, "
            "or CASCADE_CONFLICT when a cascade_uuid was supplied but does "
            "not admit the mutation, or FROZEN_ARTIFACT when the target is "
            "frozen at or below the change point. The command verifies its "
            "own result by re-reading the transitioned step after writing "
            "the revision."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step to transition, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                "type": "string",
                "required": True,
            },
            "status": {
                "description": "The new status to transition the step to.",
                "type": "string",
                "required": True,
                "enum": ["draft", "ready_for_review", "frozen", "needs_review", "in_progress", "done"],
            },
            "cascade_uuid": {
                "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The transitioned step's identity, new status, and the revision that recorded it.",
                "data": {
                    "uuid": "Immutable UUID identity of the step, as a string.",
                    "step_id": "Human-readable step identifier.",
                    "status": "The step's status after the transition, as re-read from storage.",
                    "revision_uuid": "UUID of the version-store revision that recorded the transition, as a string.",
                },
                "example": {
                    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "step_id": "T-006",
                    "status": "ready_for_review",
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
        "legal_transitions": {
            "description": (
                "Direct user-requested transitions enforced by the status "
                "model. needs_review is never a direct target; it is reserved "
                "for cascade propagation. in_progress and done are atomic-step "
                "statuses only, and in_progress is reached directly only from "
                "frozen atomic steps."
            ),
            "statuses": {
                status: {
                    "direct_targets": _direct_targets(status),
                    "scope": (
                        "atomic_steps_only"
                        if status in ATOMIC_ONLY_STATUSES
                        else "all_step_artifacts"
                    ),
                }
                for status in sorted(STATUSES | ATOMIC_ONLY_STATUSES)
            },
            "cascade_targets": {
                "needs_review": {
                    "from": "any_known_status",
                    "scope": "cascade_propagation_only",
                    "direct_request": "INVALID_TRANSITION",
                }
            },
            "notes": [
                "draft -> ready_for_review",
                "ready_for_review -> draft",
                "ready_for_review -> frozen",
                "needs_review -> draft",
                "needs_review -> frozen",
                "frozen -> in_progress is direct only for atomic steps",
                "in_progress -> done is direct only for atomic steps",
                "done has no direct outgoing transition",
                "needs_review as a requested target always yields INVALID_TRANSITION",
            ],
        },
        "usage_examples": [
            {
                "description": "Transition a step from draft to ready_for_review.",
                "command": {"plan": "plan_manager", "step_id": "T-006", "status": "ready_for_review"},
                "explanation": "Validates the transition against the status model and records it as a revision.",
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
                "description": "The requested status is not a legal transition from the step's current status, or is needs_review, which is reserved for cascade propagation.",
                "message": "invalid status transition",
                "solution": "Call step_get to check the step's current status and choose a legal target status.",
            },
            "CASCADE_REQUIRED": {
                "description": "The target step is not directly mutable and no cascade_uuid was supplied.",
                "message": "cascade required to transition this step",
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
                "solution": "Begin a cascade to transition a frozen step.",
            },
        },
        "best_practices": [
            "Call step_get first to confirm the step's current status before requesting a transition.",
            "Never request needs_review directly; it is set only by cascade propagation and always yields INVALID_TRANSITION.",
            "Omit cascade_uuid for direct-mode transitions on non-frozen steps; supply it only when working inside an open cascade.",
        ],
    }
