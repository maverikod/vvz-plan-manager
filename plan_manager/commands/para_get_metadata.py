"""Extended AI/documentation metadata for ParaGetCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_get_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_get.

    Args:
        cls: The ParaGetCommand class, providing name, version, descr,
            category, author, email class attributes.

    Returns:
        A dictionary with all metadatastd-required documentation fields.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": "Resolves one bare four-character base36 paragraph label of the resolved plan's HRS to its full paragraph record. Read-only: this command never mutates the HRS, the database, or any other state. An unknown label yields the PARAGRAPH_NOT_FOUND error code rather than a partial or empty result. Use para_list to discover valid labels.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "label": {
                "description": 'Bare four-character base36 paragraph label (no braces), e.g. "a1b2".',
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The resolved paragraph.",
                "data": {
                    "label": "Four-character base36 label (string).",
                    "binding": "Whether the paragraph is a binding block (boolean).",
                    "position": "Zero-based position of the paragraph in the HRS (integer).",
                    "text": "Full paragraph text (string).",
                },
                "example": {"label": "a1b2", "binding": True, "position": 0, "text": "..."},
            },
            "error": {
                "description": "Returned when the plan cannot be resolved or the label is unknown.",
                "code": "PLAN_NOT_FOUND | PARAGRAPH_NOT_FOUND",
                "message": "Plan not found: {plan} | label not found: {label}",
                "details": "May include the raw plan identifier or label that failed to resolve.",
            },
        },
        "usage_examples": [
            {
                "description": "Resolve one paragraph label to its text.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "label": "a1b2",
                },
                "explanation": "Returns the paragraph record for label a1b2, or a PARAGRAPH_NOT_FOUND error when the label is unknown.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            },
            "PARAGRAPH_NOT_FOUND": {
                "description": "No paragraph in the plan's HRS carries the given label.",
                "message": "label not found: {label}",
                "solution": "Call para_list to discover the valid labels currently assigned in the plan's HRS.",
            },
        },
        "best_practices": [
            "Validate the label shape (four base36 characters) client-side before calling, to avoid an avoidable round trip.",
            "Call para_list first when the label is not already known to the caller.",
        ],
    }
