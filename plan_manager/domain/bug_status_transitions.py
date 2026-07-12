"""Shared bug-status legal-transition guard for the bug lifecycle command group (C-020, C-026).

The bug store (set_bug_status/mark_bug_duplicate) stamps status changes mechanically and
enforces no legality of its own. This module is the single command-layer guard that all bug
transition commands share so the terminal statuses cannot be left except by re-discovery:

  * closed / rejected / duplicate are TERMINAL and may be left ONLY via bug_reopen;
  * bug_confirm is legal only from reported or triaged (idempotent from confirmed);
  * every refusal names the statuses actually reachable from the current status (legal_targets)
    so the caller can pick a legal command.

The full status vocabulary (fixing/fixed_source/propagating/verified/triaged) remains reachable
only as an initial bug_create status; no command advances a bug into those post-creation, so they
are not transition targets here.
"""
from __future__ import annotations

from plan_manager.domain.bug_report import BUG_STATUSES
from plan_manager.domain.runtime_validation import RuntimeValidationError

# Terminal bug statuses: a bug in one of these is left only by bug_reopen.
TERMINAL_STATUSES: frozenset[str] = frozenset({"closed", "rejected", "duplicate"})

# The single status each bug transition command drives the bug to.
COMMAND_TARGET: dict[str, str] = {
    "bug_confirm": "confirmed",
    "bug_reject": "rejected",
    "bug_close": "closed",
    "bug_mark_duplicate": "duplicate",
    "bug_reopen": "reopened",
}

_NON_TERMINAL: frozenset[str] = frozenset(BUG_STATUSES) - TERMINAL_STATUSES

# The statuses from which each command is a legal transition.
#   * confirm: only from reported/triaged, plus idempotent re-confirm from confirmed.
#   * reject / close / mark_duplicate: from any non-terminal status (never re-entering a
#     terminal status from another terminal one).
#   * reopen: only from a terminal status (the sole legal exit from terminal).
LEGAL_SOURCES: dict[str, frozenset[str]] = {
    "bug_confirm": frozenset({"reported", "triaged", "confirmed"}),
    "bug_reject": _NON_TERMINAL,
    "bug_close": _NON_TERMINAL,
    "bug_mark_duplicate": _NON_TERMINAL,
    "bug_reopen": TERMINAL_STATUSES,
}


class BugStatusTransitionError(RuntimeValidationError):
    """A bug transition command was applied from a status it cannot legally leave (C-026).

    Carries the current status and the sorted legal_targets reachable from it so the command
    surface can report INVALID_RUNTIME_STATUS_TRANSITION with an actionable payload.
    """

    def __init__(self, command: str, current_status: str) -> None:
        self.command = command
        self.current_status = current_status
        self.legal_targets = legal_targets(current_status)
        target = COMMAND_TARGET.get(command, command)
        super().__init__(
            f"illegal bug status transition: {command} (-> {target}) is not legal from "
            f"status {current_status!r}; legal targets from here: {self.legal_targets}"
        )


def is_legal_transition(command: str, current_status: str) -> bool:
    """Return whether ``command`` is a legal transition from ``current_status``."""
    return current_status in LEGAL_SOURCES.get(command, frozenset())


def legal_targets(current_status: str) -> list[str]:
    """Return the sorted target statuses reachable from ``current_status`` by any bug command."""
    return sorted(
        {
            COMMAND_TARGET[command]
            for command, sources in LEGAL_SOURCES.items()
            if current_status in sources
        }
    )


def guard_bug_transition(command: str, current_status: str) -> None:
    """Raise BugStatusTransitionError when ``command`` is illegal from ``current_status``.

    Args:
        command: The bug transition command name (a key of COMMAND_TARGET).
        current_status: The bug's current status.

    Raises:
        BugStatusTransitionError: When the transition is not legal from the current status.
    """
    if not is_legal_transition(command, current_status):
        raise BugStatusTransitionError(command, current_status)
