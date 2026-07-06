"""Shared metadata builders for plan project binding commands."""

from typing import Any


def _base(cls: Any, detailed: str, parameters: dict, return_data: dict, examples: list[dict], errors: dict) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": detailed,
        "parameters": parameters,
        "return_value": {
            "success": {
                "description": "Project binding state for the resolved plan.",
                "data": return_data,
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "INVALID_PROJECT_ID",
                "message": "The supplied project_id is not a UUID.",
            },
        },
        "usage_examples": examples,
        "error_cases": errors,
        "best_practices": [
            "Bind projects at the plan level before assigning project_id to individual steps.",
            "Use project UUIDs from the analysis server; planmgr stores only the UUID anchor.",
        ],
    }


def _plan_param(required: bool = True) -> dict:
    return {
        "description": "Plan identifier resolved by UUID or unique name.",
        "type": "string",
        "required": required,
        "examples": ["workmgr"],
    }


def _project_param() -> dict:
    return {
        "description": "Analysis-server project UUID to bind, unbind, or make primary.",
        "type": "string",
        "required": True,
        "examples": ["4acd4be1-d166-417d-81c6-76bf77b4a392"],
    }


def get_plan_project_attach_metadata(cls: Any) -> dict:
    return _base(
        cls,
        "Attach an analysis-server project UUID to a plan. The command is idempotent: attaching an already-bound project returns already_exists=true instead of failing. With primary=true it also sets primary_project_id to that UUID.",
        {
            "plan": _plan_param(),
            "project_id": _project_param(),
            "primary": {
                "description": "When true, also set this project as the plan primary project.",
                "type": "boolean",
                "required": False,
                "default": False,
                "examples": [True, False],
            },
        },
        {
            "plan_uuid": "Plan UUID.",
            "project_ids": "All bound project UUIDs.",
            "primary_project_id": "Primary project UUID or null.",
            "already_exists": "Whether the project was already bound.",
        },
        [
            {
                "description": "Attach a project and make it primary.",
                "command": {
                    "plan": "workmgr",
                    "project_id": "4acd4be1-d166-417d-81c6-76bf77b4a392",
                    "primary": True,
                },
            }
        ],
        {
            "INVALID_PROJECT_ID": {"description": "project_id is not a UUID.", "message": "project_id must be a valid UUID.", "solution": "Retry with an analysis-server project UUID."},
            "PRIMARY_PROJECT_NOT_BOUND": {"description": "Primary project is not in project_ids.", "message": "primary_project_id must be present in project_ids.", "solution": "Attach the project first."},
        },
    )


def get_plan_project_detach_metadata(cls: Any) -> dict:
    return _base(
        cls,
        "Detach an analysis-server project UUID from a plan. Detaching clears primary_project_id when it matches and clears project_id on every GS/TS/AS step that pointed at the detached project.",
        {"plan": _plan_param(), "project_id": _project_param()},
        {
            "detached_project_id": "Detached project UUID.",
            "cleared_primary": "Whether primary_project_id was cleared.",
            "affected_steps": "Canonical step paths whose project_id was cleared.",
        },
        [
            {
                "description": "Detach a project and clear affected step bindings.",
                "command": {
                    "plan": "workmgr",
                    "project_id": "4acd4be1-d166-417d-81c6-76bf77b4a392",
                },
            }
        ],
        {
            "INVALID_PROJECT_ID": {"description": "project_id is not a UUID.", "message": "project_id must be a valid UUID.", "solution": "Retry with a UUID."},
            "PROJECT_NOT_ATTACHED_TO_PLAN": {"description": "Project is not attached to the plan.", "message": "project_id is not attached to plan.", "solution": "Call plan_project_list and retry with an attached project UUID."},
        },
    )


def get_plan_project_list_metadata(cls: Any) -> dict:
    return _base(
        cls,
        "Return the project UUIDs bound to a plan and the optional primary project UUID.",
        {"plan": _plan_param()},
        {
            "plan_uuid": "Plan UUID.",
            "project_ids": "All bound project UUIDs.",
            "primary_project_id": "Primary project UUID or null.",
        },
        [{"description": "List project bindings.", "command": {"plan": "workmgr"}}],
        {"PLAN_NOT_FOUND": {"description": "Plan cannot be resolved.", "message": "plan not found.", "solution": "Call plan_list and retry."}},
    )


def get_plan_project_set_primary_metadata(cls: Any) -> dict:
    return _base(
        cls,
        "Set the primary project for a plan. The project must already be present in plan.project_ids; this command never attaches it implicitly.",
        {"plan": _plan_param(), "project_id": _project_param()},
        {
            "plan_uuid": "Plan UUID.",
            "project_ids": "All bound project UUIDs.",
            "primary_project_id": "Primary project UUID.",
        },
        [
            {
                "description": "Set an attached project as primary.",
                "command": {
                    "plan": "workmgr",
                    "project_id": "4acd4be1-d166-417d-81c6-76bf77b4a392",
                },
            }
        ],
        {
            "INVALID_PROJECT_ID": {"description": "project_id is not a UUID.", "message": "project_id must be a valid UUID.", "solution": "Retry with a UUID."},
            "PROJECT_NOT_BOUND_TO_PLAN": {"description": "Project is not attached to the plan.", "message": "project_id is not bound to plan.", "solution": "Call plan_project_attach first."},
        },
    )


def get_plan_project_clear_primary_metadata(cls: Any) -> dict:
    return _base(
        cls,
        "Clear the plan primary project without changing plan.project_ids or any step-level project_id binding.",
        {"plan": _plan_param()},
        {
            "plan_uuid": "Plan UUID.",
            "project_ids": "All bound project UUIDs.",
            "primary_project_id": "Always null after success.",
        },
        [{"description": "Clear the primary project.", "command": {"plan": "workmgr"}}],
        {"PLAN_NOT_FOUND": {"description": "Plan cannot be resolved.", "message": "plan not found.", "solution": "Call plan_list and retry."}},
    )
