"""Shared metadata builder for wish commands."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata


WISH_ERROR_CASES: dict[str, dict[str, str]] = {
    "WISH_NOT_FOUND": {
        "description": "The supplied wish identifier does not resolve to a live wish item.",
        "message": "wish not found: {wish}",
        "solution": "Call wish_list to discover live wish identifiers.",
    },
}


def wish_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    *,
    include_not_found: bool = False,
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build standard metadata for a wish command."""
    merged = dict(WISH_ERROR_CASES) if include_not_found else {}
    if error_cases:
        merged.update(error_cases)
    return runtime_metadata(
        cls,
        parameters,
        return_value,
        examples,
        error_cases=merged,
        best_practices=best_practices,
    )
