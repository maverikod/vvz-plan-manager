"""Extended AI/documentation metadata for the step_tree command."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_metadata_params

def get_step_tree_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepTreeCommand.

    Args:
        cls: The StepTreeCommand class object, used to source identity
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
            "Returns one page of the plan's full step tree: every level 3, 4, and 5 "
            "step as a flat list of {path, step_id, slug, level, status} "
            "entries, sorted by (level, path) and paginated with the uniform "
            "offset/limit convention (default limit 50, max 200). This is a "
            "read-only command: it never mutates the plan and performs no "
            "admission or cascade checks."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "include_runtime": {
                "description": "Optional flag; when true, include each step's runtime parameters.",
                "type": "boolean",
                "required": False,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of the plan's full step tree as a flat, sorted list, plus total/limit/offset.",
                "data": {
                    "tree": "List of {path, step_id, slug, level, status} entries, sorted by (level, path). Entries include runtime when include_runtime is true.",
                    "total": "Count of the full step tree before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "tree": [
                        {
                            "path": "docs/plans/example/G-005-api-surface/README.yaml",
                            "step_id": "G-005",
                            "slug": "api-surface",
                            "level": 3,
                            "status": "draft",
                        },
                        {
                            "path": "docs/plans/example/G-005-api-surface/T-006-step-commands/README.yaml",
                            "step_id": "T-006",
                            "slug": "step-commands",
                            "level": 4,
                            "status": "draft",
                        },
                    ],
                    "total": 2,
                    "limit": 50,
                    "offset": 0,
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
                "description": "List the first page of the step tree of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of the plan's steps as a flat, sorted list with statuses.",
            },
            {
                "description": "List the step tree with runtime parameters.",
                "command": {"plan": "plan_manager", "include_runtime": True},
                "explanation": "Includes runtime only when explicitly requested.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
            "GRAPH_CORRUPTED_CHAIN": {
                "description": "A level 4 or 5 step's parent_step_uuid does not resolve to any step row in the plan (a corrupted parent chain); step_tree computes each entry's path/parent_path/artifact_path by walking this chain for every node.",
                "message": "parent of step {step_id} not found in nodes",
                "solution": "Inspect the plan's step table for the named step_id and repair or remove the row with the dangling parent_step_uuid; this indicates data corruption, not a caller input error.",
            },
        },
        "best_practices": [
            "Use step_tree to discover valid step_id values before calling step_get, step_update, step_move, step_delete, or step_set_status.",
            "This command never mutates state; it is safe to call at any time and any status.",
            "Leave include_runtime false for ordinary topology reads and use it only when operational runtime data is needed.",
            "Compare offset+limit against total to detect additional pages.",
        ],
    }
