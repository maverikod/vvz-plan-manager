"""Metadata for the plan_list command."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_metadata_params
from plan_manager.commands.list_projection import view_metadata_params

def get_plan_list_metadata(cls: Any) -> dict:
    """Return the full metadata dictionary for PlanListCommand.

    Args:
        cls: The PlanListCommand class, providing name, version, descr,
            category, author, email class attributes.

    Returns:
        dict: Metadata dictionary conforming to metadatastd.yaml
            required_fields: name, version, description, category,
            author, email, detailed_description, parameters,
            return_value, usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns one paginated page of the database catalog of plans "
            "(C-001), ordered by name, using the uniform offset/limit "
            "convention (default limit 50, max 200). Each row carries plan "
            "identity, name, status, context budget, whether the plan has a "
            "head revision, the analysis projects the plan is bound to (the "
            "full project_ids list, their count, and the primary project "
            "id), and a deleted flag. By default the catalog omits "
            "soft-deleted plans; pass show_deleted=true to include them "
            "(each such row has deleted=true). Soft-deleted plans remain "
            "fully operable and resolvable by uuid or name; they are only "
            "hidden from this default listing. This command is read-only: "
            "it never mutates the database."
        ),
        "parameters": {
            "show_deleted": {
                "description": (
                    "When true, include soft-deleted plans in the catalog. "
                    "When false or omitted, soft-deleted plans are hidden."
                ),
                "type": "boolean",
                "required": False,
                "default": False,
                "examples": [False, True],
            },
            **pagination_metadata_params(),
            **view_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": (
                    "A page of the plan catalog, each row including the plan's bound "
                    "projects and soft-deletion flag, plus total/limit/offset."
                ),
                "data": {
                    "plans": (
                        "List of plan rows in the requested page, each with uuid, name, status, "
                        "context_budget, has_head, project_ids, "
                        "project_count, primary_project_id, and deleted."
                    ),
                    "total": "Count of the full plan catalog before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "plans": [
                        {
                            "uuid": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                            "name": "my-plan",
                            "status": "draft",
                            "context_budget": 4000,
                            "has_head": False,
                            "project_ids": [
                                "4acd4be1-d166-417d-81c6-76bf77b4a392"
                            ],
                            "project_count": 1,
                            "primary_project_id": (
                                "4acd4be1-d166-417d-81c6-76bf77b4a392"
                            ),
                            "deleted": False,
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": (
                    "Unexpected failures propagate as a platform-level "
                    "internal error, except INVALID_PAGINATION which is "
                    "returned as a domain ErrorResult when limit or offset "
                    "is out of range or not an integer."
                ),
                "code": "INVALID_PAGINATION",
                "message": "limit must be between 1 and 200, got {limit}",
            },
        },
        "usage_examples": [
            {
                "description": "List the first page of the live plan catalog with bound projects.",
                "command": {},
                "explanation": (
                    "Returns the first page (default limit 50) of plans that are not soft-deleted, each with "
                    "its bound project_ids and primary_project_id."
                ),
            },
            {
                "description": "Include soft-deleted plans in the listing.",
                "command": {"show_deleted": True},
                "explanation": (
                    "Returns all plans; soft-deleted rows are marked with "
                    "deleted=true."
                ),
            },
        ],
        "error_cases": {
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Call plan_list to discover valid plan identifiers before calling plan_status or other plan-scoped commands.",
            "Read each row's primary_project_id and project_ids to see which analysis projects a plan is bound to.",
            "Use show_deleted=true to audit or recover soft-deleted plans; a row with deleted=true was removed from the default catalog by plan_delete.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary returns a compact per-row projection (uuid, name, status, primary_project_id, deleted) instead of the full row (drops context_budget, has_head, project_ids, project_count, completed, comment); use plan_status for a single plan's full detail.",
        ],
    }
