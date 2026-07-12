"""Shared metadata builder for the bug lifecycle command group (C-029): common bug error cases and the bug_metadata builder, re-exporting the base parameters and filter/pagination fragment helpers."""
from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import (
    BASE_PARAMETERS,
    runtime_metadata,
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
)

BUG_ERROR_CASES = {
    "BUG_NOT_FOUND": {
        "description": "The supplied bug identifier does not resolve to a stored BugReport.",
        "message": "bug not found: {bug_id}",
        "solution": "Call bug_list and retry with an existing bug identifier.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied primary source anchor for the bug is malformed, incomplete for its source_type, or does not reference an existing anchor target.",
        "message": "invalid bug source anchor: {details}",
        "solution": "Supply a source_type-consistent set of identifier fields; see the bug_create parameter descriptions for the fields required by each source_type.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": (
            "The requested bug lifecycle transition is illegal from the bug's current status. The shared "
            "terminal-status guard refuses it: closed/rejected/duplicate are terminal and may be left ONLY "
            "via bug_reopen, and bug_confirm is legal only from reported/triaged (idempotent from confirmed). "
            "bug_close additionally requires the BugClosureDiscipline invariant (C-026) to be satisfied: the "
            "source fix verified, and every downstream impact and propagation fully handled."
        ),
        "message": "invalid bug status transition: {details}",
        "solution": (
            "Inspect the error details: current_status and legal_targets name the statuses reachable from here "
            "(use bug_reopen to leave a terminal status). For bug_close, resolve every blocking condition "
            "reported (verify the source fix, resolve or clear every impact, finish every propagation) before retrying."
        ),
    },
}


def bug_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a bug lifecycle command, merging BUG_ERROR_CASES (itself layered under COMMON_ERROR_CASES via runtime_metadata) with any command-specific error_cases.

    Args:
        cls: the Command subclass providing name, version, descr, category, author, email class attributes.
        parameters: the command's full parameters dict.
        return_value: the command's return value schema dict.
        examples: the command's usage examples list.
        error_cases: optional command-specific error cases, merged on top of BUG_ERROR_CASES; same-named keys override the layer below.
        best_practices: optional command-specific best practices list.

    Returns:
        The standard metadata dict as built by runtime_metadata.
    """
    merged_error_cases = dict(BUG_ERROR_CASES)
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
