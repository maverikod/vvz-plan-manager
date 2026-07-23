"""Extended metadata for the cascade_preview command."""

from plan_manager.commands.cascade_preview_projection import (
    CATEGORY_VALUES,
    category_metadata_params,
    view_metadata_params,
)
from plan_manager.commands.runtime_filtering import filter_metadata_params, pagination_metadata_params
from plan_manager.verify.gate import GATE_CHECK_SEMANTICS


def get_cascade_preview_metadata(cls: type) -> dict:
    """Return the extended documentation metadata for CascadePreviewCommand.

    Args:
        cls: The CascadePreviewCommand class supplying identity attributes
            (name, version, descr, category, author, email).

    Returns:
        A dictionary with all fields required by the command metadata
        standard: name, version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the mechanical gate verdict of the plan's currently open "
            "cascade plus a fixed 5-category summary-count dashboard (added, "
            "removed, changed, needs_review, gate_findings) by default "
            "(view=summary; todo 3c762bfe fixed the prior default, which "
            "embedded the raw unbounded change_set and blew the caller "
            "output budget on large cascades). view=full additionally "
            "returns a bounded, filterable, paginated 'entries' page: the "
            "change set, the needs_review blast radius, and the flattened "
            "mechanical gate findings unified into one deterministically "
            "ordered collection, each entry tagged by its 'category'. This "
            "command is read-only: it never mutates the cascade record, the "
            "plan, or any other database state. There is no dry_run or undo "
            "concept for a read-only command. Verify: run cascade_preview "
            "again after further edits to see the updated counts/entries "
            "and gate verdict; the gate verdict returned here gates whether "
            "cascade_commit will accept the cascade."
        ),
        "gate_check_semantics": dict(GATE_CHECK_SEMANTICS),
        "parameters": {
            "plan": {
                "description": "Plan UUID or unique plan name.",
                "type": "string",
                "required": True,
            },
            **view_metadata_params(),
            **pagination_metadata_params(),
            **category_metadata_params(),
            **filter_metadata_params(["entity_type", "step", "status"]),
        },
        "return_value": {
            "success": {
                "description": (
                    "view=summary (default): cascade_uuid, base_revision_uuid, "
                    "tip_revision_uuid, gate_green, and a 'summary' dict of "
                    "5 fixed counts. view=full: the same fields plus "
                    "'entries' (the current bounded/filtered page), 'total' "
                    "(the filtered match count), 'limit', 'offset', and "
                    "'gate_report_json' (the full mechanical gate report, "
                    "unchanged shape, for callers already parsing it)."
                ),
                "data": {
                    "cascade_uuid": "UUID of the open cascade.",
                    "base_revision_uuid": (
                        "UUID of the plan head revision the cascade is "
                        "anchored to."
                    ),
                    "tip_revision_uuid": (
                        "UUID of the latest revision recorded inside the "
                        "cascade."
                    ),
                    "gate_green": (
                        "Boolean: whether the mechanical gate passed for "
                        "the cascade's current state."
                    ),
                    "summary": (
                        "Dict with integer keys 'added', 'removed', "
                        "'changed', 'needs_review', 'gate_findings' -- the "
                        "cascade's real totals, independent of any detail "
                        "filter or page."
                    ),
                    "entries": (
                        "view=full only: the current page of unified "
                        "detail entries, each a dict with a 'category' key "
                        "(one of " + ", ".join(CATEGORY_VALUES) + ") plus "
                        "category-specific fields: 'entity_uuid', "
                        "'entity_type', 'step_path', 'step_status' for "
                        "added/removed/changed/needs_review; 'fields' "
                        "(changed top-level content keys) additionally for "
                        "'changed'; 'check_id', 'severity', 'artifact_path', "
                        "'message' for 'gate_finding'."
                    ),
                    "total": "view=full only: count of entries matching the current filters (pre-pagination).",
                    "limit": "view=full only: the page size actually applied.",
                    "offset": "view=full only: the offset actually applied.",
                    "gate_report_json": (
                        "view=full only: JSON string of the full mechanical "
                        "gate report. See the top-level 'gate_check_semantics' "
                        "metadata field for a one-line gloss of what each "
                        "check_id actually means before interpreting a finding."
                    ),
                },
                "example": {
                    "cascade_uuid": "6f1c2e2a-1111-4a2b-9c3d-4e5f6a7b8c9d",
                    "base_revision_uuid": (
                        "1a2b3c4d-5e6f-4071-8899-aabbccddeeff"
                    ),
                    "tip_revision_uuid": (
                        "2b3c4d5e-6f70-4182-99aa-bbccddeeff00"
                    ),
                    "gate_green": True,
                    "summary": {
                        "added": 1,
                        "removed": 0,
                        "changed": 0,
                        "needs_review": 0,
                        "gate_findings": 0,
                    },
                },
            },
            "error": {
                "description": "Domain error result on failure.",
                "code": "Stable domain error code string (see error_cases).",
                "message": "Human-readable error message.",
                "details": "Optional diagnostic fields, present when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Compact default: summary counts only.",
                "command": {"plan": "plan-manager"},
                "explanation": (
                    "Returns cascade_uuid/base/tip, gate_green, and the "
                    "5-category summary counts; no raw change_set or "
                    "findings are embedded."
                ),
            },
            {
                "description": "Full detail, first page of gate findings only.",
                "command": {"plan": "plan-manager", "view": "full", "category": "gate_finding", "limit": 50, "offset": 0},
                "explanation": (
                    "Returns up to 50 gate_finding entries plus 'total' so "
                    "the caller can page through the rest via offset."
                ),
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan parameter does not resolve to any plan.",
                "message": "Plan not found: {plan}",
                "solution": (
                    "List existing plans and retry with a valid plan UUID "
                    "or name."
                ),
            },
            "CASCADE_REQUIRED": {
                "description": "The plan has no open cascade to preview.",
                "message": "Plan {plan} has no open cascade.",
                "solution": "Call cascade_begin to open a cascade first.",
            },
            "INVALID_FILTER": {
                "description": "view or category is not one of its accepted values.",
                "message": "category must be one of [...], got {value!r}",
                "solution": "Retry with view in {full, summary} and category one of " + ", ".join(CATEGORY_VALUES) + ".",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Call cascade_preview before cascade_commit to confirm the "
            "gate is green and the summary counts match expectations.",
            "Use view=full with category='needs_review' to page through "
            "artifacts requiring manual attention before committing.",
            "Use view=full with category='gate_finding' (optionally plus "
            "check_id) to page through mechanical gate findings instead of "
            "parsing gate_report_json for large cascades.",
            "Compare offset+limit against total to detect additional pages.",
            "cascade_preview is safe to call repeatedly; it never mutates "
            "state.",
        ],
    }
