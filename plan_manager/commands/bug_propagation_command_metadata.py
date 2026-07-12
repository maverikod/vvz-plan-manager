"""Shared metadata builder for the bug-propagation commands (C-029), projecting the G-005 bug fix propagation record (C-025)."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import BASE_PARAMETERS, runtime_metadata


ERROR_CASES = {
    "BUG_PROPAGATION_NOT_FOUND": {
        "description": "The supplied propagation identifier does not resolve to a stored bug fix propagation record.",
        "message": "bug propagation not found: {propagation_id}",
        "solution": "Call bug_propagation_list and retry with an existing propagation id.",
    },
    "BUG_FIX_NOT_FOUND": {
        "description": "The supplied bug fix identifier does not resolve to a stored bug fix record.",
        "message": "bug fix not found: {bug_fix_id}",
        "solution": "Call bug_fix_list and retry with an existing bug fix id.",
    },
    "BUG_IMPACT_NOT_FOUND": {
        "description": "The supplied impact identifier does not resolve to a stored bug impact record.",
        "message": "bug impact not found: {impact_id}",
        "solution": "Call bug_impact_list and retry with an existing impact id.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": "The requested status value is not a valid propagation status.",
        "message": "invalid runtime status transition: {details}",
        "solution": "Supply one of: pending, ready, in_progress, done, failed, blocked, skipped, verified.",
    },
}


def bug_propagation_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    merged_error_cases = dict(ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    return runtime_metadata(
        cls,
        parameters,
        return_value,
        examples,
        error_cases=merged_error_cases,
        best_practices=best_practices,
    )
