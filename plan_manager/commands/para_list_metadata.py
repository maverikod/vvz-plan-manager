"""Extended AI/documentation metadata for ParaListCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


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
        "detailed_description": "Lists every paragraph of the resolved plan's HRS text in position order. Read-only: this command never mutates the HRS, the database, or any other state. Each paragraph row carries its label (None when unassigned), its binding flag, its zero-based position, and its text. Use para_label_assign beforehand to ensure binding paragraphs carry labels.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "Every paragraph of the plan's HRS in position order.",
                "data": {
                    "paragraphs": "List of paragraph objects, each with label (string or null), binding (boolean), position (integer), and text (string)."
                },
                "example": {
                    "paragraphs": [
                        {"label": "a1b2", "binding": True, "position": 0, "text": "..."},
                        {"label": None, "binding": False, "position": 1, "text": "..."},
                    ]
                },
            },
            "error": {
                "description": "Returned when the plan cannot be resolved.",
                "code": "PLAN_NOT_FOUND",
                "message": "Plan not found: {plan}",
                "details": "May include the raw plan identifier that failed to resolve.",
            },
        },
        "usage_examples": [
            {
                "description": "List every paragraph of a plan's HRS.",
                "command": {"plan": "f06b7269-cc9c-4293-886b-24984e4033ba"},
                "explanation": "Returns all paragraphs in position order with label, binding flag, and text.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            }
        },
        "best_practices": [
            "Call para_list after para_label_assign to confirm every binding paragraph now carries a label.",
            "This command is read-only and safe to call at any time without cascade coordination.",
        ],
    }
