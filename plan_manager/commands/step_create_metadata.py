"""Extended AI/documentation metadata for the step_create command."""

from typing import Any


def get_step_create_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepCreateCommand.

    Args:
        cls: The StepCreateCommand class object, used to source identity
            attributes (name, version, category, author, email) so the
            metadata dictionary never drifts from the class definition.

    Returns:
        A dictionary with the required metadata fields: name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases,
        best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Scaffolds a new step under the declarative level schema with "
            "the level-specific required-field skeleton (populated with "
            "empty values per the declarative level schema defaults, C-006), "
            "status draft, and the next free zero-padded identifier (G-NNN "
            "for level 3, T-NNN for level 4, A-NNN for level 5). The "
            "command itself supplies the skeleton; the caller does not pass "
            "field values on creation. Level 3 steps have no parent; "
            "level 4 and 5 steps require parent_step_id. This is a mutating "
            "command that runs under the mutation admission regime: direct "
            "execution is admitted only when the parent (or, for level 3, "
            "the plan root) is not frozen; otherwise the command returns "
            "CASCADE_REQUIRED, or CASCADE_CONFLICT when a cascade_uuid was "
            "supplied but does not admit the mutation, or FROZEN_ARTIFACT "
            "when the parent is frozen at or below the change point. A "
            "fresh draft leaf never invalidates any other step. The command "
            "verifies its own result by re-reading the created step after "
            "writing the revision. The optional top-level project_id binds "
            "the new step to an analysis-server project UUID already attached "
            "to the plan; it is never passed inside fields."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "level": {
                "description": "Target hierarchy level for the new step: 3 (global step), 4 (tactical step), or 5 (atomic step).",
                "type": "integer",
                "required": True,
                "enum": [3, 4, 5],
            },
            "slug": {
                "description": "Lowercase kebab-case slug (pattern ^[a-z0-9][a-z0-9-]*$), unique among siblings under the same parent.",
                "type": "string",
                "required": True,
            },
            "parent_step_id": {
                "description": "Human-readable step_id of the parent step; required for levels 4 and 5, must be absent for level 3.",
                "type": "string",
                "required": False,
            },
            "cascade_uuid": {
                "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen parent.",
                "type": "string",
                "required": False,
            },
            "project_id": {
                "description": "Optional analysis-server project UUID already bound to the plan; stored as the step's top-level project_id.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The scaffolded step's identity and the revision that recorded it.",
                "data": {
                    "uuid": "Immutable UUID identity of the new step, as a string.",
                    "step_id": "The assigned human-readable step identifier.",
                    "slug": "The slug of the new step.",
                    "level": "The hierarchy level of the new step.",
                    "project_id": "Top-level analysis-server project UUID, or null.",
                    "status": "The status of the new step (always draft).",
                    "revision_uuid": "UUID of the version-store revision that recorded the creation, as a string.",
                },
                "example": {
                    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "step_id": "T-007",
                    "slug": "graph-commands",
                    "level": 4,
                    "project_id": None,
                    "status": "draft",
                    "revision_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef",
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "Stable domain error code (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Create a new tactical step under an existing global step.",
                "command": {"plan": "plan_manager", "level": 4, "slug": "graph-commands", "parent_step_id": "G-005"},
                "explanation": "Scaffolds a draft T-NNN step under G-005 with the next free zero-padded id.",
            },
            {
                "description": "Create a new global step bound to an attached project.",
                "command": {
                    "plan": "plan_manager",
                    "level": 3,
                    "slug": "project-context",
                    "project_id": "4acd4be1-d166-417d-81c6-76bf77b4a392",
                },
                "explanation": "Validates that the project UUID is already attached to the plan, then stores it on the step.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "parent_step_id was given but does not match any step in the plan.",
                "message": "step not found: {parent_step_id}",
                "solution": "Call step_tree to list valid step_id values for the plan.",
            },
            "AMBIGUOUS_PARENT_STEP_ID": {
                "description": "A bare local parent_step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {parent_step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID for parent_step_id.",
            },
            "DUPLICATE_ID": {
                "description": "A sibling step with the same slug already exists under the same parent.",
                "message": "duplicate slug under parent",
                "solution": "Choose a different slug or update the existing step instead.",
            },
            "CASCADE_REQUIRED": {
                "description": "The parent is not directly mutable and no cascade_uuid was supplied.",
                "message": "cascade required to create under this parent",
                "solution": "Begin a cascade and retry with its cascade_uuid.",
            },
            "CASCADE_CONFLICT": {
                "description": "The supplied cascade_uuid does not admit this mutation.",
                "message": "cascade_uuid does not admit this mutation",
                "solution": "Verify the cascade is open, targets this plan, and retry with the correct cascade_uuid.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The parent is frozen at or below the change point and no admitting cascade was supplied.",
                "message": "parent is frozen at or below the change point",
                "solution": "Begin a cascade to mutate under a frozen parent.",
            },
            "INVALID_PROJECT_ID": {
                "description": "project_id was supplied but is not a UUID.",
                "message": "project_id must be a valid UUID",
                "solution": "Retry with an analysis-server project UUID.",
            },
            "PROJECT_NOT_BOUND_TO_PLAN": {
                "description": "project_id was supplied but is not attached to the plan.",
                "message": "project_id is not bound to plan",
                "solution": "Call plan_project_attach first, then retry step_create.",
            },
            "CONTEXT_BLOCKS_MISSING": {
                "description": (
                    "The parent (a global step or tactical step) has no CURRENT compiled "
                    "context_common block for the child level being created. A block "
                    "compiled against a superseded revision counts as absent."
                ),
                "message": "parent {parent_path} has no current context_common block for child_level {level}",
                "solution": "Call context_common for the exact parent node and child_level, then retry step_create.",
            },
        },
        "best_practices": [
            "Call step_tree first to confirm the parent_step_id exists and to avoid slug collisions.",
            "Omit cascade_uuid for direct-mode creation under non-frozen parents; supply it only when working inside an open cascade.",
            "Re-read the created step with step_get to confirm the assigned step_id before referencing it elsewhere.",
        ],
    }
