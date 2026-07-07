"""Metadata for the plan_list command."""

from typing import Any


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
            "Returns the database catalog of plans (C-001), ordered by "
            "name. Each row carries plan identity, name, status, context "
            "budget, whether the plan has a head revision, the analysis "
            "projects the plan is bound to (the full project_ids list, "
            "their count, and the primary project id), and a deleted flag. "
            "By default the catalog omits soft-deleted plans; pass "
            "show_deleted=true to include them (each such row has "
            "deleted=true). Soft-deleted plans remain fully operable and "
            "resolvable by uuid or name; they are only hidden from this "
            "default listing. This command is read-only: it never mutates "
            "the database."
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
        },
        "return_value": {
            "success": {
                "description": (
                    "The plan catalog, each row including the plan's bound "
                    "projects and soft-deletion flag."
                ),
                "data": {
                    "plans": (
                        "List of plan rows, each with uuid, name, status, "
                        "context_budget, has_head, project_ids, "
                        "project_count, primary_project_id, and deleted."
                    ),
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
                    ]
                },
            },
            "error": {
                "description": (
                    "This command declares no domain error codes: "
                    "list_plans does not raise mapped domain "
                    "exceptions, so any unexpected failure propagates "
                    "as a platform-level internal error rather than a "
                    "domain ErrorResult (map_exception re-raises "
                    "exceptions it does not recognize)."
                ),
                "code": "",
                "message": "",
            },
        },
        "usage_examples": [
            {
                "description": "List the live plan catalog with bound projects.",
                "command": {},
                "explanation": (
                    "Returns every plan that is not soft-deleted, each with "
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
            "none": {
                "description": (
                    "No stable domain error is declared for this command; "
                    "unexpected failures surface as platform-level internal errors."
                ),
                "message": "",
                "solution": "Retry after checking database connectivity and server logs.",
            },
        },
        "best_practices": [
            "Call plan_list to discover valid plan identifiers before calling plan_status or other plan-scoped commands.",
            "Read each row's primary_project_id and project_ids to see which analysis projects a plan is bound to.",
            "Use show_deleted=true to audit or recover soft-deleted plans; a row with deleted=true was removed from the default catalog by plan_delete.",
        ],
    }
