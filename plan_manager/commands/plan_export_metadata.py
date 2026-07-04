"""Extended metadata for the plan_export command."""

from typing import Any, Dict


def get_plan_export_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata for PlanExportCommand.

    Args:
        cls: The PlanExportCommand class (passed as ``cls`` from a classmethod).

    Returns:
        A dictionary conforming to the metadatastd.yaml required_fields: name, version, description, category, author, email, detailed_description, parameters, return_value, usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": "Renders one resolved plan into the standard file layout under the server-configured export root. Read-only over plan truth: no plan data is modified. The export root directory is taken exclusively from server configuration (AppConfig.export_root); request parameters never carry filesystem paths. When the optional revision parameter is omitted, the plan head revision is exported; when supplied, it must be a valid revision UUID belonging to the plan's version history, otherwise the command returns REVISION_NOT_FOUND. This command is queue-bound (use_queue = True) because rendering a full plan layout to disk can take longer than an interactive request budget.",
        "parameters": {
            "plan": {
                "description": "Plan identifier resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "revision": {
                "description": "Optional revision UUID to export instead of the plan head revision. Must parse as a UUID.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The written layout summary.",
                "data": {
                    "root": "Filesystem path of the written layout root.",
                    "files": "Number of files written.",
                    "revision": "The revision string that was exported, or 'head' when no revision was requested.",
                },
                "example": {
                    "root": "/var/planmgr/export/my-plan",
                    "files": 42,
                    "revision": "head",
                },
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
                "description": "Export the current head revision of a plan.",
                "command": {"plan": "my-plan"},
                "explanation": "Writes the standard layout for the plan head revision under the configured export root.",
            },
            {
                "description": "Export a specific historical revision.",
                "command": {
                    "plan": "my-plan",
                    "revision": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
                "explanation": "Writes the standard layout as it existed at the given revision.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not exist in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "REVISION_NOT_FOUND": {
                "description": "The revision parameter does not identify a stored revision of the plan.",
                "message": "Revision not found: {revision}",
                "solution": "Omit revision to export the head, or supply a revision id from the plan's version history.",
            },
        },
        "best_practices": [
            "This command is read-only: it never mutates plan data or the version store.",
            "The export root is fixed by server configuration; no dry-run is needed because nothing in the database changes.",
            "Verify the export by reading the written layout files at the returned root path.",
        ],
    }
