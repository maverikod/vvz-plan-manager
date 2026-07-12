"""Model binding inheritance: the six-level specificity order that selects the effective binding (C-010)."""

from __future__ import annotations
from plan_manager.domain.runtime_validation import RuntimeValidationError


INHERITANCE_ORDER: tuple[str, ...] = ("system", "plan", "level", "branch", "step", "role")

SCOPE_RANK: dict[str, int] = {name: i for i, name in enumerate(INHERITANCE_ORDER)}


def scope_rank(scope: str) -> int:
    """Return the rank (specificity level) of the given scope.

    Args:
        scope: The scope name to look up.

    Returns:
        The integer rank of the scope (0 for least specific, 5 for most specific).

    Raises:
        RuntimeValidationError: If scope is not a valid scope name.
    """
    if scope not in SCOPE_RANK:
        raise RuntimeValidationError(f"Invalid scope '{scope}': must be one of {INHERITANCE_ORDER}")
    return SCOPE_RANK[scope]


def is_more_specific(scope_a: str, scope_b: str) -> bool:
    """Check whether scope_a is more specific than scope_b.

    Args:
        scope_a: The first scope to compare.
        scope_b: The second scope to compare.

    Returns:
        True if scope_a is more specific (has a higher rank) than scope_b.

    Raises:
        RuntimeValidationError: If either scope is invalid.
    """
    return scope_rank(scope_a) > scope_rank(scope_b)


def order_by_specificity(scopes: list[str]) -> list[str]:
    """Return a new list of scopes sorted by specificity (least to most specific).

    Args:
        scopes: A list of scope names to sort.

    Returns:
        A new list containing the same scopes sorted in ascending order of specificity.

    Raises:
        RuntimeValidationError: If any scope in the input is invalid.
    """
    # Validate all scopes first by calling scope_rank on each
    for scope in scopes:
        scope_rank(scope)
    # Return sorted copy (least specific first, most specific last)
    return sorted(scopes, key=scope_rank)


def most_specific(scopes: list[str]) -> str:
    """Return the single scope with the highest specificity from the input list.

    Args:
        scopes: A list of scope names.

    Returns:
        The scope name with the highest rank (most specific).

    Raises:
        RuntimeValidationError: If scopes is empty or if any scope is invalid.
    """
    if not scopes:
        raise RuntimeValidationError("Cannot determine most_specific scope: input list is empty")
    # Validate all scopes and find the one with max rank
    return max(scopes, key=scope_rank)
