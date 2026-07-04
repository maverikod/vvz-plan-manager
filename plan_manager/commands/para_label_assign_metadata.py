"""Extended AI/documentation metadata for ParaLabelAssignCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_label_assign_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_label_assign.

    Args:
        cls: The ParaLabelAssignCommand class, providing name, version,
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
        "detailed_description": "Mutating command. Inserts fresh unique four-character base36 labels into every unlabeled binding paragraph of the resolved plan's HRS text — the only textual edit this command performs. The edit is line-precise: surrounding prose stays byte-identical outside the inserted label markers. Admission follows the mutation admission regime: when the change point sits above a frozen artifact, a request without an open cascade identity is rejected with CASCADE_REQUIRED, and a stale or unknown cascade identity yields CASCADE_CONFLICT; when no step is frozen and no cascade_uuid was supplied, the mutation is admitted directly and advances the plan head revision. This command has no dry_run parameter: it is inherently safe because it only ever fills in previously absent labels and never rewrites existing labels or paragraph text, and it verifies its own result before returning by re-reading the plan's paragraphs with para_list's underlying listing and asserting every binding paragraph now carries a non-null label. Callers can independently confirm the result at any time by calling para_list.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "cascade_uuid": {
                "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one because the change point sits above a frozen artifact. Omit for direct admission when no frozen artifact blocks the change.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The labels freshly assigned to previously unlabeled binding paragraphs.",
                "data": {
                    "assigned": "List of newly assigned four-character base36 labels (strings), in assignment order.",
                    "count": "Number of labels assigned (integer).",
                },
                "example": {"assigned": ["a1b2", "c3d4"], "count": 2},
            },
            "error": {
                "description": "Returned when the plan cannot be resolved or the mutation is not admitted.",
                "code": "PLAN_NOT_FOUND | CASCADE_REQUIRED | CASCADE_CONFLICT | FROZEN_ARTIFACT",
                "message": "Plan not found: {plan} | admission-specific message",
                "details": "May include the raw plan identifier, the parsed cascade_uuid, or the admission failure reason.",
            },
        },
        "usage_examples": [
            {
                "description": "Assign labels directly (no frozen artifact blocks the change).",
                "command": {"plan": "f06b7269-cc9c-4293-886b-24984e4033ba"},
                "explanation": "Inserts fresh labels into unlabeled binding paragraphs and advances the plan head revision directly.",
            },
            {
                "description": "Assign labels under an open cascade.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "cascade_uuid": "11111111-1111-1111-1111-111111111111",
                },
                "explanation": "Admits the mutation under the named open cascade instead of advancing the plan head directly.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
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
            "Call para_list after para_label_assign to independently confirm every binding paragraph now carries a label.",
            "Pass cascade_uuid whenever operating inside an already-open cascade to avoid a CASCADE_REQUIRED round trip.",
        ],
    }
