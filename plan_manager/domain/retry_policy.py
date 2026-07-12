"""Retry policy: bounded attempts before escalation; unbounded automatic retries forbidden (C-019)."""
from __future__ import annotations
from dataclasses import dataclass

from plan_manager.domain.runtime_validation import RuntimeValidationError

DEFAULT_MAX_RETRIES: int = 1   # {aub0}: one initial attempt + one retry at the same level, then escalate
RETRY_LIMIT_MIN: int = 0       # 0 retries = a single attempt, then escalate on failure
RETRY_LIMIT_MAX: int = 10      # a finite configurable ceiling; unbounded automatic retries are forbidden ({4af2})

@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    should_escalate: bool
    next_attempt_number: int | None   # 1-based number of the next attempt when should_retry, else None
    reason: str


def validate_max_retries(value: int) -> int:
    """Validate that max_retries is within the configured bounds.

    Args:
        value: The maximum number of retries to validate.

    Returns:
        The value if valid.

    Raises:
        RuntimeValidationError: If value is outside [RETRY_LIMIT_MIN, RETRY_LIMIT_MAX].
    """
    if not (RETRY_LIMIT_MIN <= value <= RETRY_LIMIT_MAX):
        raise RuntimeValidationError(
            f"max_retries must be between {RETRY_LIMIT_MIN} and {RETRY_LIMIT_MAX}, got {value}"
        )
    return value


def decide_retry(
    *,
    attempts_made: int,
    max_retries: int,
    last_attempt_failed: bool,
) -> RetryDecision:
    """Decide whether to retry, escalate, or stop.

    Args:
        attempts_made: Number of attempts completed so far.
        max_retries: Maximum number of retries allowed (must be validated).
        last_attempt_failed: Whether the last attempt failed.

    Returns:
        A RetryDecision indicating the next action.

    Raises:
        RuntimeValidationError: If max_retries is out of bounds.
    """
    validate_max_retries(max_retries)
    total_allowed_attempts = 1 + max_retries

    if not last_attempt_failed:
        return RetryDecision(
            should_retry=False,
            should_escalate=False,
            next_attempt_number=None,
            reason="last attempt did not fail; no retry needed",
        )
    elif attempts_made < total_allowed_attempts:
        return RetryDecision(
            should_retry=True,
            should_escalate=False,
            next_attempt_number=attempts_made + 1,
            reason="retry within configured limit",
        )
    else:
        return RetryDecision(
            should_retry=False,
            should_escalate=True,
            next_attempt_number=None,
            reason="retry limit exhausted; escalate",
        )
