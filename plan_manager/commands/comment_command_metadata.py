"""Shared metadata builder for the comment commands (C-029): comment-specific error cases, a thin wrapper over the shared runtime metadata builder, plus re-exported filter/pagination fragment helpers (C-030)."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
)

COMMENT_ERROR_CASES = {
    "COMMENT_NOT_FOUND": {
        "description": "The supplied comment identifier does not resolve to an existing, non-deleted RuntimeComment record.",
        "message": "comment not found: {comment_uuid}",
        "solution": "Call comment_list to discover an existing comment identifier, or verify the identifier was not superseded or soft-deleted.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied comment anchor is malformed, uses an anchor_type outside the eleven-kind comment anchor vocabulary (or 'none', which comments reject), or does not reference an existing anchor target.",
        "message": "invalid comment anchor: {details}",
        "solution": "Supply a well-formed anchor (anchor_type plus the applicable identifiers) using one of the eleven comment anchor kinds: plan, revision, step, project, file, todo, bug, bug_fix, execution_attempt, review_result, or escalation. 'none' is not a valid comment anchor: a comment always attaches to a subject.",
    },
    "INVALID_VISIBILITY": {
        "description": "The supplied comment visibility value is not one of the known CommentVisibility modes.",
        "message": "invalid comment visibility: {details}",
        "solution": "Supply one of: audit_only, execution_context, owner_context, reviewer_context, public_summary.",
    },
}


def comment_metadata(cls, parameters: dict[str, Any], return_value: dict[str, Any], examples: list[dict[str, Any]], error_cases: dict[str, dict[str, str]] | None = None, best_practices: list[str] | None = None) -> dict[str, Any]:
    """Build the standard metadata dict for a comment command (C-029), merging COMMENT_ERROR_CASES with any command-specific error_cases before delegating to the shared runtime_metadata builder. Args: cls — the Command subclass providing name, version, descr, category, author, email class attributes; parameters — the command's full parameters dict; return_value — the command's return value schema dict; examples — the command's usage examples list; error_cases — optional command-specific error cases merged on top of COMMENT_ERROR_CASES (default None); best_practices — optional command-specific best practices list (default None, passed through unchanged). Returns: the standard metadata dict produced by runtime_metadata."""
    merged_error_cases = dict(COMMENT_ERROR_CASES)
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
