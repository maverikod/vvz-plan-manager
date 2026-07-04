"""Extended metadata for the cascade_preview command."""


def get_cascade_preview_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for CascadePreviewCommand.

    Args:
        cls: The CascadePreviewCommand class supplying identity attributes
            (name, version, descr, category, author, email).

    Returns:
        A dictionary with all fields required by the command metadata
        standard: name, version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the accumulated change set of the plan's currently "
            "open cascade against its base revision, the needs_review "
            "blast radius of artifact paths invalidated by the change set, "
            "and the mechanical gate verdict for the cascade state. This "
            "command is read-only: it never mutates the cascade record, "
            "the plan, or any other database state. There is no dry_run or "
            "undo concept for a read-only command. Verify: run "
            "cascade_preview again after further edits to see the updated "
            "change set and gate verdict; the gate verdict returned here "
            "gates whether cascade_commit will accept the cascade."
        ),
        "parameters": {
            "plan": {
                "description": "Plan UUID or unique plan name.",
                "type": "string",
                "required": True,
            }
        },
        "return_value": {
            "success": {
                "description": (
                    "The accumulated change set, needs_review blast "
                    "radius, and mechanical gate verdict of the plan's "
                    "open cascade."
                ),
                "data": {
                    "cascade_uuid": "UUID of the open cascade.",
                    "base_revision_uuid": (
                        "UUID of the plan head revision the cascade is "
                        "anchored to."
                    ),
                    "tip_revision_uuid": (
                        "UUID of the latest revision recorded inside the "
                        "cascade."
                    ),
                    "change_set": (
                        "Object with 'added', 'removed', and 'changed' "
                        "artifact path lists."
                    ),
                    "needs_review": (
                        "List of artifact paths whose status was "
                        "propagated to needs_review by this cascade."
                    ),
                    "gate_green": (
                        "Boolean: whether the mechanical gate passed for "
                        "the cascade's current state."
                    ),
                    "gate_report_json": (
                        "JSON string of the full mechanical gate report."
                    ),
                },
                "example": {
                    "cascade_uuid": "6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    "base_revision_uuid": (
                        "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"
                    ),
                    "tip_revision_uuid": (
                        "2b3c4d5e-6f70-4182-99aa-bbccddeeff00"
                    ),
                    "change_set": {
                        "added": ["G-005-api-surface/T-010-cascade-commands"],
                        "removed": [],
                        "changed": [],
                    },
                    "needs_review": [],
                    "gate_green": True,
                    "gate_report_json": "{\"findings\": []}",
                },
            },
            "error": {
                "description": "Domain error result on failure.",
                "code": "Stable domain error code string (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Optional diagnostic fields, present when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Preview the open cascade of a plan by name.",
                "command": {"plan": "plan-manager"},
                "explanation": (
                    "Returns the change set, blast radius, and gate "
                    "verdict of the currently open cascade."
                ),
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan parameter does not resolve to any plan.",
                "message": "Plan not found: {plan}",
                "solution": (
                    "List existing plans and retry with a valid plan UUID "
                    "or name."
                ),
            },
            "CASCADE_REQUIRED": {
                "description": "The plan has no open cascade to preview.",
                "message": "Plan {plan} has no open cascade.",
                "solution": "Call cascade_begin to open a cascade first.",
            },
        },
        "best_practices": [
            "Call cascade_preview before cascade_commit to confirm the "
            "gate is green and the change set matches expectations.",
            "Inspect needs_review to identify artifacts requiring manual "
            "attention before committing.",
            "cascade_preview is safe to call repeatedly; it never mutates "
            "state.",
        ],
    }
