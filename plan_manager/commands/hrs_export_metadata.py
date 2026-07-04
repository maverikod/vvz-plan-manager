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
        "detailed_description": "Returns the byte-identical HRS Markdown text of a resolved plan. Read-only and not queue-bound: the HRS text is read directly from the version store and returned synchronously. No filesystem access occurs; the export root configuration is not used by this command.",
        "parameters": {
            "plan": {
                "description": "Plan identifier resolved against the catalog.",
                "type": "string",
                "required": True,
            }
        },
        "return_value": {
            "success": {
                "description": "The byte-identical HRS Markdown text.",
                "data": {
                    "markdown": "The full HRS Markdown text of the plan.",
                },
                "example": {"markdown": "# Plan Title\n\n..."},
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
                "explanation": "Returns the plan's HRS text unchanged.",
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
            "The returned text is byte-identical to the stored HRS; do not post-process it before round-tripping through hrs_import.",
        ],
    }
