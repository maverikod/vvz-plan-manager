"""Extended metadata for the cascade_commit command."""


def get_cascade_commit_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for CascadeCommitCommand.

    Args:
        cls: The CascadeCommitCommand class supplying identity attributes
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
            "Publishes the plan's currently open cascade atomically: runs "
            "the mechanical gate over the accumulated change set and, on a "
            "green verdict, advances the plan head revision and closes the "
            "cascade. On a red verdict the commit is refused, the cascade "
            "stays open, and the error carries the finding count. Safety: "
            "this command mutates the plan head revision and closes the "
            "open cascade only when the gate is green; on refusal no state "
            "changes and the cascade remains open for further edits. "
            "Undo: a successful commit advances the head revision "
            "permanently -- the version store retains every revision so "
            "any prior revision remains addressable, but there is no "
            "single-command revert of a commit; a refused commit changes "
            "nothing and can simply be retried after fixing findings, or "
            "the open cascade can be discarded with cascade_abort. Verify: "
            "this command re-reads the open cascade record and the plan's "
            "head revision after the operation and builds its response "
            "from that fresh state rather than from the mutation's return "
            "value alone; call cascade_preview beforehand to check the "
            "gate verdict without side effects."
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
                    "The gate verdict and the plan's head revision after "
                    "the commit attempt, read fresh from the database."
                ),
                "data": {
                    "green": (
                        "Boolean: whether the mechanical gate was green "
                        "for the committed cascade."
                    ),
                    "scope": "Scope string the gate verdict was computed for.",
                    "head_revision_uuid": (
                        "UUID of the plan head revision after the commit "
                        "attempt, re-read from the database."
                    ),
                },
                "example": {
                    "green": True,
                    "scope": "plan:6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    "head_revision_uuid": (
                        "2b3c4d5e-6f70-4182-99aa-bbccddeeff00"
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
                "description": "Commit the open cascade of a plan by name.",
                "command": {"plan": "plan-manager"},
                "explanation": (
                    "Runs the mechanical gate and, if green, advances the "
                    "plan head revision and closes the cascade."
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
                "description": "The plan has no open cascade to commit.",
                "message": "Plan {plan} has no open cascade.",
                "solution": "Call cascade_begin to open a cascade first.",
            },
            "GATE_RED": {
                "description": (
                    "The mechanical gate found problems in the cascade's "
                    "change set; the commit was refused and the cascade "
                    "stays open."
                ),
                "message": "Commit refused: gate is red ({finding_count} findings).",
                "solution": (
                    "Call cascade_preview to inspect the findings, fix the "
                    "underlying artifacts, and retry cascade_commit."
                ),
            },
        },
        "best_practices": [
            "Call cascade_preview before cascade_commit to confirm the "
            "gate is already green and avoid a refused commit.",
            "On GATE_RED, the cascade remains open -- fix findings and "
            "retry cascade_commit rather than reopening a new cascade.",
            "Treat the returned head_revision_uuid as authoritative; it is "
            "read fresh from the database after the commit attempt.",
        ],
    }
