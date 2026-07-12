"""Extended metadata for the plan_unfreeze command."""


def get_plan_unfreeze_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for PlanUnfreezeCommand.

    Args:
        cls: The PlanUnfreezeCommand class supplying identity attributes
            (name, version, descr, category, author, email).

    Returns:
        A dictionary with all fields required by the command metadata
        standard: name, version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "The audited escape hatch out of full freeze -- the ONLY door "
            "that reopens a fully frozen plan. A plan is fully frozen when "
            "it has at least one step and every step has status='frozen' "
            "(plan.status itself is never set to 'frozen'; the frozen state "
            "is derived from step statuses). Such a plan is deliberately "
            "read-only: cascade_begin refuses it with FROZEN_TRUTH_WRITE, so "
            "the ordinary reopen path (open a cascade, then scoped "
            "step_transition frozen->draft) has no way to start -- a "
            "permanent deadlock this command resolves. plan_unfreeze refuses "
            "unless the plan is fully frozen (a not-fully-frozen plan gets "
            "PLAN_NOT_FULLY_FROZEN and is told to use cascade_begin), refuses "
            "if a cascade is already open (CASCADE_CONFLICT), and requires a "
            "non-empty changed_by and reason (RUNTIME_VALIDATION_ERROR "
            "otherwise). On success it writes an immutable runtime audit "
            "record (action=plan_unfreeze, actor=changed_by, the reason, the "
            "plan uuid, and the head revision at unfreeze) and opens a "
            "cascade on the plan, bypassing ONLY the all-steps-frozen "
            "refusal (via an explicit internal entry point of begin_cascade, "
            "never by weakening the public cascade_begin guard, which still "
            "refuses fully frozen plans). Safety: this mutates database state "
            "(one appended audit row plus a new open cascade record and its "
            "ref) but does NOT touch the published plan head -- no step "
            "leaves 'frozen' until you run a scoped step_transition "
            "frozen->draft under the returned cascade_uuid. Undo: abort the "
            "opened cascade with cascade_abort to discard the reopen with no "
            "effect on published truth. The command verifies its own result "
            "by re-reading the open cascade record and confirming its "
            "identity. Cascade status vocabulary: open, committed, aborted. "
            "Next steps after unfreeze: run step_transition(to_status=draft, "
            "scope=..., cascade_uuid=<returned>) to reopen the steps you "
            "need, then cascade_commit (requires a green gate) or "
            "cascade_abort."
        ),
        "parameters": {
            "plan": {
                "description": "Plan UUID or unique plan name to unfreeze.",
                "type": "string",
                "required": True,
            },
            "changed_by": {
                "description": (
                    "Identity of the actor requesting the unfreeze; recorded "
                    "in the audit trail. Must be a non-empty string."
                ),
                "type": "string",
                "required": True,
            },
            "reason": {
                "description": (
                    "Why the fully-frozen plan is being reopened; recorded in "
                    "the audit trail. Must be a non-empty string."
                ),
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "The opened cascade identity and its anchor revision, "
                    "confirmed by re-reading the open cascade record, plus a "
                    "statement of the next steps to complete the reopen."
                ),
                "data": {
                    "cascade_uuid": "UUID of the cascade opened by the unfreeze.",
                    "base_revision_uuid": (
                        "UUID of the plan head revision the cascade is "
                        "anchored to."
                    ),
                    "ref_name": "Name of the cascade ref record.",
                    "created_at": "ISO 8601 timestamp of cascade creation.",
                    "plan_uuid": "UUID of the unfrozen plan.",
                    "audit_uuid": "UUID of the appended runtime audit record.",
                    "next_steps": (
                        "Human-readable guidance for completing the reopen "
                        "via a scoped step_transition frozen->draft under the "
                        "returned cascade_uuid."
                    ),
                },
                "example": {
                    "cascade_uuid": "6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    "base_revision_uuid": "1a2b3c4d-5e6f-4071-8899-aabbccddeeff",
                    "ref_name": "cascade/6f1c2e2a",
                    "created_at": "2026-07-13T12:00:00+00:00",
                    "plan_uuid": "9c3d4e5f-6a7b-4c8d-9e0f-112233445566",
                    "audit_uuid": "7b8c9d0e-2233-4455-8677-8899aabbccdd",
                    "next_steps": (
                        "Cascade opened. Run step_transition(plan=..., "
                        "to_status='draft', scope=..., cascade_uuid="
                        "'6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d') to reopen "
                        "frozen steps, then cascade_commit or cascade_abort."
                    ),
                },
            },
            "error": {
                "description": "Domain error result on failure.",
                "code": "Stable domain error code string (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Optional diagnostic fields, present when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Reopen a fully frozen plan for a corrective change.",
                "command": {
                    "plan": "planmgr-runtime-work-layer-integration",
                    "changed_by": "orchestrator",
                    "reason": "reopen to fix defect d01b3bc6 in G-004",
                },
                "explanation": (
                    "Audits the escape and opens a cascade on the fully "
                    "frozen plan; follow with a scoped step_transition "
                    "frozen->draft under the returned cascade_uuid."
                ),
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan parameter does not resolve to any plan.",
                "message": "plan not found: {plan}",
                "solution": (
                    "List existing plans and retry with a valid plan UUID or "
                    "name."
                ),
            },
            "PLAN_NOT_FULLY_FROZEN": {
                "description": (
                    "The plan is not fully frozen (it has no steps, or at "
                    "least one step is not frozen). plan_unfreeze is only for "
                    "escaping full freeze; a plan that still has a non-frozen "
                    "step can be mutated through the ordinary cascade path."
                ),
                "message": (
                    "plan {plan} is not fully frozen; open a cascade with "
                    "cascade_begin instead"
                ),
                "solution": (
                    "Use cascade_begin to open a cascade on a plan that is "
                    "not fully frozen."
                ),
            },
            "CASCADE_CONFLICT": {
                "description": (
                    "The plan already has an open cascade, or the post-open "
                    "re-read did not confirm the newly created cascade record."
                ),
                "message": "plan {plan} already has an open cascade.",
                "solution": (
                    "Inspect the existing cascade with cascade_preview, or "
                    "close it with cascade_commit/cascade_abort, before "
                    "unfreezing."
                ),
            },
            "RUNTIME_VALIDATION_ERROR": {
                "description": (
                    "changed_by or reason was empty or whitespace-only; both "
                    "are mandatory so the audit trail records who reopened the "
                    "plan and why."
                ),
                "message": "changed_by and reason must be non-empty.",
                "solution": (
                    "Retry with a non-empty changed_by identity and a "
                    "non-empty reason."
                ),
            },
        },
        "best_practices": [
            "Reserve plan_unfreeze for genuinely fully-frozen plans; for a "
            "plan that still has any non-frozen step, use cascade_begin.",
            "Give a specific, auditable reason -- the reason and actor are "
            "recorded immutably in the runtime audit trail at the plan's "
            "head revision.",
            "After unfreeze, reopen only the steps you need with a scoped "
            "step_transition(to_status='draft', cascade_uuid=...), then "
            "cascade_commit (green gate required) or cascade_abort.",
            "See the {1e67} roadmap note: subtree freeze/unfreeze already "
            "works via scoped step_transition; plan_unfreeze covers only the "
            "whole-plan full-freeze escape.",
        ],
    }
