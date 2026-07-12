"""Extended AI/documentation metadata for the step_get command."""

from typing import Any


def get_step_get_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepGetCommand.

    Args:
        cls: The StepGetCommand class object, used to source identity
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
            "Returns one step of a plan (level 3 global step, level 4 "
            "tactical step, or level 5 atomic step) identified by its "
            "human-readable step_id, together with its resolved parent "
            "artifact path. This is a read-only command: it never mutates "
            "the plan and performs no admission or cascade checks. The "
            "plan is resolved against the database catalog by the plan "
            "parameter; step_id is matched among the plan's loaded steps."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Human-readable step identifier (e.g. G-001, T-006, A-003).",
                "type": "string",
                "required": True,
            },
            "include_runtime": {
                "description": "Optional flag; when true, include the step's runtime parameters.",
                "type": "boolean",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The step's resolved fields and its parent path.",
                "data": {
                    "uuid": "Immutable UUID identity of the step, as a string.",
                    "step_id": "Human-readable step identifier.",
                    "slug": "Kebab-case slug of the step.",
                    "level": "Hierarchy level of the step (3, 4, or 5).",
                    "status": "Current lifecycle status of the step.",
                    "parent_path": "Artifact path of the parent step, or null for a level-3 step.",
                    "fields": "Level-specific field dictionary.",
                    "depends_on": "List of step_id values this step depends on.",
                    "concepts": "List of MRS concept_id values this step realizes.",
                    "path": "Artifact path of this step.",
                    "runtime": "RuntimeRecord with activations, execution_attempts, journal_aggregates, authoring when include_runtime is true.",
                },
                "example": {
                    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "step_id": "T-006",
                    "slug": "step-commands",
                    "level": 4,
                    "status": "draft",
                    "parent_path": "docs/plans/example/G-005-api-surface/README.yaml",
                    "fields": {},
                    "depends_on": [],
                    "concepts": ["C-023", "C-026", "C-005", "C-006", "C-007", "C-016"],
                    "path": "docs/plans/example/G-005-api-surface/T-006-step-commands/README.yaml",
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
                "description": "Read one tactical step by its step_id.",
                "command": {"plan": "plan_manager", "step_id": "T-006"},
                "explanation": "Returns T-006 with its resolved parent path and level-specific fields.",
            },
            {
                "description": "Read one step with runtime parameters.",
                "command": {"plan": "plan_manager", "step_id": "A-001", "include_runtime": True},
                "explanation": "Includes runtime only when explicitly requested.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "No step with the given step_id exists in the resolved plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree to list valid step_id values for the plan.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID.",
            },
        },
        "best_practices": [
            "Use step_tree first to discover valid step_id values before calling step_get.",
            "This command never mutates state; it is safe to call at any time and any status.",
            "Leave include_runtime false unless the caller explicitly needs operational runtime data.",
        ],
    }
