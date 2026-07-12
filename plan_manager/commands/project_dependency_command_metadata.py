"""Shared metadata builder for the project dependency command group (C-029): group-specific error cases plus the project_dependency_metadata builder wrapping the shared runtime_metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS


ERROR_CASES = {
    "PROJECT_DEPENDENCY_NOT_FOUND": {
        "description": "The supplied dependency_uuid does not resolve to an existing project_dependency edge.",
        "message": "project dependency not found: {dependency_uuid}",
        "solution": "Call project_dependency_list and retry with an existing dependency_uuid.",
    },
    "PROJECT_DEPENDENCY_CYCLE": {
        "description": "Creating this edge would introduce a directed cycle in the project dependency graph.",
        "message": "project dependency cycle detected: {details}",
        "solution": "Remove or redirect the conflicting edge before adding this dependency.",
    },
    "DUPLICATE_PROJECT_DEPENDENCY": {
        "description": "An active edge already exists for this (dependent_project_id, depends_on_project_id, dependency_type) combination.",
        "message": "duplicate project dependency: {details}",
        "solution": "Call project_dependency_list to find the existing edge, or remove it before re-adding.",
    },
    "INVALID_PROJECT_ID": {
        "description": "The supplied project identifier is not a valid external analysis-server project reference.",
        "message": "invalid project id: {details}",
        "solution": "Supply a valid UUID string for the project identifier.",
    },
}


def project_dependency_metadata(
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
