"""Extended AI/documentation metadata for ParaUpdateCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_update_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_update.

    Args:
        cls: The ParaUpdateCommand class, providing name, version, descr,
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
        "detailed_description": "Mutating command. Replaces the TEXT of exactly one existing binding paragraph addressed by its bare four-character base36 label, in place: the row's uuid, label, position, and binding flag are all preserved, so concept source_labels and coverage references stay valid. The replacement text must parse (through the normative HRS paragraph parser) to exactly one binding paragraph; a '{xxxx} ' prefix in the text is rejected unless it equals the addressed label — this command never rewrites labels (labels are assigned at insert/import time and are stable identities). Only binding paragraphs are addressable: a wrapped (non-binding) row keeps its label but must be unwrapped with para_mark_non_binding before it can be edited. Admission follows the mutation admission regime: when any step of the plan is frozen, a request without an open cascade identity is rejected with FROZEN_ARTIFACT (or CASCADE_REQUIRED when no step is frozen but a cascade is open elsewhere), and a stale or unknown cascade identity yields CASCADE_CONFLICT; when no step is frozen and no cascade_uuid was supplied, the mutation is admitted directly and advances the plan head revision. The new state is recorded as a per-paragraph version snapshot exactly like the sibling paragraph mutations, so a cascade abort restores the previous text. The command verifies its own result before returning by re-reading the stored paragraph and asserting the text changed while uuid, label, and position stayed fixed. Callers can independently confirm the result at any time by calling para_get.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "label": {
                "description": "Bare four-character base36 label of the binding paragraph to update (no braces).",
                "type": "string",
                "required": True,
            },
            "text": {
                "description": "Replacement markdown text. Must parse to exactly one binding paragraph; a '{xxxx} ' prefix is rejected unless it equals the addressed label.",
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
                "description": "The updated paragraph's identity (unchanged by the edit).",
                "data": {
                    "uuid": "The paragraph row's UUID, preserved (string).",
                    "label": "The addressed label, preserved (string).",
                    "position": "The paragraph's position, preserved (integer).",
                },
                "example": {
                    "uuid": "22222222-2222-2222-2222-222222222222",
                    "label": "a3f9",
                    "position": 2,
                },
            },
            "error": {
                "description": "Returned when the plan cannot be resolved, the label addresses no binding paragraph, the text is invalid, or the mutation is not admitted.",
                "code": "PLAN_NOT_FOUND | PARAGRAPH_NOT_FOUND | IMPORT_INVALID | CASCADE_REQUIRED | CASCADE_CONFLICT | FROZEN_ARTIFACT",
                "message": "Plan not found: {plan} | label not found: {label} | text must parse to exactly one binding paragraph, got {n} | admission-specific message",
                "details": "May include the raw plan identifier, the label, or the admission failure reason.",
            },
        },
        "usage_examples": [
            {
                "description": "Replace the text of paragraph a3f9.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "label": "a3f9",
                    "text": "The exporter must retry transient network failures up to five times.",
                },
                "explanation": "Rewrites the paragraph's prose in place; label a3f9 and its position are untouched.",
            },
            {
                "description": "Update paragraph a3f9 under an open cascade.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "label": "a3f9",
                    "text": "{a3f9} The exporter must retry transient network failures up to five times.",
                    "cascade_uuid": "11111111-1111-1111-1111-111111111111",
                },
                "explanation": "A text prefix equal to the addressed label is accepted (and stripped before storage); the change is recorded under the named open cascade.",
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
                "solution": "Call para_list to discover valid labels; unwrap a wrapped paragraph with para_mark_non_binding direction=unwrap before editing it.",
            },
            "IMPORT_INVALID": {
                "description": "The text does not parse to exactly one binding paragraph, or it carries a '{xxxx} ' label prefix different from the addressed label.",
                "message": "text must parse to exactly one binding paragraph, got {n} | text carries label prefix {other} but addresses paragraph {label}; label rewrites are not allowed here",
                "solution": "Supply markdown that forms one paragraph and either omit the label prefix or repeat the addressed label exactly.",
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
            "Call para_get after para_update to independently confirm the stored text.",
            "Never use para_update to change a label; labels are stable identities referenced by MRS source_labels.",
            "Pass cascade_uuid whenever operating inside an already-open cascade to avoid a CASCADE_REQUIRED round trip.",
            "Remember an HRS text change can invalidate downstream coverage; re-run plan_validate/concept_coverage after editing.",
        ],
    }
