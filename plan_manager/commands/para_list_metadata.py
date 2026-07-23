"""Extended AI/documentation metadata for ParaListCommand."""

from __future__ import annotations

from typing import Any, Dict, Type

from plan_manager.commands.runtime_filtering import pagination_metadata_params
from plan_manager.commands.list_projection import view_metadata_params

def get_para_list_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_list.

    Args:
        cls: The ParaListCommand class, providing name, version, descr,
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
        "detailed_description": "Lists one page of the resolved plan's HRS paragraphs in position order, paginated with the uniform offset/limit convention (default limit 50, max 200). Read-only: this command never mutates the HRS, the database, or any other state. Each paragraph row carries its label (None when unassigned), its binding flag, its zero-based position, and its text. Use para_label_assign beforehand to ensure binding paragraphs carry labels.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            **pagination_metadata_params(),
            **view_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of the plan's HRS paragraphs (or, with view=summary, compact projections) in position order, plus total/limit/offset.",
                "data": {
                    "paragraphs": "List of paragraph objects, each with label (string or null), binding (boolean), position (integer), and text (string).",
                    "total": "Count of the full paragraph set before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "paragraphs": [
                        {"label": "a1b2", "binding": True, "position": 0, "text": "..."},
                        {"label": None, "binding": False, "position": 1, "text": "..."},
                    ],
                    "total": 2,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Returned when the plan cannot be resolved or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | INVALID_PAGINATION",
                "message": "Plan not found: {plan}",
                "details": "May include the raw plan identifier that failed to resolve.",
            },
        },
        "usage_examples": [
            {
                "description": "List the first page of paragraphs of a plan's HRS.",
                "command": {"plan": "f06b7269-cc9c-4293-886b-24984e4033ba"},
                "explanation": "Returns the first page (default limit 50) of paragraphs in position order with label, binding flag, and text.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Call para_list after para_label_assign to confirm every binding paragraph now carries a label.",
            "This command is read-only and safe to call at any time without cascade coordination.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary returns a compact per-row projection (label, binding, position) instead of the full paragraph (drops text, the paragraph body itself -- often multi-sentence and the dominant contributor to row size); use para_get with a label for a single paragraph's full text.",
        ],
    }
