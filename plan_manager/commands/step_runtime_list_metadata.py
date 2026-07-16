"""Metadata for step_runtime_list."""

from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params

def get_step_runtime_list_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Lists one paginated page of runtime records for every step in a "
            "whole plan, one G-NNN scope, or one G-NNN/T-NNN scope, using the "
            "uniform offset/limit convention (default limit 50, max 200). "
            "SHAPE CHANGE: the response is an artifact_path-sorted list of "
            "{artifact_path, step_id, runtime} items plus total/limit/offset; "
            "it replaced the former map keyed by artifact path. The command "
            "returns an entry for every step in scope, including steps that "
            "have no runtime row yet; those receive an empty runtime record."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                "type": "string",
                "required": False,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of runtime records as an artifact_path-sorted item list, plus total/limit/offset.",
                "data": {
                    "runtime": "List of {artifact_path, step_id, runtime} items sorted by artifact_path.",
                    "total": "Count of the full in-scope step set before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "runtime": [
                        {
                            "artifact_path": "G-001/T-001/A-001",
                            "step_id": "A-001",
                            "runtime": {
                                "activations": [],
                                "execution_attempts": [],
                                "journal_aggregates": None,
                                "authoring": None,
                            },
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Plan or scope could not be resolved, or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND | INVALID_PAGINATION",
                "message": "Human-readable error message.",
                "details": "Domain error details when available.",
            },
        },
        "usage_examples": [
            {
                "description": "List runtime records for one tactical branch.",
                "command": {"plan": "plan_manager", "scope": "G-001/T-001"},
                "explanation": "Returns the first page (default limit 50) covering the tactical step and its atomic children.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan.",
            },
            "STEP_NOT_FOUND": {
                "description": "The scope is invalid or missing.",
                "message": "scope not found: {scope}",
                "solution": "Call step_tree to discover valid scope identifiers.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use scope for dashboards focused on one branch.",
            "Do not treat absence of runtime rows as absence of steps; empty records are intentional.",
            "The response shape changed from a map keyed by artifact path to a paginated, artifact_path-sorted list of {artifact_path, step_id, runtime} items; update consumers accordingly.",
            "Compare offset+limit against total to detect additional pages.",
        ],
    }
