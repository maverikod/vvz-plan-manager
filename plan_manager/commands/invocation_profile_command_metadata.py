"""Shared metadata builder for the invocation-profile command group (C-015, C-008): PROFILE error cases and the invocation_profile_metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS


PROFILE_ERROR_CASES = {
    "INVOCATION_PROFILE_NOT_FOUND": {
        "description": "The supplied profile identifier does not resolve to a stored invocation_profile record.",
        "message": "invocation profile not found: {profile_uuid}",
        "solution": "Call invocation_profile_list and retry with an existing profile_uuid.",
    },
    "INVALID_PROFILE_SCOPE": {
        "description": "The supplied scope value, or the fields required by that scope, are inconsistent with the six-level model-binding inheritance scope vocabulary (C-010) reused unchanged for invocation profiles.",
        "message": "invalid invocation profile scope: {details}; expected one of [...]",
        "solution": "Supply one of system, plan, level, branch, step, role and only the companion fields that scope requires.",
    },
    "INVALID_EXECUTION_MODE": {
        "description": "The supplied execution_mode value is not one of the two recognized values.",
        "message": "invalid execution_mode: {execution_mode}; expected one of ['batch', 'interactive']",
        "solution": "Supply one of 'interactive' or 'batch'.",
    },
}


def invocation_profile_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for an invocation-profile command, merging PROFILE_ERROR_CASES (and any command-specific error_cases) on top of runtime_metadata's common error cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases merged on top of PROFILE_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(PROFILE_ERROR_CASES)
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
