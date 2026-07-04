"""Metadata for the plan_create command."""

from typing import Any


def get_plan_create_metadata(cls: Any) -> dict:
    """Return the full metadata dictionary for PlanCreateCommand.

    Args:
        cls: The PlanCreateCommand class, providing name, version, descr,
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
            "Creates a new plan aggregate (C-001) at revision zero with "
            "empty HRS and MRS. The plan name must be unique across the "
            "catalog; a duplicate name is rejected with the DUPLICATE_ID "
            "domain code. The context budget in tokens governs prompt "
            "assembly for this plan and defaults to 4000 when omitted; "
            "an empty name or a context_budget below 1 is rejected as a "
            "parameter-shape violation before any database access. This "
            "command mutates the database: it verifies its own result by "
            "re-reading the created plan row before returning. There is "
            "no dry-run mode; plan creation has no partial or "
            "destructive side effects to preview."
        ),
        "parameters": {
            "name": {
                "description": (
                    "Unique plan name. Must be non-empty after "
                    "stripping surrounding whitespace."
                ),
                "type": "string",
                "required": True,
                "examples": ["my-plan"],
            },
            "context_budget": {
                "description": (
                    "Context budget in tokens consumed by prompt "
                    "assembly. Must be an integer >= 1."
                ),
                "type": "integer",
                "required": False,
                "default": 4000,
                "examples": [4000, 8000],
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "The created plan identity, verified by re-reading "
                    "the stored row after creation."
                ),
                "data": {
                    "uuid": "Plan UUID as a string.",
                    "name": "Plan name as stored.",
                    "status": "Plan lifecycle status immediately after creation.",
                    "context_budget": "Context budget in tokens as stored.",
                },
                "example": {
                    "uuid": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                    "name": "my-plan",
                    "status": "draft",
                    "context_budget": 4000,
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "DUPLICATE_ID",
                "message": "A plan with this name already exists.",
            },
        },
        "usage_examples": [
            {
                "description": "Create a plan with the default context budget.",
                "command": {"name": "my-plan"},
                "explanation": "Creates a plan named 'my-plan' with context_budget 4000.",
            },
            {
                "description": "Create a plan with an explicit context budget.",
                "command": {"name": "my-plan", "context_budget": 8000},
                "explanation": "Creates a plan named 'my-plan' with context_budget 8000.",
            },
        ],
        "error_cases": {
            "DUPLICATE_ID": {
                "description": "The requested plan name already exists in the catalog.",
                "message": "A plan with this name already exists.",
                "solution": "Call plan_list to inspect existing names and retry with a unique name.",
            },
        },
        "best_practices": [
            "Call plan_list first to confirm the desired name is not already taken.",
            "Use the default context_budget of 4000 unless prompt assembly for this plan is known to need more headroom.",
            "After creation, use the returned uuid for all subsequent operations on this plan.",
        ],
    }
