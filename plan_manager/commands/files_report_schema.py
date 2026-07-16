"""Machine-readable input schema for the files_report command."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_schema_properties

def get_files_report_schema() -> dict[str, Any]:
    """Return the machine-readable input schema for files_report.

    Returns:
        A JSON-Schema-shaped dict with type "object", the plan and scope
        string properties plus the shared uniform pagination properties
        (limit, offset), required ["plan"], and additionalProperties set
        to False.
    """
    properties: dict[str, Any] = {
        "plan": {
            "type": "string",
            "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
        },
        "scope": {
            "type": "string",
            "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
            "default": "whole_plan",
        },
    }
    properties.update(pagination_schema_properties())
    return {
        "type": "object",
        "properties": properties,
        "required": ["plan"],
        "additionalProperties": False,
    }
