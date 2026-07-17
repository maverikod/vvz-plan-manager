"""Extended AI/documentation metadata for ParaInsertCommand."""

from __future__ import annotations

from typing import Any, Dict, Type


def get_para_insert_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Build the extended metadata dictionary for para_insert.

    Args:
        cls: The ParaInsertCommand class, providing name, version, descr,
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
        "detailed_description": "Mutating command. Inserts EXACTLY ONE new binding paragraph into the stored HRS of a plan, in contrast to hrs_import which replaces the whole paragraph set. The text must parse (through the normative HRS paragraph parser) to exactly one binding paragraph; an optional '{xxxx} ' prefix on the text supplies the label. The position parameter is a zero-based index in the BINDING paragraph order: the new paragraph takes the addressed paragraph's place and every later row shifts one position down (non-binding wrapped rows shift together with binding ones because the stored position sequence covers all rows). Omitting position, or passing the current binding paragraph count, appends after the last stored paragraph. The label, when supplied via the parameter or the text prefix, must be four base36 characters and unique within the plan (uniqueness is checked against wrapped non-binding rows too, since an unwrap restores their labels); when absent a fresh unique label is drawn with the normative generator. Admission follows the mutation admission regime: when any step of the plan is frozen, a request without an open cascade identity is rejected with FROZEN_ARTIFACT (or CASCADE_REQUIRED when no step is frozen but a cascade is open elsewhere), and a stale or unknown cascade identity yields CASCADE_CONFLICT; when no step is frozen and no cascade_uuid was supplied, the mutation is admitted directly and advances the plan head revision. The inserted row and every shifted row are recorded as one revision (per-paragraph version snapshots), so a cascade abort restores the whole position sequence atomically. The command verifies its own result before returning by re-reading the stored paragraphs and asserting the new row exists with the expected label, position, and text. Callers can independently confirm the result at any time by calling para_list or para_get.",
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) to resolve.",
                "type": "string",
                "required": True,
            },
            "text": {
                "description": "Markdown text of the new paragraph. Must parse to exactly one binding paragraph; an optional '{xxxx} ' label prefix supplies the label.",
                "type": "string",
                "required": True,
            },
            "position": {
                "description": "Zero-based insertion index in the BINDING paragraph order; the new paragraph takes this place and later paragraphs shift down. Omit to append after the last paragraph.",
                "type": "integer",
                "required": False,
            },
            "label": {
                "description": "Explicit four-character base36 label for the new paragraph (no braces), unique within the plan. Omit to auto-assign a fresh label.",
                "type": "string",
                "required": False,
            },
            "cascade_uuid": {
                "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one because a frozen artifact blocks direct paragraph mutation. Omit for direct admission when no step is frozen.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The created paragraph's identity.",
                "data": {
                    "uuid": "The new paragraph row's UUID (string).",
                    "label": "The paragraph's four-character base36 label (string).",
                    "position": "The stored position the paragraph landed at (integer).",
                },
                "example": {
                    "uuid": "22222222-2222-2222-2222-222222222222",
                    "label": "b7k2",
                    "position": 4,
                },
            },
            "error": {
                "description": "Returned when the plan cannot be resolved, the text or label is invalid, the label is already in use, or the mutation is not admitted.",
                "code": "PLAN_NOT_FOUND | IMPORT_INVALID | DUPLICATE_ID | CASCADE_REQUIRED | CASCADE_CONFLICT | FROZEN_ARTIFACT",
                "message": "Plan not found: {plan} | text must parse to exactly one binding paragraph, got {n} | label already in use: {label} | admission-specific message",
                "details": "May include the raw plan identifier, the offending label or position, or the admission failure reason.",
            },
        },
        "usage_examples": [
            {
                "description": "Append a new paragraph with an auto-assigned label.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "text": "The exporter must retry transient network failures up to three times.",
                },
                "explanation": "Parses the text, draws a fresh unique label, and stores the paragraph after the last one.",
            },
            {
                "description": "Insert a paragraph at binding position 2 with an explicit label, under an open cascade.",
                "command": {
                    "plan": "f06b7269-cc9c-4293-886b-24984e4033ba",
                    "text": "Every export archive carries a checksum manifest.",
                    "position": 2,
                    "label": "c3x9",
                    "cascade_uuid": "11111111-1111-1111-1111-111111111111",
                },
                "explanation": "The new paragraph takes binding position 2; the paragraphs previously at 2 and later shift down one position.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog listing command and retry with a valid plan identifier.",
            },
            "IMPORT_INVALID": {
                "description": "The text does not parse to exactly one binding paragraph, the label is not four base36 characters, the label parameter contradicts the text's own '{xxxx} ' prefix, or the position is out of range 0..binding-count.",
                "message": "text must parse to exactly one binding paragraph, got {n} | label must be exactly four base36 characters [0-9a-z]: {label} | insert position {position} out of range 0..{count}",
                "solution": "Supply markdown that forms one paragraph (no blank lines, headings, fences, or non-binding markers splitting it), a well-formed unique label, and a position within range (call para_list to see the current order).",
            },
            "DUPLICATE_ID": {
                "description": "The supplied (or text-carried) label is already used by a stored paragraph of this plan, including a wrapped non-binding one.",
                "message": "label already in use: {label}",
                "solution": "Omit the label to auto-assign a fresh one, or pick a label not present in para_list output (wrapped rows keep their labels too).",
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
            "Call para_list after para_insert to independently confirm the new paragraph's label and position.",
            "Omit the label parameter unless you must reference the paragraph before creating it; auto-assignment guarantees uniqueness.",
            "Pass cascade_uuid whenever operating inside an already-open cascade to avoid a CASCADE_REQUIRED round trip.",
            "For wholesale HRS restructuring prefer hrs_import; para_insert is for one targeted addition.",
        ],
    }
