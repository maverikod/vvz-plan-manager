"""Shared todo-status legal-transition guard for the todo update path (C-009, C-029).

The todo store's transition helpers stamp status changes mechanically and enforce no legality of
their own. This module is the command-layer guard for the todo_update status path, mirroring the
shape of plan_manager.domain.bug_status_transitions: a legal-transition table keyed by current
status, a legality predicate, a legal-targets lookup, and a typed error carrying current_status and
legal_targets.

Only in_progress, blocked, and cancelled are reachable through this guard (TODO_UPDATABLE_STATUSES).
resolved and closed remain reachable only via the separate unconditional todo_resolve/todo_close
commands; open is only the initial todo_create status and is never a todo_update target. The status
value 'ready' has been REMOVED from the todo status vocabulary (plan_manager.domain.todo.TodoStatus)
and does not appear anywhere in this module.
"""
from __future__ import annotations

from plan_manager.domain.runtime_validation import RuntimeValidationError

# The only statuses settable through the todo_update status path (C-009).
TODO_UPDATABLE_STATUSES: frozenset[str] = frozenset({"in_progress", "blocked", "cancelled"})

# Legal transition targets reachable from each current todo status via todo_update.
# resolved/closed/cancelled are terminal for this guard: todo_update can never leave them.
TODO_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "blocked", "cancelled"}),
    "in_progress": frozenset({"blocked", "cancelled"}),
    "blocked": frozenset({"in_progress", "cancelled"}),
    "resolved": frozenset(),
    "closed": frozenset(),
    "cancelled": frozenset(),
}

class TodoStatusTransitionError(RuntimeValidationError):
    """A todo_update status change was requested from a status that cannot legally reach it (C-009).

    Carries the current status and the sorted legal_targets reachable from it so the command
    surface can report INVALID_RUNTIME_STATUS_TRANSITION with an actionable payload.
    """

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        self.legal_targets = legal_todo_targets(current_status)
        super().__init__(
            f"illegal todo status transition: todo_update(status={requested_status!r}) is not "
            f"legal from status {current_status!r}; legal targets from here: {self.legal_targets}"
        )

def is_legal_todo_transition(current_status: str, requested_status: str) -> bool:
    """Return whether moving from ``current_status`` to ``requested_status`` is legal via todo_update."""
    return requested_status in TODO_LEGAL_TRANSITIONS.get(current_status, frozenset())

def legal_todo_targets(current_status: str) -> list[str]:
    """Return the sorted statuses reachable from ``current_status`` via todo_update."""
    return sorted(TODO_LEGAL_TRANSITIONS.get(current_status, frozenset()))

def guard_todo_transition(current_status: str, requested_status: str) -> None:
    """Raise TodoStatusTransitionError when the requested todo_update status change is illegal.

    Args:
        current_status: The todo's current status.
        requested_status: The status value requested via todo_update's status parameter.

    Raises:
        TodoStatusTransitionError: When the transition is not legal from the current status.
    """
    if not is_legal_todo_transition(current_status, requested_status):
        raise TodoStatusTransitionError(current_status, requested_status)
