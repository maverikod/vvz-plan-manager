"""Extended AI/documentation metadata for the plan completion-lock commands
(plan_completed_set, plan_comment_set; bug c3950b83)."""

from typing import Any


def get_plan_completed_set_metadata(cls: type) -> dict[str, Any]:
    """Return the extended documentation metadata for PlanCompletedSetCommand.

    Args:
        cls: The PlanCompletedSetCommand class, used to source identity
            attributes (name, version, category, author, email).

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
            "Set or unset a plan's completion lock (bug c3950b83). This "
            "command is ALWAYS reachable, regardless of the plan's freeze "
            "state or its current completed value (idempotent when "
            "unchanged) -- it is one of exactly two commands (the other is "
            "plan_comment_set) exempt from the PLAN_COMPLETED guard, since "
            "the flag it sets is what that guard checks. Once completed is "
            "true, every OTHER mutating command that resolves its plan "
            "parameter to this plan refuses with the PLAN_COMPLETED domain "
            "code; read-only commands (plan_list, step_get/tree, "
            "cascade_preview, exports, etc.) stay fully allowed either way. "
            "Every call writes an immutable runtime audit record (action="
            "plan_completed_set, actor=changed_by, the from/to values, the "
            "plan uuid) via the same append-only mechanism used by "
            "plan_unfreeze and subtree_unfreeze."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "completed": {
                "description": "The new completion-lock value.",
                "type": "boolean",
                "required": True,
            },
            "changed_by": {
                "description": "Identity of the actor requesting the change; recorded in the audit trail. Must be a non-empty string.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The plan's identity and completion-lock state after the change, plus the audit record uuid.",
                "data": {
                    "plan_uuid": "Immutable UUID identity of the plan, as a string.",
                    "completed": "The plan's completed flag after the change, as re-read from storage.",
                    "audit_uuid": "UUID of the runtime audit record that recorded this change, as a string.",
                },
                "example": {
                    "plan_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "completed": True,
                    "audit_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef",
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "PLAN_NOT_FOUND",
                "message": "plan not found: {plan}",
            },
        },
        "usage_examples": [
            {
                "description": "Mark a fully executed, frozen plan completed.",
                "command": {"plan": "planmgr-cr5a-agent-config-data-layer", "completed": True, "changed_by": "l1-orchestrator"},
                "explanation": "Sets completed=true and locks the plan against every other mutating command.",
            },
            {
                "description": "Unset the completion lock to allow further mutation.",
                "command": {"plan": "planmgr-cr5a-agent-config-data-layer", "completed": False, "changed_by": "l1-orchestrator"},
                "explanation": "Sets completed=false; every other mutating command is admitted again.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan identifier.",
            },
            "RUNTIME_VALIDATION_ERROR": {
                "description": "changed_by is missing or an empty/whitespace-only string.",
                "message": "changed_by must be a non-empty string",
                "solution": "Supply a non-empty actor identity.",
            },
        },
        "best_practices": [
            "Call plan_completed_set(completed=false) BEFORE plan_delete on a completed plan -- plan_delete is itself refused with PLAN_COMPLETED while the flag is set.",
            "Use plan_comment_set to record why a plan was marked completed; the comment field is always mutable independent of the lock.",
            "Call plan_list or step_tree to confirm state -- both surface completed and comment and are never blocked.",
        ],
    }


def get_plan_comment_set_metadata(cls: type) -> dict[str, Any]:
    """Return the extended documentation metadata for PlanCommentSetCommand.

    Args:
        cls: The PlanCommentSetCommand class, used to source identity
            attributes (name, version, category, author, email).

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
            "Set, replace, or clear a plan's free-form comment (bug "
            "c3950b83). This command is ALWAYS reachable, regardless of "
            "the plan's freeze state or its completed value -- it is one "
            "of exactly two commands (the other is plan_completed_set) "
            "exempt from the PLAN_COMPLETED guard. Passing comment=null "
            "clears any existing comment. Every call writes an immutable "
            "runtime audit record (action=plan_comment_set, actor="
            "changed_by, the from/to values, the plan uuid)."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "comment": {
                "description": "The new comment text, or null to clear the comment.",
                "type": "string",
                "required": False,
            },
            "changed_by": {
                "description": "Identity of the actor requesting the change; recorded in the audit trail. Must be a non-empty string.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The plan's identity and comment after the change, plus the audit record uuid.",
                "data": {
                    "plan_uuid": "Immutable UUID identity of the plan, as a string.",
                    "comment": "The plan's comment after the change, as re-read from storage (null if cleared).",
                    "audit_uuid": "UUID of the runtime audit record that recorded this change, as a string.",
                },
                "example": {
                    "plan_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "comment": "Shipped in 0.1.58; keeping frozen for reference.",
                    "audit_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef",
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "PLAN_NOT_FOUND",
                "message": "plan not found: {plan}",
            },
        },
        "usage_examples": [
            {
                "description": "Attach a closeout note to a plan.",
                "command": {"plan": "planmgr-cr5a-agent-config-data-layer", "comment": "Shipped in 0.1.58.", "changed_by": "l1-orchestrator"},
                "explanation": "Sets the plan's comment field.",
            },
            {
                "description": "Clear a plan's comment.",
                "command": {"plan": "planmgr-cr5a-agent-config-data-layer", "comment": None, "changed_by": "l1-orchestrator"},
                "explanation": "Sets the plan's comment field back to null.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan identifier.",
            },
            "RUNTIME_VALIDATION_ERROR": {
                "description": "changed_by is missing or an empty/whitespace-only string.",
                "message": "changed_by must be a non-empty string",
                "solution": "Supply a non-empty actor identity.",
            },
        },
        "best_practices": [
            "Use plan_comment_set to explain WHY a plan is (or is not) marked completed; the comment is independent of the lock and never blocked.",
            "comment is optional and nullable: omit it, or pass comment=null explicitly, to clear the plan's comment; pass a string to set or replace it.",
        ],
    }
