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
            "Returns the database catalog of all plans (C-001). Each "
            "row carries plan identity, name, status, context budget, "
            "and whether the plan has a head revision. This command is "
            "read-only: it never mutates the database and takes no "
            "parameters."
        ),
        "parameters": {},
        "return_value": {
            "success": {
                "description": "The catalog of all plans.",
                "data": {
                    "plans": (
                        "List of plan rows, each with uuid, name, "
                        "status, context_budget, and has_head."
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
                "description": "List all plans in the catalog.",
                "command": {},
                "explanation": "Returns every plan row currently stored.",
            }
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
        ],
    }
