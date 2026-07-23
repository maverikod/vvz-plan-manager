"""Response projection for cascade_preview: category/check_id filter parsing
and paginated-detail filtering over the unified entries collection built by
plan_manager.cascade.preview.build_preview_entries (todo 3c762bfe).
"""

from __future__ import annotations

from typing import Any

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.list_projection import VIEW_SUMMARY, VIEW_VALUES

# cascade_preview reuses the list-family's full/summary VIEW_VALUES vocabulary
# and parse_view() validator (list_projection), but NOT its packaged
# view_schema_properties()/view_metadata_params(): those hardcode
# default="full" and per-row list-projection wording, both wrong here --
# the spec (todo 3c762bfe) mandates default="summary" for THIS command, and
# cascade_preview is a single-record report, not a list of rows.
_VIEW_DESCRIPTION: str = (
    "Response shape. 'summary' (default; todo 3c762bfe) returns only "
    "cascade_uuid/base/tip, gate_green, and the fixed 5-category summary "
    "counts -- no raw change_set, needs_review list, or gate findings are "
    "embedded. 'full' additionally returns the paginated/filterable "
    "'entries' detail page (see limit/offset/category/check_id/entity_type/"
    "step/status) plus gate_report_json. One of: " + ", ".join(VIEW_VALUES) + "."
)

_VIEW_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(VIEW_VALUES),
    "default": VIEW_SUMMARY,
    "description": _VIEW_DESCRIPTION,
}

_VIEW_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _VIEW_DESCRIPTION,
    "required": False,
    "enum": list(VIEW_VALUES),
}


def view_schema_properties() -> dict[str, Any]:
    """Return the JSON-schema `properties` fragment for cascade_preview's `view` param."""
    return {"view": dict(_VIEW_SCHEMA_PROPERTY)}


def view_metadata_params() -> dict[str, Any]:
    """Return the AI-metadata `parameters` fragment for cascade_preview's `view` param."""
    return {"view": dict(_VIEW_METADATA_PARAM)}


CATEGORY_VALUES: tuple[str, ...] = ("added", "removed", "changed", "needs_review", "gate_finding")

_CATEGORY_DESCRIPTION: str = (
    "Restrict paginated detail entries to one category: 'added'/'removed'/'changed' "
    "(change-set membership vs. the cascade's base revision), 'needs_review' "
    "(blast-radius steps), or 'gate_finding' (flattened mechanical gate findings). "
    "Omit to include every category. Only applies when view=full; view=summary never "
    "returns entries regardless of this filter. One of: " + ", ".join(CATEGORY_VALUES) + "."
)

CATEGORY_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(CATEGORY_VALUES),
    "description": _CATEGORY_DESCRIPTION,
}

CATEGORY_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _CATEGORY_DESCRIPTION,
    "required": False,
    "enum": list(CATEGORY_VALUES),
}

_CHECK_ID_DESCRIPTION: str = (
    "Restrict gate_finding detail entries to one mechanical-gate check_id (e.g. "
    "'coverage.gs'), the 'review/gate category' filter dimension; has no effect on "
    "entries of any other category. Only applies when view=full."
)

CHECK_ID_SCHEMA_PROPERTY: dict[str, Any] = {"type": "string", "description": _CHECK_ID_DESCRIPTION}

CHECK_ID_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _CHECK_ID_DESCRIPTION,
    "required": False,
}


def category_schema_properties() -> dict[str, Any]:
    """Return the JSON-schema `properties` fragment for `category` and `check_id`."""
    return {"category": dict(CATEGORY_SCHEMA_PROPERTY), "check_id": dict(CHECK_ID_SCHEMA_PROPERTY)}


def category_metadata_params() -> dict[str, Any]:
    """Return the AI-metadata `parameters` fragment for `category` and `check_id`."""
    return {"category": dict(CATEGORY_METADATA_PARAM), "check_id": dict(CHECK_ID_METADATA_PARAM)}


def parse_category(raw: str | None) -> str | None:
    """Validate and normalize a `category` argument.

    Args:
        raw: The caller-supplied value, or None when omitted.

    Returns:
        The validated category value, or None when raw is None.

    Raises:
        DomainCommandError: With code "INVALID_FILTER" if raw is not None
        and not one of CATEGORY_VALUES.
    """
    if raw is None:
        return None
    if raw not in CATEGORY_VALUES:
        raise DomainCommandError(
            "INVALID_FILTER", f"category must be one of {list(CATEGORY_VALUES)}, got {raw!r}"
        )
    return raw


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    category: str | None = None,
    entity_type: str | None = None,
    step: str | None = None,
    status: str | None = None,
    check_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of `entries` matching every supplied (non-None) filter.

    Filters not applicable to an entry's category (e.g. entity_type against a
    gate_finding entry, which has none) simply exclude that entry rather than
    raising -- consistent with the spec's "where applicable" scoping.

    Args:
        entries: The full unified entries collection (build_preview_entries()).
        category: Restrict to entries whose "category" equals this value.
        entity_type: Restrict to entries whose "entity_type" equals this value.
        step: Restrict to entries whose "entity_uuid" equals this value.
        status: Restrict to entries whose "step_status" equals this value.
        check_id: Restrict to entries whose "check_id" equals this value.

    Returns:
        A new filtered list; `entries` is never mutated.
    """
    result = entries
    if category is not None:
        result = [e for e in result if e["category"] == category]
    if entity_type is not None:
        result = [e for e in result if e.get("entity_type") == entity_type]
    if step is not None:
        result = [e for e in result if e.get("entity_uuid") == step]
    if status is not None:
        result = [e for e in result if e.get("step_status") == status]
    if check_id is not None:
        result = [e for e in result if e.get("check_id") == check_id]
    return result


def summarize(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Return the fixed 5-category summary-count dashboard over the FULL (unfiltered) entries.

    Args:
        entries: The full unified entries collection (build_preview_entries()),
            never a pre-filtered subset -- summary always reports the
            cascade's real totals regardless of any detail-page filter.

    Returns:
        A dict with exactly the keys "added", "removed", "changed",
        "needs_review", "gate_findings", each the count of entries of that
        category.
    """
    counts = {category: 0 for category in CATEGORY_VALUES}
    for entry in entries:
        counts[entry["category"]] += 1
    return {
        "added": counts["added"],
        "removed": counts["removed"],
        "changed": counts["changed"],
        "needs_review": counts["needs_review"],
        "gate_findings": counts["gate_finding"],
    }
