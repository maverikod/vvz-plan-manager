"""Extended metadata for the cascade_abort command."""


def get_cascade_abort_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for CascadeAbortCommand.

    Args:
        cls: The CascadeAbortCommand class supplying identity attributes
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
            "Discards the plan's currently open cascade and restores the "
            "working state to the plan's base revision, confirming that "
            "the published plan (its head revision) is untouched. Safety: "
            "this command mutates database state by closing the cascade "
            "record and releasing the per-plan lock; it never advances the "
            "plan head revision and never touches any published artifact. "
            "Undo: aborting a cascade is itself the undo operation for "
            "every mutation accumulated inside that cascade -- once "
            "aborted, the discarded cascade cannot be reopened, and a new "
            "cascade must be started with cascade_begin to make further "
            "edits. Verify: this command re-reads the open cascade record "
            "after the operation and confirms no cascade remains open for "
            "the plan before returning the plan's (unchanged) head "
            "revision."
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
                    "Confirmation that the open cascade was discarded and "
                    "the plan's head revision, read fresh from the "
                    "database, is unchanged."
                ),
                "data": {
                    "aborted": "Boolean, always true on success.",
                    "head_revision_uuid": (
                        "UUID of the plan head revision after the abort, "
                        "re-read from the database and unchanged by this "
                        "command."
                    ),
                },
                "example": {
                    "aborted": True,
                    "head_revision_uuid": (
                        "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"
                    ),
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
                "description": "Abort the open cascade of a plan by name.",
                "command": {"plan": "plan-manager"},
                "explanation": (
                    "Discards the currently open cascade and confirms the "
                    "plan head revision is unchanged."
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
                "description": "The plan has no open cascade to abort.",
                "message": "Plan {plan} has no open cascade.",
                "solution": "There is nothing to abort; call cascade_begin to start a new cascade.",
            },
        },
        "best_practices": [
            "Use cascade_abort to discard a cascade that failed "
            "cascade_commit with GATE_RED and cannot be easily fixed.",
            "After cascade_abort, the plan head revision is guaranteed "
            "unchanged; verify with a plan read command if independent "
            "confirmation is required.",
            "A new cascade must be opened with cascade_begin before any "
            "further mutating command can run on the plan.",
        ],
    }
