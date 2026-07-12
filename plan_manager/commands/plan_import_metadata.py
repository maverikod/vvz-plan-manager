"""Extended metadata for the plan_import command."""

from typing import Any, Dict


def get_plan_import_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata for PlanImportCommand.

    Args:
        cls: The PlanImportCommand class (passed as ``cls`` from a classmethod).

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
        "detailed_description": "Reads a standard file layout selected by name under the server-configured export root and creates a new plan from it; import is the only file-to-truth path for a full plan. The source layout is validated before any database write, and a malformed layout is rejected with IMPORT_INVALID without touching the database. Exposes a dry_run mode that defaults to True (safety default on): a dry run only validates the layout and reports whether it would succeed, without creating a plan. When dry_run is False and validation passes, the command creates the plan and then verifies the result by re-reading the created plan through resolve_plan before returning. The source parameter is a bare directory name resolved under app_config().export_root; it never carries a filesystem path (no '/', no '\\', no '..').",
        "parameters": {
            "source": {
                "description": "Name of the standard layout directory under the configured export root. Must not contain '/', '\\' or '..'.",
                "type": "string",
                "required": True,
            },
            "dry_run": {
                "description": "When true (the default), only validate the layout and report the outcome without writing to the database.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The dry-run report or the created plan state, verified by re-read.",
                "data": {
                    "dry_run": "Whether this call was a dry run.",
                    "valid": "Present on dry-run success; always true.",
                    "source": "Present on dry-run success; the source name.",
                    "plan_uuid": "Present on a real import; the created plan's UUID.",
                    "name": "Present on a real import; the created plan's name, re-read after write.",
                },
                "example": {"dry_run": True, "valid": True, "source": "my-plan"},
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
                "description": "Preview an import without writing to the database.",
                "command": {"source": "my-plan"},
                "explanation": "Validates the layout only; dry_run defaults to true.",
            },
            {
                "description": "Perform the import for real.",
                "command": {"source": "my-plan", "dry_run": False},
                "explanation": "Validates the layout, creates the plan, and verifies it by re-read.",
            },
        ],
        "error_cases": {
            "IMPORT_INVALID": {
                "description": "The source layout under the export root failed structural validation.",
                "message": "layout validation failed",
                "solution": "Inspect the returned issues list, fix the layout files, and retry.",
            }
        },
        "best_practices": [
            "dry_run defaults to True; callers must explicitly pass dry_run=False to write.",
            "The layout is always validated before any database write; a malformed layout never touches the database.",
            "After a real import, verify by re-reading the plan with resolve_plan or the plan catalog command.",
            "source is a bare name under server-configured export_root; it is never a filesystem path.",
            "This command runs on the queue: the plan_import call returns an enqueue acknowledgement with job_id, store='queuemgr', and poll_with='queue_get_job_status'. Poll completion with queue_get_job_status (which reports status plus created_at/started_at/completed_at); do NOT poll with the builtin job_status, which reads a separate in-memory JobManager store and will report the job as not found (returning its own poll_with='queue_get_job_status' hint).",
        ],
    }
