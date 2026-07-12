"""Shared metadata builder and domain error cases for the bug impact commands (C-029, C-030)."""
from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import BASE_PARAMETERS, runtime_metadata

BUG_IMPACT_ERROR_CASES: dict[str, dict[str, str]] = {
    "BUG_IMPACT_NOT_FOUND": {
        "description": "The supplied impact_uuid does not resolve to a stored bug_impact record.",
        "message": "bug impact not found: {impact_uuid}",
        "solution": "Call bug_impact_list for the bug and retry with a valid impact uuid.",
    },
    "BUG_NOT_FOUND": {
        "description": "The supplied bug_id does not resolve to a stored bug_report record.",
        "message": "bug not found: {bug_id}",
        "solution": "Call bug_list and retry with a valid bug id.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": "The requested bug impact status transition is not permitted, or a transition into skipped was attempted without a reason.",
        "message": "invalid bug impact status transition: {details}",
        "solution": "Supply a valid target status; when transitioning to skipped, also supply a non-empty reason.",
    },
}


def bug_impact_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the metadata dict for a bug impact command, merging BUG_IMPACT_ERROR_CASES (overridable by error_cases) then delegating to runtime_metadata.

    Args:
        cls: the Command subclass providing name/version/descr/category/author/email.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases; overrides same-named keys in BUG_IMPACT_ERROR_CASES.
        best_practices: optional command-specific best practices list.

    Returns:
        The standard metadata dict produced by runtime_metadata, with error_cases pre-merged from BUG_IMPACT_ERROR_CASES.
    """
    merged_error_cases = dict(BUG_IMPACT_ERROR_CASES)
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
