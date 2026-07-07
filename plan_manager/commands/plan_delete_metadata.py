"""Metadata for the plan_delete command."""

from typing import Any


def get_plan_delete_metadata(cls: Any) -> dict:
    """Return the full metadata dictionary for PlanDeleteCommand.

    Args:
        cls: The PlanDeleteCommand class, providing name, version, descr,
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
            "Deletes a plan aggregate (C-001), resolved by UUID or unique "
            "name, in one of two modes. The default soft delete marks the "
            "plan deleted (stamping its deletion time) so it is hidden from "
            "the default plan_list catalog while remaining fully preserved: "
            "the plan and all of its artifacts stay in the database, the "
            "plan stays resolvable by uuid or name, and every other command "
            "keeps operating on it unchanged. Soft delete is idempotent — "
            "deleting an already soft-deleted plan reports already_deleted "
            "true and never overwrites the original deletion time. The hard "
            "delete mode (hard=true) removes the plan row permanently and "
            "irreversibly; every artifact belonging to the plan (revisions, "
            "paragraphs, concepts, relations, steps, node versions, refs, "
            "cascades, step runtime, and context blocks) is removed with it "
            "through the database's ON DELETE CASCADE foreign keys, and "
            "hard delete applies whether or not the plan was previously "
            "soft-deleted. This command mutates the database and verifies "
            "its own result by re-reading the plan row after the operation: "
            "soft delete confirms the deletion mark is present, hard delete "
            "confirms the row is gone. A missing plan is reported with the "
            "PLAN_NOT_FOUND domain code before any deletion is attempted. "
            "There is no dry-run mode; use plan_list (show_deleted=true) to "
            "inspect soft-deleted plans, and note that soft delete keeps the "
            "plan name reserved by the catalog's uniqueness constraint."
        ),
        "parameters": {
            "plan": {
                "description": (
                    "Plan identifier: either the plan UUID or its unique "
                    "name. Soft-deleted plans remain resolvable by both."
                ),
                "type": "string",
                "required": True,
                "examples": [
                    "my-plan",
                    "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                ],
            },
            "hard": {
                "description": (
                    "Deletion mode. False (the default) soft-deletes: the "
                    "plan is hidden from the default catalog but preserved "
                    "and reversible. True hard-deletes: the plan and all of "
                    "its artifacts are removed permanently and irreversibly."
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
                    "The deleted plan identity and the mode applied, "
                    "verified by re-reading the plan row after deletion."
                ),
                "data": {
                    "uuid": "Plan UUID as a string.",
                    "name": "Plan name as stored.",
                    "mode": "The deletion mode applied: 'soft' or 'hard'.",
                    "deleted": (
                        "Always True on success; for soft delete it "
                        "reflects the re-read deletion mark."
                    ),
                    "already_deleted": (
                        "Soft delete only: True when the plan was already "
                        "soft-deleted before this call (idempotent no-op)."
                    ),
                },
                "example": {
                    "uuid": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                    "name": "my-plan",
                    "mode": "soft",
                    "deleted": True,
                    "already_deleted": False,
                },
            },
            "error": {
                "description": (
                    "A domain error result carrying a stable string code."
                ),
                "code": "PLAN_NOT_FOUND",
                "message": "plan not found: my-plan",
            },
        },
        "usage_examples": [
            {
                "description": "Soft-delete a plan (hide it from the catalog).",
                "command": {"plan": "my-plan"},
                "explanation": (
                    "Marks 'my-plan' deleted; it disappears from plan_list "
                    "unless show_deleted=true, but stays fully operable."
                ),
            },
            {
                "description": "Permanently delete a plan and all its artifacts.",
                "command": {"plan": "my-plan", "hard": True},
                "explanation": (
                    "Irreversibly removes 'my-plan' and every child artifact "
                    "via ON DELETE CASCADE."
                ),
            },
            {
                "description": "Purge a plan already soft-deleted.",
                "command": {
                    "plan": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                    "hard": True,
                },
                "explanation": (
                    "Hard delete applies regardless of prior soft deletion, "
                    "removing the plan row permanently."
                ),
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": (
                    "No plan matches the given UUID or name. Note that a "
                    "soft-deleted plan is still found and can be deleted "
                    "again (soft, idempotently) or hard-deleted."
                ),
                "message": "plan not found: <identifier>",
                "solution": (
                    "Call plan_list (with show_deleted=true to include "
                    "soft-deleted plans) to confirm the identifier, then "
                    "retry."
                ),
            },
        },
        "best_practices": [
            "Prefer soft delete (the default) for routine removal; it is reversible and keeps history and bound projects intact.",
            "Use plan_list with show_deleted=true to review or recover soft-deleted plans before purging them.",
            "Reserve hard delete for permanent purges; it is irreversible and cascades to every artifact belonging to the plan.",
            "Remember that a soft-deleted plan keeps its name reserved; hard-delete it first if you must reuse the exact name.",
        ],
    }
