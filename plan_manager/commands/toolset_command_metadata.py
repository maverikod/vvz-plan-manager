"""Shared metadata builder for the toolset command group (C-002, C-015): TOOLSET error cases and the toolset_metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata


TOOLSET_ERROR_CASES = {
    "TOOLSET_NOT_FOUND": {
        "description": "The supplied toolset identifier does not resolve to a stored toolset record.",
        "message": "toolset not found: {toolset_uuid}",
        "solution": "Call toolset_list and retry with an existing toolset_uuid.",
    },
}


def toolset_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a toolset command, merging TOOLSET_ERROR_CASES (and any command-specific error_cases) on top of runtime_metadata's common error cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases merged on top of TOOLSET_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(TOOLSET_ERROR_CASES)
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
