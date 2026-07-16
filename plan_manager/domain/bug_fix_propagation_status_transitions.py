"""Shared propagation-status legal-transition guard for the bug propagation update path (C-009, C-025).

Mirrors plan_manager.domain.bug_status_transitions: a legal-transition table keyed by current
status, a legality predicate, a legal-targets lookup, and a typed error carrying current_status and
legal_targets. Extends the shared guard pattern to bug-fix-propagation status transitions, which
previously accepted any PropagationStatus value with no source-status legality check.

The initial status at bug_propagation_create is unguarded (pending or ready may be supplied at
creation). This guard applies only to status changes requested through bug_propagation_update's
status parameter.
"""
from __future__ import annotations

from plan_manager.domain.runtime_validation import RuntimeValidationError

# Legal transition targets reachable from each current PropagationStatus.
PROPAGATION_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"ready", "in_progress", "blocked", "skipped"}),
    "ready": frozenset({"in_progress", "blocked", "skipped"}),
    "in_progress": frozenset({"done", "failed", "blocked"}),
    "blocked": frozenset({"pending", "ready", "in_progress", "skipped"}),
    "failed": frozenset({"in_progress", "skipped"}),
    "done": frozenset({"verified"}),
    "skipped": frozenset(),
    "verified": frozenset(),
}

class BugFixPropagationStatusTransitionError(RuntimeValidationError):
    """A propagation status change was requested from a status that cannot legally reach it (C-009).

    Carries the current status and the sorted legal_targets reachable from it so the command
    surface can report INVALID_RUNTIME_STATUS_TRANSITION with an actionable payload.
    """

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        self.legal_targets = legal_propagation_targets(current_status)
        super().__init__(
            f"illegal bug fix propagation status transition: {requested_status!r} is not legal "
            f"from status {current_status!r}; legal targets from here: {self.legal_targets}"
        )

def is_legal_propagation_transition(current_status: str, requested_status: str) -> bool:
    """Return whether moving from ``current_status`` to ``requested_status`` is a legal PropagationStatus transition."""
    return requested_status in PROPAGATION_LEGAL_TRANSITIONS.get(current_status, frozenset())

def legal_propagation_targets(current_status: str) -> list[str]:
    """Return the sorted PropagationStatus values reachable from ``current_status``."""
    return sorted(PROPAGATION_LEGAL_TRANSITIONS.get(current_status, frozenset()))

def guard_propagation_transition(current_status: str, requested_status: str) -> None:
    """Raise BugFixPropagationStatusTransitionError when the requested status change is illegal.

    Args:
        current_status: The propagation's current status.
        requested_status: The status value requested via bug_propagation_update's status parameter.

    Raises:
        BugFixPropagationStatusTransitionError: When the transition is not legal from the current status.
    """
    if not is_legal_propagation_transition(current_status, requested_status):
        raise BugFixPropagationStatusTransitionError(current_status, requested_status)
