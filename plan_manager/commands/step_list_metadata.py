"""Extended AI/documentation metadata for the step_list command."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_metadata_params

def get_step_list_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepListCommand.

    Args:
        cls: The StepListCommand class object, used to source identity
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
            "Returns a flat, paginated listing of a plan's steps with full step "
            "fields (uuid, step_id, slug, level, project_id, status, parent_path, "
            "parent_uuid, fields, depends_on, concepts, path, artifact_path), "
            "filterable by level, parent, status, and target_file, with optional "
            "field projection via the fields parameter."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "level": {
                "description": "Optional filter by hierarchy level; one of 3, 4, 5.",
                "type": "integer",
                "required": False,
            },
            "parent": {
                "description": "Optional parent step reference to filter to direct children, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                "type": "string",
                "required": False,
            },
            "status": {
                "description": "Optional filter by step status; one of draft, ready_for_review, frozen, needs_review, in_progress, done.",
                "type": "string",
                "required": False,
            },
            "target_file": {
                "description": "Optional exact-match project-relative file path filter.",
                "type": "string",
                "required": False,
            },
            "fields": {
                "description": "Optional projection of entry key names to return.",
                "type": "array",
                "required": False,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of the plan's steps as a flat list with full fields, plus total count.",
                "data": {
                    "steps": "List of step entries with full fields (uuid, step_id, slug, level, project_id, status, parent_path, parent_uuid, depends_on, concepts, path, artifact_path), optionally projected to requested fields.",
                    "total": "Count of the full step list before pagination.",
                    "limit": "The applied (validated or defaulted) limit.",
                    "offset": "The applied (validated or defaulted) offset.",
                },
                "example": {
                    "steps": [
                        {
                            "uuid": "12345678-1234-1234-1234-123456789012",
                            "step_id": "G-005",
                            "slug": "api-surface",
                            "level": 3,
                            "project_id": "f06b7269-cc9c-4293-886b-24984e4033ba",
                            "status": "draft",
                            "parent_path": None,
                            "parent_uuid": None,
                            "path": "docs/plans/example/G-005-api-surface/README.yaml",
                            "artifact_path": None,
                            "depends_on": [],
                            "concepts": [],
                        },
                        {
                            "uuid": "87654321-4321-4321-4321-210987654321",
                            "step_id": "T-006",
                            "slug": "step-commands",
                            "level": 4,
                            "project_id": "f06b7269-cc9c-4293-886b-24984e4033ba",
                            "status": "draft",
                            "parent_path": "docs/plans/example/G-005-api-surface/README.yaml",
                            "parent_uuid": "12345678-1234-1234-1234-123456789012",
                            "path": "docs/plans/example/G-005-api-surface/T-006-step-commands/README.yaml",
                            "artifact_path": None,
                            "depends_on": [],
                            "concepts": [],
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
                "description": "List the first page of steps in a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of all steps in the plan with full fields.",
            },
            {
                "description": "List draft steps at level 5.",
                "command": {"plan": "plan_manager", "level": 5, "status": "draft"},
                "explanation": "Filters to only draft steps at hierarchy level 5.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "A parent step reference does not resolve to a step in the plan.",
                "message": "step not found: {parent}",
                "solution": "Retry with a valid parent step identifier from the plan.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A parent step reference is ambiguous or resolves to multiple steps.",
                "message": "ambiguous step id: {parent}",
                "solution": "Use a fully-qualified step path or UUID to disambiguate.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use the fields parameter to project only the step fields you need and reduce payload size.",
            "Use target_file to find all steps that touch or reference a given file.",
            "Combine level, parent, and status filters to efficiently discover relevant steps.",
            "This command never mutates state; it is safe to call at any time and any status.",
            "Compare offset + limit against total to detect additional pages.",
        ],
    }
