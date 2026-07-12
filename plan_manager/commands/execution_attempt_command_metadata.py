"""Shared metadata builder for the execution-attempt command group (C-029): execution-attempt-specific error cases plus a thin wrapper over the runtime metadata builder."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS


EXECUTION_ERROR_CASES = {
    "EXECUTION_ATTEMPT_NOT_FOUND": {
        "description": "The supplied execution attempt identifier does not resolve to a stored execution_attempt record.",
        "message": "execution attempt not found: {attempt_id}",
        "solution": "Call execution_attempt_list and retry with an existing attempt identifier.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied plan/revision/step anchor is malformed, or the step does not belong to the given plan (and revision, if given).",
        "message": "invalid anchor: {details}",
        "solution": "Supply a step that belongs to the given plan and, if a revision is given, to that revision.",
    },
}


def execution_attempt_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for an execution-attempt command, merging
    EXECUTION_ERROR_CASES (and any command-specific error_cases passed in) into the
    shared runtime metadata builder. Args: cls -- the Command subclass providing
    name, version, descr, category, author, email; parameters -- the command's full
    parameters dict; return_value -- the command's return value schema dict;
    examples -- the command's usage examples list; error_cases -- optional
    command-specific error cases merged on top of EXECUTION_ERROR_CASES (default
    None); best_practices -- optional command-specific best practices list (default
    None). Returns: the metadata dict produced by runtime_metadata, whose
    error_cases is COMMON_ERROR_CASES merged with EXECUTION_ERROR_CASES merged with
    the passed error_cases (later merges override earlier ones on key collision).
    """
    merged_error_cases = dict(EXECUTION_ERROR_CASES)
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
