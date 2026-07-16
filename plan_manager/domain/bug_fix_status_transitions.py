"""Shared bug-fix-status legal-transition guard for the bug fix update/verify path (C-009, C-024).

Mirrors plan_manager.domain.bug_status_transitions: a legal-transition table keyed by current
status, a legality predicate, a legal-targets lookup, and a typed error carrying current_status and
legal_targets. Extends the shared guard pattern to bug-fix status transitions, which previously
accepted any BugFixStatus value with no source-status legality check.

The initial status at bug_fix_create is unguarded (any of the eight BugFixStatus values may be
supplied at creation, mirroring bug_create). This guard applies only to status changes requested
through bug_fix_update's status parameter and to the implicit verified/failed target of
bug_fix_verify.
"""
from __future__ import annotations

from plan_manager.domain.runtime_validation import RuntimeValidationError

# Legal transition targets reachable from each current BugFix status.
FIX_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"in_progress", "rejected"}),
    "in_progress": frozenset({"implemented", "failed", "partial", "rejected"}),
    "implemented": frozenset({"verified", "failed"}),
    "partial": frozenset({"in_progress", "implemented", "failed"}),
    "failed": frozenset({"in_progress", "reverted"}),
    "rejected": frozenset(),
    "verified": frozenset(),
    "reverted": frozenset(),
}

class BugFixStatusTransitionError(RuntimeValidationError):
    """A bug-fix status change was requested from a status that cannot legally reach it (C-009).

    Carries the current status and the sorted legal_targets reachable from it so the command
    surface can report INVALID_RUNTIME_STATUS_TRANSITION with an actionable payload.
    """

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        self.legal_targets = legal_fix_targets(current_status)
        super().__init__(
            f"illegal bug fix status transition: {requested_status!r} is not legal from "
            f"status {current_status!r}; legal targets from here: {self.legal_targets}"
        )

def is_legal_fix_transition(current_status: str, requested_status: str) -> bool:
    """Return whether moving from ``current_status`` to ``requested_status`` is a legal BugFix transition."""
    return requested_status in FIX_LEGAL_TRANSITIONS.get(current_status, frozenset())

def legal_fix_targets(current_status: str) -> list[str]:
    """Return the sorted BugFix statuses reachable from ``current_status``."""
    return sorted(FIX_LEGAL_TRANSITIONS.get(current_status, frozenset()))

def guard_fix_transition(current_status: str, requested_status: str) -> None:
    """Raise BugFixStatusTransitionError when the requested BugFix status change is illegal.

    Args:
        current_status: The bug fix's current status.
        requested_status: The status value requested (via bug_fix_update's status parameter, or
            the implicit verified/failed target of bug_fix_verify).

    Raises:
        BugFixStatusTransitionError: When the transition is not legal from the current status.
    """
    if not is_legal_fix_transition(current_status, requested_status):
        raise BugFixStatusTransitionError(current_status, requested_status)
