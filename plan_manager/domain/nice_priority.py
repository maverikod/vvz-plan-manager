"""Nice-style runtime priority and tie-break ordering for runtime work (C-007)."""

from __future__ import annotations

from plan_manager.domain.runtime_validation import (
    validate_priority_nice, PRIORITY_NICE_MIN, PRIORITY_NICE_MAX,
)


def validate_nice_priority(value: int) -> int:
    """Validate a candidate nice priority value.

    Delegates to validate_priority_nice, which accepts an integer in the
    closed range PRIORITY_NICE_MIN..PRIORITY_NICE_MAX (-20 highest priority,
    0 normal, 19 background, following the Linux nice principle) and raises
    RuntimeValidationError for any out-of-range value.

    Args:
        value: Candidate nice priority to validate.

    Returns:
        The validated nice priority value, unchanged.

    Raises:
        RuntimeValidationError: If value lies outside -20..19.
    """
    return validate_priority_nice(value)


def tie_break_sort_key(
    *,
    priority_nice: int,
    has_blocker: bool,
    deps_ready: bool,
    age_seconds: float,
    due_at_epoch: float | None,
    kind_rank: int,
    execution_wave: int,
) -> tuple:
    """Build a pure in-memory ordering key for runtime work queue sorting.

    Ascending sort over the returned tuple yields correct runtime-queue
    order. This function never reads or alters the execution dependencies
    of the frozen plan; it governs only the runtime work queue.

    Tie-break order after priority_nice: presence of a blocker, readiness
    of dependencies, age of the record, due date, kind of work, and
    membership in the current execution wave.

    Note: kind_rank is an integer rank supplied by the caller (the runtime
    queue layer). This function does not import or hardcode the TodoKind
    vocabulary; that vocabulary is owned entirely by the caller.

    Args:
        priority_nice: Nice priority value, already validated by
            validate_nice_priority; -20 sorts first (highest), 19 sorts
            last (background).
        has_blocker: Whether the work item currently has a blocker present.
        deps_ready: Whether the work item's dependencies are ready.
        age_seconds: Age of the record in seconds; older records sort first.
        due_at_epoch: Due date as an epoch timestamp, or None when unset;
            earlier due dates sort first, and items with no due date sort
            last.
        kind_rank: Caller-supplied integer rank for the work item's kind of
            work; lower values sort first.
        execution_wave: Identifier of the current execution wave; earlier
            waves sort first.

    Returns:
        A 7-element tuple:
        (priority_nice, 1 if has_blocker else 0, 0 if deps_ready else 1,
         -age_seconds, due_at_epoch if due_at_epoch is not None else
         float("inf"), kind_rank, execution_wave)
    """
    return (
        priority_nice,
        1 if has_blocker else 0,
        0 if deps_ready else 1,
        -age_seconds,
        due_at_epoch if due_at_epoch is not None else float("inf"),
        kind_rank,
        execution_wave,
    )
