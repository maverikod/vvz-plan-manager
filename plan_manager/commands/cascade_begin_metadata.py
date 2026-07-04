"""Extended metadata for the cascade_begin command."""


def get_cascade_begin_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for CascadeBeginCommand.

    Args:
        cls: The CascadeBeginCommand class supplying identity attributes
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
            "Opens a new cascade transaction on the resolved plan, anchored "
            "at the plan's current head revision. A cascade is the "
            "transactional top-down change set that all MRS and lower-level "
            "mutations require while it is open. Only one cascade may be "
            "open on a plan at a time; the per-plan lock enforces this. "
            "Safety: this command mutates database state (it creates a "
            "cascade record and acquires the per-plan advisory lock) but "
            "does not touch any published artifact -- the plan head revision "
            "is unchanged until cascade_commit runs. Undo: an open cascade "
            "started by this command is discarded without any effect on the "
            "published plan by calling cascade_abort. Verify: call "
            "cascade_preview to inspect the accumulated change set of the "
            "opened cascade, or re-read the plan to confirm no head "
            "revision change occurred. The command itself verifies its own "
            "result by re-reading the open cascade record after opening it "
            "and confirming its identity matches the record just created."
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
                    "The opened cascade identity and its anchor revision, "
                    "confirmed by re-reading the open cascade record."
                ),
                "data": {
                    "cascade_uuid": "UUID of the newly opened cascade.",
                    "base_revision_uuid": (
                        "UUID of the plan head revision the cascade is "
                        "anchored to."
                    ),
                    "ref_name": "Name of the cascade ref record.",
                    "created_at": "ISO 8601 timestamp of cascade creation.",
                },
                "example": {
                    "cascade_uuid": "6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    "base_revision_uuid": (
                        "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"
                    ),
                    "ref_name": "cascade/6f1c2e2a",
                    "created_at": "2026-07-02T12:00:00+00:00",
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
                "description": "Open a cascade on a plan by name.",
                "command": {"plan": "plan-manager"},
                "explanation": (
                    "Opens a new cascade anchored at the current head "
                    "revision of the plan named 'plan-manager'."
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
            "CASCADE_CONFLICT": {
                "description": (
                    "The plan already has an open cascade, or the plan has "
                    "no head revision to anchor a new cascade to, or the "
                    "post-open re-read did not confirm the newly created "
                    "cascade record."
                ),
                "message": "Cascade conflict for plan {plan}.",
                "solution": (
                    "Call cascade_preview to inspect the existing open "
                    "cascade, or cascade_abort to discard it before "
                    "opening a new one."
                ),
            },
        },
        "best_practices": [
            "Call cascade_preview immediately after cascade_begin to "
            "confirm the anchored base revision before making further "
            "mutating calls.",
            "Only one cascade may be open per plan at a time; check for an "
            "existing open cascade before calling cascade_begin.",
            "If cascade_begin fails with CASCADE_CONFLICT, use "
            "cascade_abort to discard a stale open cascade before retrying.",
        ],
    }
