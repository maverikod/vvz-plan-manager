"""Metadata for the step_xref command (C-005)."""

from typing import Any


def get_step_xref_metadata(cls: type) -> dict[str, Any]:
    """Return the full metadata dictionary for StepXrefCommand.

    Args:
        cls: The StepXrefCommand class, providing name, version, descr,
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
            "Cross-reference report over per-field content fingerprints (C-005): "
            "for a literal text/signature fragment, or for a named field of an existing step, "
            "reports every (step path, field name) location where that exact content appears, "
            "with the first location in canonical plan order marked 'defined' and every subsequent "
            "identical occurrence marked 'inlined'."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "text": {
                "description": "Literal text or signature fragment to search for across the plan. Either text or step must be provided.",
                "type": "string",
                "required": False,
            },
            "step": {
                "description": "Step identifier (path or uuid) to use for field-level cross-reference. Either text or step must be provided.",
                "type": "string",
                "required": False,
            },
            "field": {
                "description": "When step is provided, the field name within that step whose content will be cross-referenced.",
                "type": "string",
                "required": False,
            },
            "limit": {
                "description": "Maximum number of locations to return per page (default 50, max 200).",
                "type": "integer",
                "required": False,
                "default": 50,
            },
            "offset": {
                "description": "Number of locations to skip before returning results (default 0).",
                "type": "integer",
                "required": False,
                "default": 0,
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "A page of cross-reference locations where the specified content is found, "
                    "each marked as 'defined' (first occurrence) or 'inlined' (subsequent occurrences), "
                    "plus total/limit/offset."
                ),
                "data": {
                    "locations": (
                        "List of (step path, field name, role) tuples in canonical plan order, "
                        "where role is either 'defined' or 'inlined'."
                    ),
                    "total_count": "Count of all matching locations across the plan before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                },
                "example": {
                    "locations": [
                        {
                            "path": "G-002/T-004/atomic_steps/A-001-prompt.yaml",
                            "field": "name",
                            "role": "defined",
                            "content_hash": "abc123def456",
                        },
                        {
                            "path": "G-002/T-004/atomic_steps/A-002-implementation.yaml",
                            "field": "description",
                            "role": "inlined",
                            "content_hash": "abc123def456",
                        },
                    ],
                    "total_count": 2,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": (
                    "Domain error returned when the plan cannot be resolved, the step/field cannot be found, "
                    "the query is ambiguous or invalid, or pagination is out of range."
                ),
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND | AMBIGUOUS_STEP_ID | INVALID_FILTER | INVALID_PAGINATION",
                "message": "Human-readable message identifying the error condition.",
                "details": "Additional context specific to the error type (e.g., available steps for ambiguous queries).",
            },
        },
        "usage_examples": [
            {
                "description": "Find all locations where a specific text fragment appears across the plan.",
                "command": {
                    "plan": "plan_manager",
                    "text": "dependency graph",
                },
                "explanation": (
                    "Returns all (step path, field name) locations where 'dependency graph' appears, "
                    "with the first occurrence marked 'defined' and others marked 'inlined'."
                ),
            },
            {
                "description": "Cross-reference a specific field of a step to find all identical content.",
                "command": {
                    "plan": "plan_manager",
                    "step": "G-002/T-004/A-001",
                    "field": "name",
                },
                "explanation": (
                    "Extracts the 'name' field from step G-002/T-004/A-001, then reports every location "
                    "in the plan where that exact text appears, marking the original step as 'defined'."
                ),
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "The step identifier provided does not exist in the plan.",
                "message": "step not found: {step}",
                "solution": "Use graph_order or step_list to verify valid step identifiers within the plan.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "The step identifier matches multiple steps in the plan.",
                "message": "ambiguous step identifier: {step}; matches {count} steps",
                "solution": "Provide a fully qualified step path or uuid to disambiguate.",
            },
            "INVALID_FILTER": {
                "description": "Neither text nor step parameter was provided, or step was provided without field.",
                "message": "invalid filter: either text or (step with field) must be provided",
                "solution": "Provide either a text fragment to search, or both step and field parameters.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use text search for broad content discovery; use step+field for precise cross-referencing.",
            "Check the 'defined' role to find the canonical location; 'inlined' locations are reuses.",
            "When a step identifier is ambiguous, use the fully qualified artifact path to disambiguate.",
            "Compare offset+limit against total_count to detect additional pages.",
            "Use content_hash to programmatically detect and deduplicate identical fragments.",
        ],
    }
