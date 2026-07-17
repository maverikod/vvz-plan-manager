"""Extended AI/documentation metadata for ParaDeleteCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_delete_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_delete.

    Args:
        cls: The ParaDeleteCommand class, providing name, version, descr,
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
        "detailed_description": "Mutating command. Deletes exactly one binding paragraph addressed by its bare four-character base36 label and closes the position gap: every later row (binding or wrapped non-binding — the stored position sequence covers all rows) shifts one position up. This is a TRUE row removal recorded as a tombstone snapshot (deleted=true) plus post-shift snapshots of the moved rows, all in one revision, so a cascade abort restores the deleted paragraph and the whole position sequence atomically. It differs from para_mark_non_binding direction=wrap, which merely hides a paragraph reversibly while keeping the row. Only binding paragraphs are addressable: a wrapped (non-binding) row keeps its label but cannot be deleted here — unwrap it with para_mark_non_binding first if it must be removed. Admission follows the mutation admission regime: when any step of the plan is frozen, a request without an open cascade identity is rejected with FROZEN_ARTIFACT (or CASCADE_REQUIRED when no step is frozen but a cascade is open elsewhere), and a stale or unknown cascade identity yields CASCADE_CONFLICT; when no step is frozen and no cascade_uuid was supplied, the mutation is admitted directly and advances the plan head revision. The command verifies its own result before returning by re-reading the stored rows and asserting the row is gone and no binding row carries the label. Callers can independently confirm the result at any time by calling para_list.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "label": {
                "description": "Bare four-character base36 label of the binding paragraph to delete (no braces).",
                "type": "string",
                "required": True,
            },
            "cascade_uuid": {
                "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one because a frozen artifact blocks direct paragraph mutation. Omit for direct admission when no step is frozen.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "Confirmation of the removed paragraph.",
                "data": {
                    "uuid": "The deleted paragraph row's UUID (string).",
                    "label": "The deleted paragraph's label (string).",
                    "position": "The position the paragraph occupied before deletion (integer).",
                    "deleted": "Always true on success.",
                },
                "example": {
                    "uuid": "22222222-2222-2222-2222-222222222222",
                    "label": "a3f9",
                    "position": 2,
                    "deleted": True,
                },
            },
            "error": {
                "description": "Returned when the plan cannot be resolved, the label addresses no binding paragraph, or the mutation is not admitted.",
                "code": "PLAN_NOT_FOUND | PARAGRAPH_NOT_FOUND | CASCADE_REQUIRED | CASCADE_CONFLICT | FROZEN_ARTIFACT",
                "message": "Plan not found: {plan} | label not found: {label} | admission-specific message",
                "details": "May include the raw plan identifier, the label, or the admission failure reason.",
            },
        },
        "usage_examples": [
            {
                "description": "Delete paragraph a3f9.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "label": "a3f9",
                },
                "explanation": "Removes the paragraph; every later paragraph shifts one position up.",
            },
            {
                "description": "Delete paragraph a3f9 under an open cascade.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "label": "a3f9",
                    "cascade_uuid": "11111111-1111-1111-1111-111111111111",
                },
                "explanation": "Records the removal (tombstone plus position shifts) under the named open cascade; a cascade abort restores it.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            },
            "PARAGRAPH_NOT_FOUND": {
                "description": "No BINDING paragraph of the plan carries the given label (wrapped non-binding rows are not addressable).",
                "message": "label not found: {label}",
                "solution": "Call para_list to discover valid labels; unwrap a wrapped paragraph with para_mark_non_binding direction=unwrap before deleting it.",
            },
            "CASCADE_REQUIRED": {
                "description": "Direct admission was rejected (an open cascade exists) and no cascade_uuid was supplied while no step is frozen.",
                "message": "admission rejected: cascade required",
                "solution": "Begin a cascade first, then retry supplying its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this mutation (unknown, closed, or not the plan's open cascade).",
                "message": "admission rejected: cascade conflict",
                "solution": "Re-check the open cascade identity and retry, or begin a new cascade.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The plan has a frozen step, so direct paragraph mutation is rejected outside of any cascade context.",
                "message": "admission rejected: frozen artifact",
                "solution": "Begin a cascade to admit HRS changes on a plan with frozen artifacts.",
            },
        },
        "best_practices": [
            "Prefer para_mark_non_binding direction=wrap when the paragraph might come back; para_delete is a true removal.",
            "Check concept source_labels (concept_list) before deleting: a deleted label leaves dangling references that coverage checks will surface.",
            "Call para_list after para_delete to independently confirm the label is gone and positions are contiguous.",
            "Pass cascade_uuid whenever operating inside an already-open cascade to avoid a CASCADE_REQUIRED round trip.",
        ],
    }
