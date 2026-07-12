"""Shared metadata builder for the review-and-escalation command group (C-029): common error cases for review_result and escalation commands, plus the review_escalation_metadata builder."""
from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_command_metadata import runtime_metadata, BASE_PARAMETERS


ERROR_CASES = {
    "REVIEW_RESULT_NOT_FOUND": {
        "description": "The requested review result does not resolve.",
        "message": "review result not found: {review_id}",
        "solution": "Call review_result_list to discover valid review identifiers, or verify the identifier is correct.",
    },
    "ESCALATION_NOT_FOUND": {
        "description": "The requested escalation does not resolve.",
        "message": "escalation not found: {escalation_id}",
        "solution": "Call escalation_create to create a new escalation, or verify the identifier is correct.",
    },
    "SELF_CERTIFICATION_FORBIDDEN": {
        "description": "The reviewer identity equals the producer identity (created_by) of the execution attempt under review; the code executor may not certify its own result (C-017 OwnerReviewLadder).",
        "message": "self-certification forbidden: reviewer {reviewer} equals the execution attempt producer identity",
        "solution": "Record the review under a reviewer identity distinct from the attempt's created_by producer, per the owner review ladder.",
    },
    "INVALID_RUNTIME_STATUS_TRANSITION": {
        "description": "The requested status value is not a valid status for this entity.",
        "message": "invalid runtime status transition: {details}",
        "solution": "Supply one of the entity's valid status values; consult the command schema for the allowed set.",
    },
    "INVALID_ANCHOR": {
        "description": "The supplied primary anchor is malformed or does not reference an existing anchor target.",
        "message": "invalid anchor: {details}",
        "solution": "Supply a well-formed anchor referencing an existing plan/step/project/file target.",
    },
}


def review_escalation_metadata(
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
