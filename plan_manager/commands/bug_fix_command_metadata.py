"""Shared metadata builder for the bug fix commands (C-024 projected via the RuntimeCommandSurface C-029 and RuntimeFiltering C-030)."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import BASE_PARAMETERS, runtime_metadata
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
)


BUG_FIX_ERROR_CASES: dict[str, dict[str, str]] = {
    "BUG_FIX_NOT_FOUND": {
        "description": "The supplied bug fix identifier does not resolve to an existing BugFix record.",
        "message": "bug fix not found: {bug_fix}",
        "solution": "Call bug_fix_list for the owning bug and retry with an existing bug fix uuid.",
    },
    "BUG_NOT_FOUND": {
        "description": "The supplied bug identifier does not resolve to an existing BugReport record.",
        "message": "bug not found: {bug}",
        "solution": "Call bug_list and retry with an existing bug uuid.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": "The requested status value is not one of the eight legal BugFix lifecycle statuses.",
        "message": "invalid bug fix status: {details}",
        "solution": "Supply one of: proposed, in_progress, implemented, failed, partial, reverted, rejected, verified.",
    },
}


def bug_fix_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a bug fix command (C-024), merging BUG_FIX_ERROR_CASES
    (and the COMMON_ERROR_CASES merged in by runtime_metadata) with any command-specific error_cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict (already merged with BASE_PARAMETERS and any
            filter/pagination fragments by the caller).
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases to merge on top of BUG_FIX_ERROR_CASES
            (default None).
        best_practices: optional command-specific best practices list; when None, a default bug-fix
            best-practices list is used.

    Returns:
        The standard metadata dict produced by runtime_metadata, with BUG_FIX_ERROR_CASES merged under
        error_cases (command-specific error_cases entries override same-named BUG_FIX_ERROR_CASES entries).
    """
    merged_error_cases = dict(BUG_FIX_ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    return runtime_metadata(
        cls,
        parameters,
        return_value,
        examples,
        error_cases=merged_error_cases,
        best_practices=best_practices if best_practices is not None else [
            "Call bug_fix_create only after the owning bug exists.",
            "Call bug_fix_verify after implementing a fix to record whether it passed.",
        ],
    )
