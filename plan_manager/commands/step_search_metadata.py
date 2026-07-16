"""Extended AI/documentation metadata for the step_search command."""

from typing import Any


def get_step_search_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for StepSearchCommand.

    Args:
        cls: The StepSearchCommand class (passed by its classmethod metadata()).

    Returns:
        A metadata dictionary with keys name, version, description, category,
        author, email, detailed_description, parameters, return_value,
        usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Searches step content for an exact substring or a regular expression "
            "across every searchable text field of a step: name and description for "
            "global and tactical steps; name, target_file, prompt, and the "
            "verification target and expected text for atomic steps. Accepts a "
            "search scope of either the whole plan or one branch (a global step, its "
            "tactical step, and its atomic step, named together by their three step "
            "ids), and returns, for every match, the matching step's path, the name "
            "of the matched field, and a bounded context excerpt drawn from the "
            "surrounding text. Read-only: never mutates plan state."
        ),
        "parameters": {
            "plan": {
                "type": "string",
                "required": True,
                "description": "Plan identifier (UUID or unique plan name) resolved against the catalog.",
            },
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Substring or regular expression to search for (max 200 characters).",
            },
            "mode": {
                "type": "string",
                "required": False,
                "enum": ["substring", "regex"],
                "default": "substring",
                "description": "Search mode: exact substring match or regular-expression match.",
            },
            "scope": {
                "type": "string",
                "required": False,
                "enum": ["plan", "branch"],
                "default": "plan",
                "description": "Search scope: the whole plan or one branch named by its three step ids.",
            },
            "gs_step_id": {
                "type": "string",
                "required": False,
                "description": "Global step id (e.g. G-005) of the branch. Required when scope is 'branch'.",
            },
            "ts_step_id": {
                "type": "string",
                "required": False,
                "description": "Tactical step id (e.g. T-009) of the branch. Required when scope is 'branch'.",
            },
            "as_step_id": {
                "type": "string",
                "required": False,
                "description": "Atomic step id (e.g. A-101) of the branch. Required when scope is 'branch'.",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": "Maximum number of results to return (default 50, max 200).",
            },
            "offset": {
                "type": "integer",
                "required": False,
                "description": "Number of results to skip before returning results (default 0).",
            },
        },
        "return_value": {
            "success": {
                "description": "A bounded page of step-content search matches, plus total_count.",
                "data": {
                    "matches": "List of match entries; each has path, field, excerpt.",
                    "total_count": "Total number of matches found across the requested scope, before pagination.",
                },
                "example": {
                    "matches": [
                        {"path": "G-002/T-002/A-001", "field": "prompt", "excerpt": "...needle..."},
                    ],
                    "total_count": 1,
                },
            },
            "error": {
                "description": "Error result with a stable domain code.",
                "code": "stable error code string (PLAN_NOT_FOUND, STEP_NOT_FOUND, INVALID_FILTER, or INVALID_PAGINATION)",
                "message": "human-readable message",
                "details": "additional diagnostic fields when available",
            },
        },
        "usage_examples": [
            {
                "description": "Search the whole plan for a literal substring.",
                "command": {"plan": "plan-manager", "pattern": "needle"},
                "explanation": "Returns the first page of matches for the literal substring 'needle' across every searchable field of the plan.",
            },
            {
                "description": "Search one branch with a regular expression.",
                "command": {
                    "plan": "plan-manager",
                    "pattern": "foo.*bar",
                    "mode": "regex",
                    "scope": "branch",
                    "gs_step_id": "G-002",
                    "ts_step_id": "T-002",
                    "as_step_id": "A-001",
                },
                "explanation": "Returns matches of the regular expression restricted to the named branch.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "List plans and retry with a valid plan identifier or UUID.",
            },
            "STEP_NOT_FOUND": {
                "description": "scope is 'branch' and the named gs_step_id, ts_step_id, as_step_id do not resolve to an existing branch.",
                "message": "no step found at level <level> with step_id '<id>'",
                "solution": "Verify the gs_step_id, ts_step_id, and as_step_id name an existing branch, then retry.",
            },
            "INVALID_FILTER": {
                "description": "mode is 'regex' and pattern fails to compile, pattern exceeds the maximum length, or the branch step ids are inconsistent with scope.",
                "message": "invalid regular expression: <detail>",
                "solution": "Fix the pattern syntax, shorten it to at most 200 characters, or supply/withhold the branch step ids consistently with scope.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use step_search before step_get when the exact step path is unknown.",
            "step_search never mutates plan state; safe to call at any plan or cascade status.",
            "Prefer scope='branch' with all three step ids to narrow a search once the branch is known.",
            "Compare offset+limit against total_count to detect additional pages.",
        ],
    }
