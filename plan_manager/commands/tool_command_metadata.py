"""Shared metadata builder for the tool command group (C-001, C-015): TOOL error cases and the tool_metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata


TOOL_ERROR_CASES = {
    "TOOL_NOT_FOUND": {
        "description": "The supplied tool identifier does not resolve to a stored tool record.",
        "message": "tool not found: {tool_uuid}",
        "solution": "Call tool_list and retry with an existing tool_uuid.",
    },
}


def tool_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a tool command, merging TOOL_ERROR_CASES (and any command-specific error_cases) on top of runtime_metadata's common error cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases merged on top of TOOL_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(TOOL_ERROR_CASES)
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
