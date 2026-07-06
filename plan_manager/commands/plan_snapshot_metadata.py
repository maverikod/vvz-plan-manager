"""Extended metadata for the plan_snapshot command."""

from typing import Any, Dict


def get_plan_snapshot_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata for PlanSnapshotCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Renders the plan's effective working state into the standard "
            "file layout under the configured export root. If the plan has "
            "an open cascade, the snapshot exports that cascade's current "
            "tip revision without requiring a green gate or cascade commit. "
            "If no cascade is open, it is equivalent to exporting the plan "
            "head. The command is read-only over plan truth and validates "
            "the written layout with the same validator used by plan_import."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier resolved against the catalog.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The written and importable snapshot layout summary.",
                "data": {
                    "root": "Filesystem path of the written layout root.",
                    "files": "Number of files written.",
                    "based_on_revision": "Head revision UUID the snapshot is based on, or null when unavailable.",
                    "cascade_uuid": "Open cascade UUID overlaid into the snapshot, or null when no cascade is open.",
                    "snapshot_revision": "Exact revision rendered: cascade tip when open, otherwise current head or null.",
                    "importable": "Always true after the command validates the layout successfully.",
                },
                "example": {
                    "root": "/var/planmgr/export/my-plan",
                    "files": 42,
                    "based_on_revision": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "cascade_uuid": "9f8e7d6c-5b4a-3c2d-1e0f-a1b2c3d4e5f6",
                    "snapshot_revision": "72bacd3d-1111-2222-3333-444444444444",
                    "importable": True,
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
                "description": "Snapshot the live working state of a plan.",
                "command": {"plan": "my-plan"},
                "explanation": (
                    "Writes an importable standard layout. Open cascade "
                    "content is included automatically."
                ),
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not exist in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "IMPORT_INVALID": {
                "description": "The written snapshot failed standard-layout validation.",
                "message": "snapshot layout validation failed",
                "solution": "Inspect the returned issues and fix the exported state shape.",
            },
        },
        "best_practices": [
            "Use plan_snapshot for backups during active cascade authoring.",
            "Treat snapshot_revision as the exact version-store point rendered to disk.",
            "The command is read-only and does not commit, abort, or score a cascade.",
        ],
    }
