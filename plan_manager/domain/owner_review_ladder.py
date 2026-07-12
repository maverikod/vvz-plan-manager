"""Owner review ladder: each level owner verifies its direct subordinate; no self-certification; escalate up (C-017)."""
from __future__ import annotations

from plan_manager.domain.runtime_validation import RuntimeValidationError

# Ownership levels, most-senior first ({sz0j}). The code executor is a distinct producer of the
# "as_execution" result but is NOT an ownership level (it never certifies itself).
LADDER_LEVELS: tuple[str, ...] = ("hrs_mrs", "gs", "ts", "as")

# {sz0j}: HRS/MRS owner verifies GS; GS owner verifies TS; TS owner verifies AS AND the result of AS
# execution. Maps a produced artifact/result level -> the owner level that verifies it.
VERIFICATION_MAP: dict[str, str] = {"gs": "hrs_mrs", "ts": "gs", "as": "ts", "as_execution": "ts"}

# The producer (author/executor) of each produced level. "as_execution" is produced by the code executor.
PRODUCER_MAP: dict[str, str] = {"gs": "gs", "ts": "ts", "as": "as", "as_execution": "code_execution"}


def verifier_of(produced_level: str) -> str:
    """Return the verifier (owner level) for the given produced level."""
    if produced_level not in VERIFICATION_MAP:
        raise RuntimeValidationError(
            f"Unknown produced level: {produced_level}. "
            f"Valid levels are: {', '.join(VERIFICATION_MAP.keys())}"
        )
    return VERIFICATION_MAP[produced_level]


def producer_of(produced_level: str) -> str:
    """Return the producer for the given produced level."""
    if produced_level not in PRODUCER_MAP:
        raise RuntimeValidationError(
            f"Unknown produced level: {produced_level}. "
            f"Valid levels are: {', '.join(PRODUCER_MAP.keys())}"
        )
    return PRODUCER_MAP[produced_level]


def subordinate_levels(owner_level: str) -> tuple[str, ...]:
    """Return a tuple of all produced levels that this owner verifies."""
    if owner_level not in LADDER_LEVELS:
        raise RuntimeValidationError(
            f"Unknown owner level: {owner_level}. "
            f"Valid levels are: {', '.join(LADDER_LEVELS)}"
        )
    # Find all produced_level keys where VERIFICATION_MAP[produced_level] == owner_level
    result = tuple(
        produced_level
        for produced_level in VERIFICATION_MAP.keys()
        if VERIFICATION_MAP[produced_level] == owner_level
    )
    return result


def escalation_target(owner_level: str) -> str | None:
    """Return the next level up (more senior) in LADDER_LEVELS, or None if already at top."""
    if owner_level not in LADDER_LEVELS:
        raise RuntimeValidationError(
            f"Unknown owner level: {owner_level}. "
            f"Valid levels are: {', '.join(LADDER_LEVELS)}"
        )
    # Find the index of this level
    index = LADDER_LEVELS.index(owner_level)
    # If index is 0 (most senior), return None
    if index == 0:
        return None
    # Otherwise return the level at index - 1
    return LADDER_LEVELS[index - 1]


def is_self_certification(reviewer_level: str, produced_level: str) -> bool:
    """Return True if the reviewer is the producer of the produced level."""
    return producer_of(produced_level) == reviewer_level


def guard_no_self_certification(reviewer_level: str, produced_level: str) -> None:
    """Raise RuntimeValidationError if reviewer is certifying their own work."""
    if is_self_certification(reviewer_level, produced_level):
        raise RuntimeValidationError(
            f"Self-certification forbidden: {reviewer_level} cannot verify {produced_level} "
            f"(produced by {producer_of(produced_level)})"
        )


def guard_valid_reviewer(reviewer_level: str, produced_level: str) -> None:
    """Raise RuntimeValidationError if reviewer is not the correct verifier."""
    expected_verifier = verifier_of(produced_level)
    if reviewer_level != expected_verifier:
        raise RuntimeValidationError(
            f"Invalid reviewer: {reviewer_level} cannot verify {produced_level}. "
            f"Expected verifier: {expected_verifier}"
        )
