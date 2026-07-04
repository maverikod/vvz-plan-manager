"""Extended metadata for the hrs_import command."""

from typing import Any, Dict


def get_hrs_import_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata for HrsImportCommand.

    Args:
        cls: The HrsImportCommand class (passed as ``cls`` from a classmethod).

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
        "detailed_description": "Replaces the HRS text of a resolved plan from a Markdown source selected by name under the server-configured export root. The source text is validated before any write, and a malformed source is rejected with IMPORT_INVALID without touching the database. Exposes a dry_run mode that defaults to True (safety default on): a dry run only validates the text and reports whether it would succeed. When dry_run is False and validation passes, admission is checked: an open cascade is required unless the change is admissible directly. When an explicit cascade_uuid was supplied and admission is rejected, the command returns CASCADE_CONFLICT; when no cascade_uuid was supplied and any step of the plan is frozen, it returns FROZEN_ARTIFACT; otherwise it returns CASCADE_REQUIRED. On successful admission the HRS text is replaced and the result is verified by re-reading the HRS text and asserting it equals the imported text — a mismatch is treated as an internal defect. The source parameter is a bare file name resolved under app_config().export_root; it never carries a filesystem path (no '/', no '\\', no '..').",
        "parameters": {
            "plan": {
                "description": "Plan identifier resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "source": {
                "description": "Name of the Markdown source file under the configured export root. Must not contain '/', '\\' or '..'.",
                "type": "string",
                "required": True,
            },
            "dry_run": {
                "description": "When true (the default), only validate the HRS text without writing to the database.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
            "cascade_uuid": {
                "description": "Identifier of an already-open cascade to scope this import to. Must parse as a UUID when present.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The dry-run report or the paragraph count of the replaced HRS, verified by re-read.",
                "data": {
                    "dry_run": "Whether this call was a dry run.",
                    "valid": "Present on dry-run success; always true.",
                    "paragraphs": "Present on a real import; the number of paragraphs written.",
                },
                "example": {"dry_run": True, "valid": True},
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
                "description": "Preview an HRS replacement without writing to the database.",
                "command": {"plan": "my-plan", "source": "hrs.md"},
                "explanation": "Validates the Markdown source only; dry_run defaults to true.",
            },
            {
                "description": "Replace the HRS text inside an already-open cascade.",
                "command": {
                    "plan": "my-plan",
                    "source": "hrs.md",
                    "dry_run": False,
                    "cascade_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
                "explanation": "Writes the new HRS text scoped to the given open cascade.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not exist in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "IMPORT_INVALID": {
                "description": "The HRS Markdown source failed structural validation.",
                "message": "hrs validation failed",
                "solution": "Inspect the returned issues list, fix the Markdown source, and retry.",
            },
            "CASCADE_REQUIRED": {
                "description": "The HRS replacement is not admissible directly and no cascade_uuid was supplied.",
                "message": "an open cascade is required for this change",
                "solution": "Begin a cascade for the plan and retry with its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this change.",
                "message": "the supplied cascade does not admit this change",
                "solution": "Verify the cascade is open and scoped correctly, or begin a new cascade.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The plan has frozen steps and the change requires a cascade.",
                "message": "the plan has frozen artifacts; a cascade is required",
                "solution": "Begin a cascade for the plan and retry with its cascade_uuid.",
            },
        },
        "best_practices": [
            "dry_run defaults to True; callers must explicitly pass dry_run=False to write.",
            "The HRS text is always validated before any database write; a malformed source never touches the database.",
            "After a real import, the command itself verifies the result by re-reading the HRS text and asserting equality.",
            "source is a bare name under server-configured export_root; it is never a filesystem path.",
        ],
    }
