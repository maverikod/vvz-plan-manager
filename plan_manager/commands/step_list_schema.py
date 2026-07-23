"""JSON input schema for the step_list command (C-002, C-001), split into its own module per the complex-command companion layout."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_schema_properties
from plan_manager.commands.list_projection import view_schema_properties

def get_step_list_schema() -> dict[str, Any]:
    """Return the machine-readable JSON input schema for step_list.

    Returns:
        A JSON-Schema-shaped dict with type=object, a properties map for
        every parameter step_list.execute accepts (plan, level, parent,
        status, target_file, fields, and the pagination fields limit and
        offset), required=["plan"], and additionalProperties=False. The
        level property carries an enum of [3, 4, 5]; the status property
        carries the step lifecycle status enum (the union of the
        all-artifact statuses and the atomic-only statuses from the
        StatusModel); the fields property is an array of strings.
    """
    properties: dict[str, Any] = {
        "plan": {
            "type": "string",
            "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
        },
        "level": {
            "type": "integer",
            "description": "Optional hierarchy level to filter by. One of: 3, 4, 5.",
            "enum": [3, 4, 5],
        },
        "parent": {
            "type": "string",
            "description": "Optional parent step reference (UUID, canonical path, or unambiguous bare step_id); when given, only direct children of this step are included.",
        },
        "status": {
            "type": "string",
            "description": "Optional exact-match step status to filter by. One of: draft, ready_for_review, frozen, needs_review, in_progress, done (in_progress and done occur only on level-5 atomic steps).",
            "enum": ["draft", "ready_for_review", "frozen", "needs_review", "in_progress", "done"],
        },
        "target_file": {
            "type": "string",
            "description": "Optional exact-match project-relative file path to filter by, matched against fields.target_file (present only on level-5 steps).",
        },
        "fields": {
            "type": "array",
            "description": "Optional list of entry key names to project each returned step to; when omitted, every entry key is returned in full (or the view=summary default projection, see `view`). Valid names: uuid, step_id, slug, level, project_id, status, parent_path, parent_uuid, fields, depends_on, concepts, path, artifact_path. An explicit fields list always takes precedence over view.",
            "items": {"type": "string"},
        },
        **pagination_schema_properties(),
        **view_schema_properties(),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["plan"],
        "additionalProperties": False,
    }
