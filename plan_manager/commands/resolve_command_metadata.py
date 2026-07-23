"""Shared metadata builder for the resolve command group (C-015): RESOLVE error cases and the resolve_command_metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS


RESOLVE_ERROR_CASES = {
    "INVALID_RUNTIME_ROLE": {
        "description": "The supplied role value is not one of the twelve recognized runtime roles (C-011).",
        "message": "invalid runtime role: {role}; expected one of [...]",
        "solution": "Supply one of the twelve recognized RuntimeRole values.",
    },
}


def resolve_command_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a resolve command, merging RESOLVE_ERROR_CASES (and any command-specific error_cases) on top of runtime_metadata's common error cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases merged on top of RESOLVE_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(RESOLVE_ERROR_CASES)
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
