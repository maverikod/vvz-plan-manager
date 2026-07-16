"""Shared metadata builder for the todo command group (C-029, C-030): common error cases and the todo_metadata builder, re-exporting BASE_PARAMETERS and the runtime filter/pagination helpers."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
)


TODO_ERROR_CASES: dict[str, dict[str, str]] = {
    "TODO_NOT_FOUND": {
        "description": "The supplied todo identifier does not resolve to an existing TODO item.",
        "message": "todo not found: {todo}",
        "solution": "Call todo_list to discover existing todo identifiers.",
    },
    "TODO_LINK_NOT_FOUND": {
        "description": "The supplied todo link identifier does not resolve to an existing link.",
        "message": "todo link not found: {link}",
        "solution": "Verify the link identifier returned by todo_link_add and retry.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied primary anchor for the todo item is malformed or does not reference an existing anchor target.",
        "message": "invalid anchor: {details}",
        "solution": "Supply a well-formed anchor referencing an existing plan/step/project/file/todo target.",
    },
    "INVALID_NICE_PRIORITY": {
        "description": "The supplied priority_nice value is outside the valid range [-20, 19].",
        "message": "invalid priority: {details}",
        "solution": "Supply an integer priority_nice value between -20 and 19 inclusive.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": "The requested todo_update status change is illegal from the todo's current status. Only in_progress, blocked, and cancelled are reachable through todo_update; resolved and closed remain reachable only via the separate todo_resolve/todo_close commands; open is only the initial todo_create status.",
        "message": "invalid todo status transition: {details}",
        "solution": "Inspect the error details: current_status and legal_targets name the statuses reachable from here via todo_update. Use todo_resolve or todo_close for those separate unconditional transitions.",
    },
}


def todo_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a todo command (C-029), merging TODO_ERROR_CASES (and, transitively, COMMON_ERROR_CASES) with any command-specific error_cases, then delegating to runtime_metadata.

    Args:
        cls: the Command subclass providing name/version/descr/category/author/email.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: usage examples list.
        error_cases: optional command-specific error cases merged on top of TODO_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None, passed through to runtime_metadata).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(TODO_ERROR_CASES)
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
