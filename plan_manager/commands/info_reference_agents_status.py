"""Status vocabularies and lifecycle transition matrices for the info agent reference.

Split out of info_reference_agents.py for file-size discipline (CR-1 C-014).
Vocabularies are derived directly from the domain enum classes so this
reference can never silently drift from the values the commands actually
enforce.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from plan_manager.domain.bug_fix import BugFixStatus, BugFixType
from plan_manager.domain.bug_fix_propagation import PropagationAction, PropagationStatus
from plan_manager.domain.bug_impact import (
    BugImpactStatus,
    BugImpactTargetType,
    BugImpactType,
)
from plan_manager.domain.bug_report import BugKind, BugSeverity, BugStatus
from plan_manager.domain.escalation import EscalationStatus
from plan_manager.domain.execution_attempt import (
    TERMINAL_ATTEMPT_STATUSES,
    ExecutionAttemptStatus,
)
from plan_manager.domain.model_binding import BindingScope
from plan_manager.domain.review_result import ReviewObjectType, ReviewStatus
from plan_manager.domain.runtime_comment import CommentKind
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
                "commands": ["escalation_create", "escalation_resolve", "escalation_get", "escalation_list"],
                "notes": "open at creation; escalation_resolve is the only transition (open->resolved). escalation_get/escalation_list are read-only.",
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
                "commands": ["project_dependency_add", "project_dependency_discover", "project_dependency_update", "project_dependency_confirm"],
                "notes": "confidence is not a lifecycle status; project_dependency_update adjusts a dependency edge's fields and project_dependency_confirm raises a discovered edge's confidence to confirmed.",
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
                "cascade_begin refuses a fully frozen plan (FROZEN_TRUTH_WRITE); plan_unfreeze is the only door out of full freeze — it writes an audit record and opens a cascade under which scoped step_transition frozen->draft may then run.",
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
                "bug_confirm": "-> confirmed (legal only from reported/triaged; idempotent from confirmed)",
                "bug_reject": "-> rejected (legal from any non-terminal status)",
                "bug_mark_duplicate": "-> duplicate (legal from any non-terminal status)",
                "bug_reopen": "-> reopened (legal only from a terminal status: closed/rejected/duplicate)",
                "bug_close": "-> closed (legal from any non-terminal status AND refused unless BugClosureDiscipline is satisfied)",
            },
            "terminal_guard": {
                "terminal_statuses": ["closed", "rejected", "duplicate"],
                "rule": (
                    "closed/rejected/duplicate are terminal and may be left ONLY via bug_reopen. "
                    "Every other bug transition command applied to a terminal status, and bug_confirm "
                    "applied from any status other than reported/triaged/confirmed, is refused with "
                    "INVALID_RUNTIME_STATUS_TRANSITION carrying current_status and the reachable legal_targets."
                ),
                "enforced_by": "plan_manager.domain.bug_status_transitions.guard_bug_transition (command layer)",
            },
            "unreachable_post_creation": ["triaged", "fixing", "fixed_source", "propagating", "verified"],
            "notes": [
                "The store's set_bug_status enforces no legality check and stamps confirmed_at/closed_at/reopened_at mechanically; the shared command-layer terminal_guard is what refuses illegal transitions.",
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
        "project_dependency": {
            "enforced": False,
            "command_transitions": {
                "project_dependency_confirm": "-> confirmed (unconditional; legal from any confidence value, idempotent from confirmed)",
            },
            "unreachable_post_creation": ["unconfirmed", "suspected"],
            "notes": [
                "confidence is not a step-style lifecycle status; project_dependency_add sets the initial confidence (default unconfirmed), guarded by guard_discovery_not_silently_confirmed: confidence=confirmed at creation is refused unless discovery_source=manual.",
                "project_dependency_confirm is the only post-creation transition and always sets confidence to confirmed regardless of the current value; there is no command that demotes confidence back to unconfirmed or suspected once set.",
                "project_dependency_update never touches confidence; it patches dependency_type, version_constraint, and active only.",
            ],
        },
        "review_result": {
            "enforced": False,
            "notes": [
                "review_result has no transition matrix because it has no transitions at all: review_result_create is the only write command, and no update or status-changing command is exposed.",
                "status is recorded once as the reviewer's verdict (accepted/rejected/changes_requested/escalated/needs_owner_decision) and never advances afterward; a corrected verdict is filed as a new ReviewResult, not an update to the existing one.",
            ],
        },
    }
