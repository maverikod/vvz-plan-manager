"""Exhaustive agent-facing reference data for the info command.

This module answers, without reading source, the questions an executing agent
most often has to reverse-engineer from code today: the full status vocabulary
of every stateful entity, the admissible status transitions and their
reachability caveats, the per-stage operational checklists for the multi-step
lifecycles, the anchor-type tables, comment visibility modes, the queue/polling
guide, the create/read/update/delete reality per entity, and a category index of
every command on the surface.

Vocabularies are derived directly from the domain enum classes so this reference
can never silently drift from the values the commands actually enforce.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.domain.bug_fix import BugFixStatus, BugFixType
from plan_manager.domain.bug_fix_propagation import PropagationAction, PropagationStatus
from plan_manager.domain.bug_impact import (
    BugImpactStatus,
    BugImpactTargetType,
    BugImpactType,
)
from plan_manager.domain.bug_report import BugKind, BugSeverity, BugStatus
from plan_manager.domain.bug_source import BugSourceType
from plan_manager.domain.comment_visibility import (
    VISIBILITY_CONTEXT_MAP,
    CommentVisibility,
    PromptContextKind,
)
from plan_manager.domain.escalation import EscalationStatus
from plan_manager.domain.execution_attempt import (
    TERMINAL_ATTEMPT_STATUSES,
    ExecutionAttemptStatus,
)
from plan_manager.domain.model_binding import BindingScope
from plan_manager.domain.primary_anchor import PrimaryAnchorType
from plan_manager.domain.review_result import ReviewObjectType, ReviewStatus
from plan_manager.domain.runtime_comment import CommentAnchorType, CommentKind
from plan_manager.domain.runtime_role import RuntimeRole
from plan_manager.domain.status_model import (
    ATOMIC_ONLY_STATUSES,
    LEGAL_TRANSITIONS,
    STATUSES,
)
from plan_manager.domain.todo import TodoKind, TodoStatus
from plan_manager.domain.todo_link import TodoLinkType


# Cascade status vocabulary (frozenset in cascade.record); listed here in
# lifecycle order so the reference is deterministic.
_CASCADE_STATUSES = ["open", "committed", "aborted"]


def _vals(enum_cls: type[Enum]) -> list[str]:
    """Return an enum's member values in declaration order."""
    return [member.value for member in enum_cls]


def status_vocabularies() -> dict[str, Any]:
    """Every stateful entity's status vocabulary in one place.

    Each entry lists the ordered legal status values and, where the domain
    defines one, the terminal subset. These are the exact values the list and
    write commands validate against; they are no longer discoverable only via an
    INVALID_FILTER error.
    """
    return {
        "purpose": (
            "The authoritative status value set of every stateful entity on the "
            "surface. A value outside its entity's set is rejected (INVALID_FILTER "
            "on a list filter, or a validation error on a write)."
        ),
        "entities": {
            "step": {
                "values": sorted(STATUSES | ATOMIC_ONLY_STATUSES),
                "all_artifact_statuses": sorted(STATUSES),
                "atomic_only_statuses": sorted(ATOMIC_ONLY_STATUSES),
                "commands": ["step_set_status", "step_transition"],
                "notes": "in_progress/done apply to atomic (level-5) steps only; needs_review is cascade-propagation only.",
            },
            "cascade": {
                "values": _CASCADE_STATUSES,
                "terminal": ["committed", "aborted"],
                "commands": ["cascade_begin", "cascade_commit", "cascade_abort"],
            },
            "todo": {
                "values": _vals(TodoStatus),
                "commands": ["todo_create", "todo_resolve", "todo_close"],
                "notes": "Only open->resolved and open->closed are reachable post-creation; ready/in_progress/blocked/cancelled are settable only as the initial status at todo_create.",
            },
            "execution_attempt": {
                "values": _vals(ExecutionAttemptStatus),
                "terminal": sorted(TERMINAL_ATTEMPT_STATUSES),
                "commands": ["execution_attempt_create", "execution_attempt_report"],
                "notes": "No transition matrix is enforced; execution_attempt_report accepts any status regardless of the attempt's current status.",
            },
            "review_result": {
                "values": _vals(ReviewStatus),
                "object_types": _vals(ReviewObjectType),
                "commands": ["review_result_create"],
                "notes": "Review results are create-only verdicts; the status is a verdict, not a mutable lifecycle.",
            },
            "escalation": {
                "values": _vals(EscalationStatus),
                "commands": ["escalation_create", "escalation_resolve"],
                "notes": "open at creation; escalation_resolve is the only transition (open->resolved).",
            },
            "bug": {
                "values": _vals(BugStatus),
                "kinds": _vals(BugKind),
                "severities": _vals(BugSeverity),
                "commands": ["bug_create", "bug_confirm", "bug_reject", "bug_mark_duplicate", "bug_reopen", "bug_close"],
                "notes": "No enforced transition matrix. reported/triaged/confirmed/rejected/duplicate/reopened/closed are reachable via commands; fixing/fixed_source/propagating/verified are NOT set by any command post-creation (track fix progress via bug_fix_*/bug_impact_*/bug_propagation_* records, not bug.status).",
            },
            "bug_impact": {
                "values": _vals(BugImpactStatus),
                "impact_types": _vals(BugImpactType),
                "target_types": _vals(BugImpactTargetType),
                "commands": ["bug_impact_add", "bug_impact_update"],
                "notes": "Cleared statuses for closure are unaffected/verified; a skipped impact requires a reason and skip_decided_by.",
            },
            "bug_fix": {
                "values": _vals(BugFixStatus),
                "fix_types": _vals(BugFixType),
                "commands": ["bug_fix_create", "bug_fix_update", "bug_fix_verify"],
                "notes": "started_at is stamped on the in_progress transition; implemented_at on the implemented transition (at create or update); verified_at by bug_fix_verify.",
            },
            "bug_fix_propagation": {
                "values": _vals(PropagationStatus),
                "actions": _vals(PropagationAction),
                "finished_statuses": ["done", "verified", "skipped"],
                "commands": ["bug_propagation_create", "bug_propagation_update"],
            },
            "project_dependency": {
                "confidence_levels": ["confirmed", "unconfirmed", "suspected"],
                "commands": ["project_dependency_add", "project_dependency_discover"],
                "notes": "confidence is not a lifecycle status; a non-manual (discovered) edge can never be moved to confirmed because no project_dependency_confirm command is exposed.",
            },
        },
        "non_status_vocabularies": {
            "todo_kind": _vals(TodoKind),
            "todo_link_type": _vals(TodoLinkType),
            "comment_kind": _vals(CommentKind),
            "model_binding_scope": _vals(BindingScope),
            "runtime_role": _vals(RuntimeRole),
        },
    }


def lifecycle_matrices() -> dict[str, Any]:
    """Legal status-transition matrices for every stateful entity.

    For entities whose domain enforces a matrix (step, cascade) the admissible
    source->target sets are published. For entities whose store enforces no
    matrix (bug, bug_impact, bug_fix, propagation, execution_attempt, todo) the
    reachability reality is stated explicitly, including which vocabulary values
    are not reachable through any command.
    """
    step_matrix = {
        status: {
            "direct_targets": sorted(
                set(LEGAL_TRANSITIONS[status])
                | ({"in_progress"} if status == "frozen" else set())
            ),
            "scope": "atomic_steps_only" if status in ATOMIC_ONLY_STATUSES else "all_step_artifacts",
        }
        for status in sorted(STATUSES | ATOMIC_ONLY_STATUSES)
    }
    return {
        "step": {
            "enforced": True,
            "by_source_status": step_matrix,
            "cascade_only_target": {
                "needs_review": "Reachable only via cascade propagation; a direct request yields INVALID_TRANSITION.",
            },
            "notes": [
                "frozen->in_progress is a direct transition for atomic steps only.",
                "step_transition applies draft->frozen as the multi-hop draft->ready_for_review->frozen in one batch revision.",
                "Reopening a frozen step (frozen->draft/ready_for_review) requires an admitting cascade_uuid.",
            ],
        },
        "cascade": {
            "enforced": True,
            "by_source_status": {
                "open": {"direct_targets": ["committed", "aborted"]},
                "committed": {"direct_targets": []},
                "aborted": {"direct_targets": []},
            },
            "notes": [
                "open->committed requires a green mechanical gate (cascade_commit); otherwise GATE_RED and the cascade stays open.",
                "open->aborted is unconditional (cascade_abort).",
                "committed and aborted are terminal; retrying commit/abort on a closed cascade raises CASCADE_CONFLICT.",
            ],
        },
        "escalation": {
            "enforced": False,
            "by_source_status": {"open": {"direct_targets": ["resolved"]}, "resolved": {"direct_targets": []}},
            "notes": ["escalation_resolve overwrites unconditionally with no precondition on the current status."],
        },
        "bug": {
            "enforced": False,
            "command_transitions": {
                "bug_confirm": "-> confirmed",
                "bug_reject": "-> rejected",
                "bug_mark_duplicate": "-> duplicate",
                "bug_reopen": "-> reopened",
                "bug_close": "-> closed (refused unless BugClosureDiscipline is satisfied)",
            },
            "unreachable_post_creation": ["triaged", "fixing", "fixed_source", "propagating", "verified"],
            "notes": [
                "set_bug_status enforces no legality check; the store stamps confirmed_at/closed_at/reopened_at mechanically.",
                "fixing/fixed_source/propagating/verified/triaged can only be set as the initial status at bug_create; no command advances a bug into them afterward. Track fix progress via the bug_fix/bug_impact/bug_propagation records.",
            ],
        },
        "bug_impact": {
            "enforced": False,
            "notes": [
                "bug_impact_update sets any BugImpactStatus with no source-status check.",
                "For closure, an impact must be unaffected or verified, or skipped with a reason and skip_decided_by.",
            ],
        },
        "bug_fix": {
            "enforced": False,
            "notes": [
                "bug_fix_update sets any BugFixStatus with no source-status check; bug_fix_verify records verification and sets verified_at.",
                "reverted is settable but revert_info cannot be populated through any command (no revert command is exposed).",
            ],
        },
        "bug_fix_propagation": {
            "enforced": False,
            "notes": ["bug_propagation_update sets any PropagationStatus; started_at/finished_at are auto-stamped on the in_progress/finished transitions."],
        },
        "execution_attempt": {
            "enforced": False,
            "notes": ["execution_attempt_report accepts any ExecutionAttemptStatus regardless of the current status; a terminal attempt can be reported again."],
        },
        "todo": {
            "enforced": False,
            "reachable_post_creation": {"todo_resolve": "-> resolved", "todo_close": "-> closed"},
            "unreachable_post_creation": ["ready", "in_progress", "blocked", "cancelled"],
            "notes": ["todo_resolve/todo_close are unconditional with no precondition on the prior status; ready/in_progress/blocked/cancelled are settable only as the initial todo_create status."],
        },
    }


def operational_checklists() -> dict[str, Any]:
    """Per-stage 'what to set at each stage' checklists for the multi-step lifecycles."""
    return {
        "bug_fix_lifecycle": {
            "intended_flow": [
                "bug_create (status reported) -> bug_confirm once triage confirms a real defect (status confirmed).",
                "Assign the fix owner with bug_update(owner=...). NOTE: no command sets bug.status to fixing; use owner + the bug_fix record for progress.",
                "bug_fix_create(status=in_progress|implemented) to open the source fix; implemented stamps implemented_at.",
                "bug_impact_add for each affected downstream target (or bug_impact_discover to auto-suggest from the project dependency graph).",
                "bug_fix_verify(passed=true) to certify the source fix (sets verified_at); the fix status must reach verified for closure.",
                "For each impact, bug_propagation_create the required downstream action, drive it to done/verified/skipped (bug_propagation_update), and optionally bug_propagation_generate_todos to surface the work on the queue.",
                "bug_close once BugClosureDiscipline is satisfied: source fix verified, every impact cleared (unaffected/verified) or ownerly skipped, every propagation finished, mandatory TODOs closed, required cascades finished.",
            ],
            "honesty_note": "bug.status does not auto-advance through fixing/fixed_source/propagating/verified; those values are not written by any command. Treat the bug_fix/bug_impact/bug_propagation records — not bug.status — as the source of truth for fix progress until bug_close.",
        },
        "todo_lifecycle": [
            "todo_create with an initial status (open by default; ready/in_progress/blocked are settable here but cannot be changed later).",
            "todo_update to adjust title/description/priority_nice/assigned_to/blocking_reason/execution_result (status is NOT updatable here).",
            "todo_resolve (-> resolved) or todo_close (-> closed) to terminate; both are unconditional. There is no delete command for a TODO.",
            "todo_promote_to_cascade_request to escalate a TODO into a normative cascade request (does not itself open/commit the cascade).",
        ],
        "propagation_lifecycle": [
            "bug_propagation_create(action, status=pending|ready) for one impact.",
            "bug_propagation_update to advance status; in_progress stamps started_at, a finished status stamps finished_at.",
            "Drive to a finished status (done, verified, skipped) — required for the parent bug's closure.",
        ],
        "cascade_workflow": [
            "cascade_begin on a plan that is not fully frozen (a fully frozen plan raises FROZEN_TRUTH_WRITE).",
            "Make admitted mutations under the returned cascade_uuid.",
            "cascade_preview to inspect the gate/impact before committing.",
            "cascade_commit (requires a green gate; otherwise GATE_RED and the cascade stays open) or cascade_abort (unconditional; restores base state). Both are terminal.",
        ],
    }


def anchor_type_tables() -> dict[str, Any]:
    """The anchor-type vocabularies each anchored entity accepts."""
    return {
        "primary_anchor_types": {
            "purpose": "PrimaryAnchor kinds usable as a TODO/bug/general primary anchor; 'none' means unanchored.",
            "values": _vals(PrimaryAnchorType),
        },
        "comment_anchor_types": {
            "purpose": "RuntimeComment anchor kinds; a comment always attaches to a subject, so 'none' is NOT valid here.",
            "values": _vals(CommentAnchorType),
        },
        "bug_source_types": {
            "purpose": "The single primary source anchor kind of a BugReport (bug_create source_type).",
            "values": _vals(BugSourceType),
        },
        "bug_impact_target_types": {
            "purpose": "The target kind of a BugImpact record (bug_impact_add target_type).",
            "values": _vals(BugImpactTargetType),
        },
    }


def visibility_modes_reference() -> dict[str, Any]:
    """Runtime comment visibility modes and the prompt contexts each reaches."""
    return {
        "purpose": (
            "A RuntimeComment's visibility mode governs which prompt contexts it "
            "may enter. may_reach_context(visibility, context_kind) is the single "
            "predicate; audit_only reaches nothing, public_summary reaches all."
        ),
        "visibility_modes": _vals(CommentVisibility),
        "prompt_context_kinds": _vals(PromptContextKind),
        "reaches": {
            visibility.value: sorted(VISIBILITY_CONTEXT_MAP[visibility.value])
            for visibility in CommentVisibility
        },
    }


def queue_polling_guide() -> dict[str, Any]:
    """How to poll queue-bound commands (correct for mcp-proxy-adapter >=8.10.20)."""
    queued = sorted(name for name in INVENTORY if name in _QUEUED_COMMANDS)
    return {
        "purpose": (
            "Some commands run on the queuemgr job queue (use_queue=True) and "
            "return an enqueue acknowledgement instead of an inline result. This "
            "guide names the correct poll command and the two-store pitfall."
        ),
        "adapter_floor": ">=8.10.20",
        "queued_commands": queued,
        "enqueue_acknowledgement": {
            "job_id": "The queuemgr job id to poll.",
            "store": "Always 'queuemgr' for plan_manager queued commands.",
            "poll_with": "Always 'queue_get_job_status' for plan_manager queued commands.",
        },
        "poll_command": "queue_get_job_status",
        "poll_response_fields": [
            "job_id", "status", "progress", "description", "result", "error",
            "created_at", "started_at", "completed_at",
        ],
        "two_store_warning": (
            "Do NOT poll with the builtin job_status: it reads a separate "
            "in-memory JobManager store, not the queuemgr store. For a queuemgr "
            "job it returns {exists: false, store: 'job_manager', poll_with: "
            "'queue_get_job_status'}. Follow the poll_with field: use "
            "queue_get_job_status."
        ),
        "unknown_param_note": (
            "Adapter >=8.10.20 rejects unknown parameters (additionalProperties "
            "defaults to false); a misspelled parameter is an error, not silently "
            "ignored."
        ),
    }


def crud_matrix() -> dict[str, Any]:
    """Create/Read/Update/Delete reality per entity, including documented immutability."""
    return {
        "purpose": (
            "The actual create/read/update/delete surface per entity. Several "
            "entities are immutable-by-design or lack a delete/update command; "
            "this states each explicitly so callers do not assume a missing verb."
        ),
        "entities": {
            "plan": {"create": "plan_create", "read": "plan_list/plan_status", "update": "none (plan.status is fixed at 'draft'; the frozen state is derived from step statuses)", "delete": "plan_delete (soft, hidden-but-preserved; or hard, irreversible cascade)"},
            "step": {"create": "step_create", "read": "step_get/step_tree", "update": "step_update/step_move; status via step_set_status/step_transition", "delete": "step_delete (also purges the step's step_runtime row via ON DELETE CASCADE)"},
            "concept": {"create": "concept_add", "read": "concept_get/concept_list", "update": "concept_update (concept_id is immutable; no rename)", "delete": "concept_remove (does not clean up relations referencing it; dangling relation endpoints are possible)"},
            "relation": {"create": "relation_add", "read": "relation_list", "update": "none (no relation_update; remove + add to change a type or endpoint)", "delete": "relation_remove"},
            "paragraph": {"create": "via hrs_import", "read": "para_list/para_get", "update": "para_label_assign/para_mark_non_binding (direction=wrap)", "delete": "none exposed; para_mark_non_binding direction=unwrap is currently non-functional"},
            "todo": {"create": "todo_create", "read": "todo_get/todo_list", "update": "todo_update (not status); todo_resolve/todo_close for terminal status", "delete": "none (TODOs have no delete command; terminate via resolve/close)"},
            "todo_link": {"create": "todo_link_add", "read": "via todo_get", "update": "none", "delete": "todo_link_remove (soft, idempotent)"},
            "comment": {"create": "comment_add", "read": "comment_get/comment_list", "update": "none (comments are immutable; comment_supersede appends a new record; comment_resolve toggles resolved)", "delete": "none exposed"},
            "model_binding": {"create": "model_binding_set (create-only; not an upsert)", "read": "model_binding_get/model_binding_list/model_binding_resolve", "update": "none (no model_binding_update; remove + set to change a binding, which mints a new binding_uuid)", "delete": "model_binding_remove (soft)"},
            "execution_attempt": {"create": "execution_attempt_create", "read": "execution_attempt_get/execution_attempt_list", "update": "execution_attempt_report (append/patch outcome fields)", "delete": "none (append-only history)"},
            "review_result": {"create": "review_result_create", "read": "review_result_get/review_result_list", "update": "none (immutable verdict)", "delete": "none"},
            "escalation": {"create": "escalation_create", "read": "none exposed (no escalation_get/escalation_list; capture the escalation_uuid from escalation_create or a review_result)", "update": "escalation_resolve (open->resolved)", "delete": "none"},
            "bug": {"create": "bug_create", "read": "bug_get/bug_list", "update": "bug_update (non-lifecycle fields); status via bug_confirm/bug_reject/bug_mark_duplicate/bug_reopen/bug_close", "delete": "none (reject/mark_duplicate/reopen preserve history)"},
            "bug_impact": {"create": "bug_impact_add/bug_impact_discover", "read": "bug_impact_list", "update": "bug_impact_update", "delete": "none"},
            "bug_fix": {"create": "bug_fix_create", "read": "bug_fix_list", "update": "bug_fix_update/bug_fix_verify", "delete": "none"},
            "bug_fix_propagation": {"create": "bug_propagation_create", "read": "bug_propagation_list", "update": "bug_propagation_update", "delete": "none"},
            "project_dependency": {"create": "project_dependency_add/project_dependency_discover", "read": "project_dependency_list/project_dependents", "update": "none (no project_dependency_update; a discovered edge can never be confirmed — no confirm command)", "delete": "project_dependency_remove (soft)"},
        },
    }


# Category index of the whole command surface. Every INVENTORY command appears
# in exactly one bucket; test_info_agent_reference guards this against drift.
_COMMAND_CATEGORIES: dict[str, list[str]] = {
    "plan_core": [
        "plan_create", "plan_list", "plan_status", "plan_delete",
        "plan_export", "plan_snapshot", "plan_import", "plan_validate", "plan_score",
    ],
    "project_binding": [
        "plan_project_attach", "plan_project_detach", "plan_project_list",
        "plan_project_set_primary", "plan_project_clear_primary",
    ],
    "transfer": ["export_upload_save", "hrs_import", "hrs_export"],
    "paragraph": ["para_list", "para_get", "para_label_assign", "para_mark_non_binding"],
    "concept_relation": [
        "concept_get", "concept_list", "concept_add", "concept_update", "concept_remove",
        "relation_list", "relation_add", "relation_remove", "concept_coverage",
    ],
    "step": [
        "step_get", "step_tree", "step_create", "step_update", "step_move",
        "step_delete", "step_set_status", "step_transition",
        "step_runtime_get", "step_runtime_report", "step_runtime_list",
    ],
    "graph": ["graph_deps", "graph_order", "graph_parallel_map", "graph_impact"],
    "step_dependency": [
        "step_dependency_list", "step_dependency_add", "step_dependency_remove",
        "step_dependency_set", "step_dependency_clear", "step_dependency_preview",
        "step_dependency_apply",
    ],
    "context_prompt": [
        "branch_prompt", "plan_prompt_chain", "context_compile", "context_common",
        "context_specific", "context_bundle", "block_get", "block_list",
        "branch_dump", "branch_weak",
    ],
    "cascade": ["cascade_begin", "cascade_preview", "cascade_commit", "cascade_abort"],
    "srt": ["srt_snapshot_create", "srt_snapshot_list", "srt_diff"],
    "system": ["info"],
    "todo": [
        "todo_create", "todo_get", "todo_list", "todo_update", "todo_resolve",
        "todo_close", "todo_link_add", "todo_link_remove", "todo_queue",
        "todo_promote_to_cascade_request",
    ],
    "comment": ["comment_add", "comment_get", "comment_list", "comment_supersede", "comment_resolve"],
    "model_binding": [
        "model_binding_set", "model_binding_get", "model_binding_list",
        "model_binding_remove", "model_binding_resolve",
    ],
    "execution_attempt": [
        "execution_attempt_create", "execution_attempt_report",
        "execution_attempt_get", "execution_attempt_list",
    ],
    "review_escalation": [
        "review_result_create", "review_result_get", "review_result_list",
        "escalation_create", "escalation_resolve",
    ],
    "bug": [
        "bug_create", "bug_get", "bug_list", "bug_update", "bug_confirm",
        "bug_reject", "bug_mark_duplicate", "bug_reopen", "bug_close",
    ],
    "bug_impact": ["bug_impact_add", "bug_impact_update", "bug_impact_list", "bug_impact_discover"],
    "bug_fix": ["bug_fix_create", "bug_fix_update", "bug_fix_list", "bug_fix_verify"],
    "bug_propagation": [
        "bug_propagation_create", "bug_propagation_list",
        "bug_propagation_update", "bug_propagation_generate_todos",
    ],
    "project_dependency": [
        "project_dependency_add", "project_dependency_remove",
        "project_dependency_list", "project_dependency_discover", "project_dependents",
    ],
}

# The queue-bound commands (use_queue=True); consumed by queue_polling_guide().
_QUEUED_COMMANDS: frozenset[str] = frozenset({
    "plan_export", "plan_snapshot", "plan_import", "hrs_import",
    "plan_prompt_chain", "branch_weak", "plan_validate", "plan_score",
    "step_transition",
})


def command_index() -> dict[str, Any]:
    """A category index of the entire command surface, with mutation flags."""
    return {
        "purpose": "Every command grouped by category, with a mutates flag drawn from the normative MUTATING set (authoring-truth mutations).",
        "total_commands": len(INVENTORY),
        "categories": {
            category: [
                {"name": name, "mutates_plan_truth": name in MUTATING}
                for name in names
            ]
            for category, names in _COMMAND_CATEGORIES.items()
        },
    }


def agent_reference() -> dict[str, Any]:
    """The full exhaustive agent-reference section returned by info."""
    return {
        "status_vocabularies": status_vocabularies(),
        "lifecycle_matrices": lifecycle_matrices(),
        "operational_checklists": operational_checklists(),
        "anchor_types": anchor_type_tables(),
        "visibility_modes": visibility_modes_reference(),
        "queue_polling": queue_polling_guide(),
        "crud_matrix": crud_matrix(),
        "command_index": command_index(),
    }
