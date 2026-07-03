"""Lifecycle state machine for plan artifacts with enforced legal
transitions (C-007 StatusModel)."""

from __future__ import annotations


class StatusTransitionError(ValueError):
    """Raised when a requested status transition is not legal."""


STATUSES: frozenset[str] = frozenset(
    {"draft", "ready_for_review", "frozen", "needs_review"}
)
"""Statuses legal for all plan artifacts (levels 2-5)."""

ATOMIC_ONLY_STATUSES: frozenset[str] = frozenset({"in_progress", "done"})
"""Additional statuses legal only for atomic steps (level 5)."""

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"ready_for_review"}),
    "ready_for_review": frozenset({"frozen", "draft"}),
    "frozen": frozenset(),
    "needs_review": frozenset({"draft", "frozen"}),
    "in_progress": frozenset({"done"}),
    "done": frozenset(),
}
"""Legal direct transitions per current status. The needs_review target is
deliberately excluded from every value here: needs_review is reachable
only via cascade propagation, never as a direct transition target, and
that rule is enforced separately (not via this table). For atomic steps
only, "frozen" additionally allows a direct transition to "in_progress";
that extra rule is also enforced separately (not encoded in this table),
since this table is shared by both atomic and non-atomic artifacts."""


def validate_transition(
    current: str, new: str, is_atomic_step: bool, via_cascade: bool
) -> None:
    """Validate a requested status transition against the StatusModel.

    Args:
        current: The artifact's current status string.
        new: The requested new status string.
        is_atomic_step: True if the artifact is an atomic step (level 5),
            which additionally allows the atomic-only statuses
            "in_progress" and "done" to be known statuses, and
            additionally allows the direct transition "frozen" ->
            "in_progress".
        via_cascade: True if this transition is being applied as part of
            cascade propagation (invalidation), False if it is a direct
            request.

    Returns:
        None. Returns normally (no exception) when the transition is
        legal.

    Raises:
        StatusTransitionError: raised if any of the following hold, in
            this order of evaluation:
            1. current is not a known status for the artifact kind: known
               statuses are the members of STATUSES, plus the members of
               ATOMIC_ONLY_STATUSES when is_atomic_step is True (when
               is_atomic_step is False, members of ATOMIC_ONLY_STATUSES
               are not known statuses).
            2. new is not a known status for the artifact kind (same rule
               as for current, evaluated after current passes).
            3. new == "needs_review" and via_cascade is False. When
               new == "needs_review" and via_cascade is True, the
               transition is legal regardless of current, and the
               function returns normally at this point without further
               checks.
            4. new != "needs_review" and new is not a member of the
               legal target set for current, where the legal target set
               is LEGAL_TRANSITIONS[current], except that when
               is_atomic_step is True and current == "frozen" the legal
               target set is LEGAL_TRANSITIONS["frozen"] union
               {"in_progress"} instead. The via_cascade flag has no
               effect on this check: it does not add any legal target
               other than "needs_review".
    """
    known_statuses = set(STATUSES)
    if is_atomic_step:
        known_statuses |= set(ATOMIC_ONLY_STATUSES)

    if current not in known_statuses:
        raise StatusTransitionError(
            f"Unknown current status {current!r} for "
            f"{'atomic step' if is_atomic_step else 'artifact'}"
        )
    if new not in known_statuses:
        raise StatusTransitionError(
            f"Unknown new status {new!r} for "
            f"{'atomic step' if is_atomic_step else 'artifact'}"
        )

    if new == "needs_review":
        if via_cascade:
            return
        raise StatusTransitionError(
            "needs_review is only reachable via cascade propagation"
        )

    legal_targets = LEGAL_TRANSITIONS[current]
    if is_atomic_step and current == "frozen":
        legal_targets = legal_targets | frozenset({"in_progress"})

    if new not in legal_targets:
        raise StatusTransitionError(f"Illegal transition from {current!r} to {new!r}")
