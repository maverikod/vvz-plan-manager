"""Shared metadata builder for the runtime_link command group (C-012, C-016): common error cases and the runtime_link_metadata builder, re-exporting BASE_PARAMETERS."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS

RUNTIME_LINK_ERROR_CASES: dict[str, dict[str, str]] = {
    "RUNTIME_LINK_NOT_FOUND": {
        "description": "The supplied runtime link identifier does not resolve to an existing link.",
        "message": "runtime link not found: {link}",
        "solution": "Call runtime_link_list to discover existing runtime link identifiers.",
    },
}

def runtime_link_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
    detailed_description: str | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a runtime_link command (C-012), merging RUNTIME_LINK_ERROR_CASES (and, transitively, COMMON_ERROR_CASES) with any command-specific error_cases, then delegating to runtime_metadata.

    Args:
        cls: the Command subclass providing name/version/descr/category/author/email.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: usage examples list.
        error_cases: optional command-specific error cases merged on top of RUNTIME_LINK_ERROR_CASES (default None).
        best_practices: optional command-specific best practices list (default None, passed through to runtime_metadata).
        detailed_description: optional longer description passed through to runtime_metadata (default None, which falls back to cls.descr).

    Returns:
        The standard metadata dict produced by runtime_metadata.
    """
    merged_error_cases = dict(RUNTIME_LINK_ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    return runtime_metadata(
        cls,
        parameters,
        return_value,
        examples,
        error_cases=merged_error_cases,
        best_practices=best_practices,
        detailed_description=detailed_description,
    )
