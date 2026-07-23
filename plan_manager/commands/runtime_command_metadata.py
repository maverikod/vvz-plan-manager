"""Shared metadata builder for the runtime command surface (C-029): common base parameters, common error cases, and the runtime_metadata builder, plus re-exported filter/pagination fragment helpers."""

from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    filter_metadata_params,
    pagination_schema_properties,
    pagination_metadata_params,
)


BASE_PARAMETERS = {
    "plan": {
        "description": "Plan identifier (name or UUID).",
        "type": "string",
        "required": True,
    },
}


COMMON_ERROR_CASES = {
    "PLAN_NOT_FOUND": {
        "description": "The plan identifier does not resolve.",
        "message": "plan not found: {plan}",
        "solution": "Call plan_list and retry with a valid plan name or UUID.",
    },
    "RUNTIME_VALIDATION_ERROR": {
        "description": "A runtime write failed a shared runtime validation check (C-031).",
        "message": "runtime validation failed: {details}",
        "solution": "Inspect the error details and correct the offending field before retrying.",
    },
    "FROZEN_TRUTH_WRITE": {
        "description": "The command attempted to mutate frozen plan truth (HRS/MRS/GS/TS/AS, concept relations, execution dependencies, frozen revision).",
        "message": "cannot mutate frozen plan truth: {details}",
        "solution": "Runtime commands never modify frozen truth; verify the target entity is a runtime entity, not a frozen-truth artifact.",
    },
    "PLAN_COMPLETED": {
        "description": "The target plan is marked completed (bug c3950b83): every mutating command that resolves its plan is refused except plan_completed_set and plan_comment_set.",
        "message": "plan {plan_uuid} is marked completed; call plan_completed_set to unset the completion lock before mutating it",
        "solution": "Call plan_completed_set(plan, completed=false, changed_by=...) to unlock the plan, then retry.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied primary anchor is malformed or does not reference an existing anchor target.",
        "message": "invalid anchor: {details}",
        "solution": "Supply a well-formed anchor referencing an existing plan/step/project/file target.",
    },
    "INVALID_NICE_PRIORITY": {
        "description": "The supplied priority value is outside the valid nice-scale range [-20, 19].",
        "message": "invalid priority: {details}",
        "solution": "Supply an integer priority value between -20 and 19 inclusive.",
    },
    "INVALID_FILTER": {
        "description": "A supplied filter parameter value is malformed or out of range.",
        "message": "invalid filter: {details}",
        "solution": "Correct the offending filter parameter and retry; consult the command schema for valid formats.",
    },
    "INVALID_PAGINATION": {
        "description": "The supplied limit or offset value is malformed or out of range.",
        "message": "invalid pagination: {details}",
        "solution": "Supply a limit between 1 and 200 and a non-negative offset.",
    },
}


def runtime_metadata(
    cls,
    parameters: dict[str, Any],
    return_value: dict[str, Any],
    examples: list[dict[str, Any]],
    error_cases: dict[str, dict[str, str]] | None = None,
    best_practices: list[str] | None = None,
    detailed_description: str | None = None,
) -> dict[str, Any]:
    """Build the standard metadata dict for a runtime command (C-029), merging COMMON_ERROR_CASES with any command-specific error_cases. Args: cls — the Command subclass providing name, version, descr, category, author, email class attributes; parameters — the command's full parameters dict (already merged with BASE_PARAMETERS and any filter/pagination fragments by caller); return_value — the command's return value schema dict; examples — the command's usage examples list; error_cases — optional command-specific error cases to merge on top of COMMON_ERROR_CASES (default None); best_practices — optional command-specific best practices list (defaults to empty list when not provided); detailed_description — optional longer description (defaults to cls.descr when not provided). Returns: the standard metadata dict with keys name, version, description, category, author, email, detailed_description, parameters, return_value, usage_examples, error_cases, best_practices."""
    merged_error_cases = dict(COMMON_ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": detailed_description if detailed_description is not None else cls.descr,
        "parameters": parameters,
        "return_value": return_value,
        "usage_examples": examples,
        "error_cases": merged_error_cases,
        "best_practices": best_practices if best_practices is not None else [],
    }
