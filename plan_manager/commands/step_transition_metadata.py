"""Extended AI/documentation metadata for the step_transition command."""

from typing import Any

from plan_manager.domain.status_model import ATOMIC_ONLY_STATUSES


# Admissible source -> target matrix for the three statuses step_transition can
# request (draft, ready_for_review, frozen). needs_review is never a
# step_transition target (cascade-only), and the atomic-execution statuses
# in_progress/done are reachable only through step_set_status, not this command.
_LEGAL_TRANSITIONS_BY_SOURCE = {
    "draft": ["ready_for_review", "frozen"],
    "ready_for_review": ["draft", "frozen"],
    "frozen": ["draft"],
    "needs_review": ["draft", "frozen"],
    "in_progress": [],
    "done": [],
}


def get_step_transition_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepTransitionCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Moves one step or every step under a scope through the authoring "
            "lifecycle in one auditable operation. The command supports "
            "single-step transition by step_id and bulk transition by scope "
            "(whole_plan, G-NNN, or G-NNN/T-NNN). Bulk writes are recorded as "
            "one version-store revision regardless of how many steps change. "
            "When to_status is frozen and require_green is true, the command "
            "runs the mechanical gate for the requested scope before applying "
            "any mutation and refuses red gates without partial updates. "
            "dry_run reports the exact transition and skip sets without "
            "writing rows or revisions. The command changes the authoritative "
            "step.status column; it never stores inert lifecycle data inside "
            "step fields or fields.status. Transition legality is validated "
            "synchronously before any gate run: if any selected step cannot "
            "legally reach to_status the whole request is refused immediately "
            "with INVALID_TRANSITION (details.illegal carries each offending "
            "step's legal_targets) and no gate runs and no rows change — a "
            "single illegal step and a mixed legal/illegal scope are both "
            "rejected as one atomic batch. The command executes on the "
            "adapter's synchronous sync-start path, so fast results (an "
            "immediate INVALID_TRANSITION, a dry_run report, or a fast "
            "draft/ready_for_review transition) are returned to the caller "
            "directly; only a slow freeze gate that exceeds the server sync "
            "cap is auto-handed to the queue."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "to_status": {
                "description": "Target authoring lifecycle status.",
                "type": "string",
                "required": True,
                "enum": ["draft", "ready_for_review", "frozen"],
            },
            "step_id": {
                "description": "Single step to transition, as UUID, canonical path, or unambiguous local step id. Mutually exclusive with scope.",
                "type": "string",
                "required": False,
            },
            "scope": {
                "description": "Bulk transition scope: whole_plan, G-NNN, or G-NNN/T-NNN. Defaults to whole_plan when step_id is omitted.",
                "type": "string",
                "required": False,
            },
            "require_green": {
                "description": "When true, freezing requires the requested scope's mechanical gate to be green before any mutation.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
            "dry_run": {
                "description": "When true, report transition and skip sets without mutating rows or recording a revision.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "cascade_uuid": {
                "description": "Open cascade identifier required when reopening frozen steps.",
                "type": "string",
                "required": False,
            },
        },
        "legal_transitions": {
            "description": (
                "Admissible source->target transitions for this command. to_status "
                "may be draft, ready_for_review, or frozen. draft->frozen is applied "
                "as the multi-hop draft->ready_for_review->frozen inside one batch "
                "revision. frozen->draft (or frozen->ready_for_review) reopens a "
                "frozen step and requires an admitting cascade_uuid. needs_review is "
                "never a step_transition target (it is reached only by cascade "
                "propagation), and the atomic-execution statuses in_progress and done "
                "are reachable only through step_set_status, not this command."
            ),
            "by_source_status": _LEGAL_TRANSITIONS_BY_SOURCE,
            "target_statuses": ["draft", "ready_for_review", "frozen"],
            "excluded_targets": {
                "needs_review": "Cascade-propagation only; never a direct step_transition target.",
                "in_progress": "Atomic-step execution status; set via step_set_status only.",
                "done": "Atomic-step execution status; set via step_set_status only.",
            },
            "atomic_only_statuses": sorted(ATOMIC_ONLY_STATUSES),
        },
        "return_value": {
            "success": {
                "description": "Transition report and revision identity for the whole batch.",
                "data": {
                    "transitioned": "List of {uuid, step_id, path, from, to}.",
                    "skipped": "List of {uuid, step_id, path, from, reason}. Currently used for already_at_target.",
                    "illegal": "On INVALID_TRANSITION, details.illegal lists {uuid, step_id, path, from, to, reason, legal_targets} where legal_targets names the statuses actually reachable from that step's current status.",
                    "gate": "Gate summary: green, scope, revision_uuid, required, and checked.",
                    "revision_uuid": "Single resulting revision UUID, or null for dry_run/no-op.",
                    "dry_run": "Whether the command ran without mutation.",
                },
            },
            "error": {
                "description": "Domain error with stable domain_code in details.",
                "code": "Stable domain error code.",
                "message": "Human-readable message.",
                "details": "Programmatic diagnostic fields.",
            },
        },
        "usage_examples": [
            {
                "description": "Freeze a gate-green plan in one revision.",
                "command": {
                    "plan": "workspace_orchestration_refactoring",
                    "to_status": "frozen",
                    "scope": "whole_plan",
                },
                "explanation": "Runs the whole-plan gate, transitions draft/ready_for_review steps to frozen, and records one revision.",
            },
            {
                "description": "Preview a tactical subtree transition.",
                "command": {
                    "plan": "workspace_orchestration_refactoring",
                    "to_status": "ready_for_review",
                    "scope": "G-006/T-001",
                    "dry_run": True,
                },
                "explanation": "Returns exactly which steps would move without changing the database.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "step_id or scope does not resolve to any step in the plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree and retry with a valid canonical path.",
            },
            "INVALID_SCOPE": {
                "description": "scope is not whole_plan, G-NNN, or G-NNN/T-NNN, or was supplied together with step_id.",
                "message": "invalid transition scope",
                "solution": "Use step_id for a single step or scope for bulk, not both.",
            },
            "INVALID_TRANSITION": {
                "description": "At least one selected step cannot legally move to to_status.",
                "message": "illegal status transition",
                "solution": "Inspect the details.illegal list and transition through the legal lifecycle path.",
            },
            "CASCADE_REQUIRED": {
                "description": "A frozen step would be reopened without an admitting cascade_uuid.",
                "message": "cascade_uuid is required to reopen frozen steps",
                "solution": "Begin a cascade and retry with its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "cascade_uuid does not match the plan's open cascade.",
                "message": "cascade id does not match the open cascade",
                "solution": "Retry with the current open cascade UUID for this plan.",
            },
            "GATE_RED": {
                "description": "to_status=frozen requested a required green gate, but the scope gate is red.",
                "message": "mechanical gate is red for transition scope",
                "solution": "Run plan_validate, fix the findings, then retry.",
            },
        },
        "best_practices": [
            "Use dry_run=True before bulk transitions on large plans.",
            "Use scope='whole_plan' to publish an authored plan for plan_prompt_chain.",
            "Leave require_green=True for freeze operations unless deliberately testing error handling.",
            "Use step_tree or step_get after transition to verify authoritative status values; do not rely on fields.status.",
            "An illegal request (any selected step cannot reach to_status) is rejected synchronously and immediately with INVALID_TRANSITION and never enqueues a job; inspect details.illegal[*].legal_targets to pick a reachable status.",
            "This command runs synchronously on the adapter's sync-start path. Fast calls return their result directly. Only a slow whole-plan freeze gate that exceeds the server sync cap is auto-handed to the queue, in which case the response carries job_id with poll_with='queue_get_job_status' (never the builtin job_status, which reads a separate in-memory store).",
        ],
    }
