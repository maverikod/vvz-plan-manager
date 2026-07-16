"""Extended metadata for the hrs_export command."""

from typing import Any, Dict

def get_hrs_export_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata for HrsExportCommand.

    Args:
        cls: The HrsExportCommand class (passed as ``cls`` from a classmethod).

    Returns:
        A dictionary conforming to the metadatastd.yaml required_fields.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns a deterministic re-serialization of the plan's binding "
            "HRS paragraphs: each stored paragraph is rendered as "
            "'{label} text' and joined with a blank line, in position order. "
            "Read-only and not queue-bound: the text is built directly from "
            "the version store and returned synchronously. No filesystem "
            "access occurs; the export root configuration is not used by "
            "this command. This reconstruction is NOT necessarily "
            "byte-identical to the originally imported document: headings, "
            "non-binding regions (the text wrapped by <!-- non-binding --> "
            "markers), and fenced code blocks outside binding paragraphs are "
            "not stored and so do not reappear, and inter-paragraph spacing "
            "is normalized to exactly one blank line regardless of the "
            "original document's spacing. Only the labeled binding-paragraph "
            "text itself round-trips exactly through hrs_import -> "
            "hrs_export."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier resolved against the catalog.",
                "type": "string",
                "required": True,
            }
        },
        "return_value": {
            "success": {
                "description": "The re-serialized HRS Markdown text of the binding paragraphs.",
                "data": {
                    "markdown": "The plan's binding paragraphs re-serialized as HRS Markdown text.",
                },
                "example": {"markdown": "{0001} Paragraph text.\n\n{0002} Next paragraph text.\n"},
            },
            "error": {
                "description": "Domain error result.",
                "code": "stable domain error code",
                "message": "human-readable message",
                "details": "additional diagnostic fields when available",
            },
        },
        "usage_examples": [
            {
                "description": "Export the HRS Markdown of a plan.",
                "command": {"plan": "my-plan"},
                "explanation": "Returns the plan's binding paragraphs re-serialized as HRS Markdown text.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not exist in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            }
        },
        "best_practices": [
            "This command is read-only and safe to call at any time.",
            "Do not assume the returned text is byte-identical to an originally imported document; headings, non-binding regions, and code fences outside binding paragraphs are not preserved. Only the labeled binding-paragraph text round-trips exactly through hrs_import.",
        ],
    }
