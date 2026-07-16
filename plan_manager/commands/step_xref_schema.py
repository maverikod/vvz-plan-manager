"""Machine-readable input schema for the step_xref command (C-005, C-001)."""

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_schema_properties

def get_step_xref_schema() -> dict[str, Any]:
    """Return the JSON-Schema-shaped input schema for step_xref.

    Returns:
        A dict with type, properties, required, and additionalProperties
        keys. The query mode is selected by the required `kind` enum:
        "signature" and "fragment" both fingerprint the literal `text`
        parameter; "field" fingerprints the named `field` of the
        referenced `step`. The pagination properties (limit, offset)
        follow the uniform convention (C-001).
    """
    properties = {
        "plan": {
            "type": "string",
            "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
        },
        "kind": {
            "type": "string",
            "description": "Query mode. 'signature' and 'fragment' fingerprint the literal text parameter; 'field' fingerprints the named field of the referenced step.",
            "enum": ["signature", "fragment", "field"],
        },
        "text": {
            "type": "string",
            "description": "Literal signature or text fragment to fingerprint. Required when kind is 'signature' or 'fragment'; must be omitted when kind is 'field'.",
        },
        "step": {
            "type": "string",
            "description": "Step reference (UUID, canonical path, or bare step_id) whose field supplies the query fingerprint. Required when kind is 'field'; must be omitted otherwise.",
        },
        "field": {
            "type": "string",
            "description": "Field name (a key of the referenced step's fields) supplying the query fingerprint. Required when kind is 'field'; must be omitted otherwise.",
        },
        **pagination_schema_properties(),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["plan", "kind"],
        "additionalProperties": False,
    }
