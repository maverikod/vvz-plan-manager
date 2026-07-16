"""Machine-readable input schema for the step_search command."""

from typing import Any

MAX_PATTERN_LENGTH: int = 200

def get_step_search_schema() -> dict[str, Any]:
    """Return the machine-readable input schema for step_search.

    Returns:
        A JSON-Schema-shaped dict with type "object", a properties entry
        for every parameter accepted by StepSearchCommand.execute, the
        required list, an explicit additionalProperties=False, and enum
        vocabularies for the fixed-value mode and scope parameters.
    """
    return {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "Plan identifier (UUID or name) resolved against the catalog.",
            },
            "pattern": {
                "type": "string",
                "description": f"Substring or regular expression to search for (max {MAX_PATTERN_LENGTH} characters).",
            },
            "mode": {
                "type": "string",
                "enum": ["substring", "regex"],
                "default": "substring",
                "description": "Search mode: exact substring match or regular-expression match.",
            },
            "scope": {
                "type": "string",
                "enum": ["plan", "branch"],
                "default": "plan",
                "description": "Search scope: the whole plan or one branch named by its three step ids.",
            },
            "gs_step_id": {
                "type": "string",
                "description": "Global step id (e.g. G-005) of the branch. Required when scope is 'branch'.",
            },
            "ts_step_id": {
                "type": "string",
                "description": "Tactical step id (e.g. T-009) of the branch. Required when scope is 'branch'.",
            },
            "as_step_id": {
                "type": "string",
                "description": "Atomic step id (e.g. A-101) of the branch. Required when scope is 'branch'.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default 50, max 200).",
                "minimum": 1,
                "maximum": 200,
            },
            "offset": {
                "type": "integer",
                "description": "Number of results to skip before returning results (default 0).",
                "minimum": 0,
            },
        },
        "required": ["plan", "pattern"],
        "additionalProperties": False,
    }
