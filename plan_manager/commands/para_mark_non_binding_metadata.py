"""Extended AI/documentation metadata for ParaMarkNonBindingCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_mark_non_binding_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_mark_non_binding.

    Args:
        cls: The ParaMarkNonBindingCommand class, providing name, version,
            descr, category, author, email class attributes.

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
        "detailed_description": "Mutating command. Wraps (direction=wrap) or unwraps (direction=unwrap) the non-binding markers around the HRS block addressed by position, line-precise and byte-preserving outside the markers themselves — surrounding prose is untouched. Admission follows the mutation admission regime: when the change point sits above a frozen artifact, a request without an open cascade identity is rejected with CASCADE_REQUIRED, and a stale or unknown cascade identity yields CASCADE_CONFLICT; when no step is frozen and no cascade_uuid was supplied, the mutation is admitted directly and advances the plan head revision. An unknown position (no block exists there) yields PARAGRAPH_NOT_FOUND. This command has no dry_run parameter: it is inherently bounded to toggling markers around exactly one addressed block and it verifies its own result before returning by re-reading the plan's paragraphs and asserting the block at position now has the expected binding flag (False after wrap, True after unwrap). Callers can independently confirm the result at any time by calling para_list.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "position": {
                "description": "Zero-based position of the HRS block to wrap or unwrap.",
                "type": "integer",
                "required": True,
            },
            "direction": {
                "description": "Whether to wrap the block in non-binding markers or unwrap it.",
                "type": "string",
                "required": True,
                "enum": ["wrap", "unwrap"],
            },
            "cascade_uuid": {
                "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one because the change point sits above a frozen artifact. Omit for direct admission when no frozen artifact blocks the change.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "Confirmation of the toggled block.",
                "data": {
                    "position": "The addressed block position (integer).",
                    "direction": "The applied direction, wrap or unwrap (string).",
                },
                "example": {"position": 4, "direction": "wrap"},
            },
            "error": {
                "description": "Returned when the plan cannot be resolved, the position addresses no block, or the mutation is not admitted.",
                "code": "PLAN_NOT_FOUND | PARAGRAPH_NOT_FOUND | CASCADE_REQUIRED | CASCADE_CONFLICT | FROZEN_ARTIFACT",
                "message": "Plan not found: {plan} | no block at position {position} | admission-specific message",
                "details": "May include the raw plan identifier, the position, or the admission failure reason.",
            },
        },
        "usage_examples": [
            {
                "description": "Wrap the block at position 4 in non-binding markers.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "position": 4,
                    "direction": "wrap",
                },
                "explanation": "Marks the block at position 4 as non-binding, excluding it from labeling and coverage.",
            },
            {
                "description": "Unwrap the block at position 4 under an open cascade.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "position": 4,
                    "direction": "unwrap",
                    "cascade_uuid": "11111111-1111-1111-1111-111111111111",
                },
                "explanation": "Restores the block at position 4 to binding status under the named open cascade.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            },
            "PARAGRAPH_NOT_FOUND": {
                "description": "No block exists at the given position in the plan's HRS.",
                "message": "no block at position {position}",
                "solution": "Call para_list to discover valid positions.",
            },
            "CASCADE_REQUIRED": {
                "description": "The change point sits above a frozen artifact and no cascade_uuid was supplied.",
                "message": "admission rejected: cascade required",
                "solution": "Begin a cascade first, then retry supplying its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this mutation (unknown, closed, or scoped to a different target).",
                "message": "admission rejected: cascade conflict",
                "solution": "Re-check the open cascade identity and retry, or begin a new cascade.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The change point sits above a frozen artifact and admission was rejected outside of any cascade context.",
                "message": "admission rejected: frozen artifact",
                "solution": "Begin a cascade to admit changes above a frozen artifact.",
            },
        },
        "best_practices": [
            "Call para_list after para_mark_non_binding to independently confirm the block's binding flag changed as expected.",
            "Pass cascade_uuid whenever operating inside an already-open cascade to avoid a CASCADE_REQUIRED round trip.",
        ],
    }
