"""Shared metadata builder for calendar-entry commands."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata


CALENDAR_ENTRY_ERROR_CASES: dict[str, dict[str, str]] = {
    "CALENDAR_ENTRY_NOT_FOUND": {
        "description": "The supplied calendar entry identifier does not resolve to a live calendar entry.",
        "message": "calendar entry not found: {calendar_entry}",
        "solution": "Call calendar_entry_list to discover live calendar-entry identifiers.",
    },
}


def calendar_entry_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    *,
    include_not_found: bool = False,
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build standard metadata for a calendar-entry command."""
    merged = dict(CALENDAR_ENTRY_ERROR_CASES) if include_not_found else {}
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
