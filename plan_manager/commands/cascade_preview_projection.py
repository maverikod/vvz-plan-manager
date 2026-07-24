"""Response projection for cascade_preview: category/check_id filter parsing
and paginated-detail filtering over the unified entries collection built by
plan_manager.cascade.preview.build_preview_entries (todo 3c762bfe), plus
gate_report_json findings pagination (todo b6ed4b0b).
"""

from __future__ import annotations

import json
from typing import Any

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.list_projection import VIEW_SUMMARY, VIEW_VALUES
from plan_manager.commands.runtime_filtering import DEFAULT_LIMIT, MAX_LIMIT, Pagination
from plan_manager.storage.canonical import canonical_json

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
    "step/status) plus gate_report_json, itself bounded by its own "
    "gate_findings_limit/gate_findings_offset page window over the "
    "flattened findings list (todo b6ed4b0b) -- see gate_findings_total for "
    "the unfiltered count and each check's finding_count for its own real "
    "total. One of: " + ", ".join(VIEW_VALUES) + "."
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


_GATE_FINDINGS_LIMIT_DESCRIPTION: str = (
    "Maximum gate_report_json findings to embed, applied to the flattened "
    "findings list across every check (default 50, max 200; same "
    "convention as the generic entries limit -- see runtime_filtering "
    "parse_pagination -- but paged independently of it). Only applies when "
    "view=full. Each check keeps its own 'finding_count' (its real, "
    "unbounded total) even when its findings are outside the current page "
    "window; see gate_findings_total for the report-wide total. Todo b6ed4b0b."
)

_GATE_FINDINGS_OFFSET_DESCRIPTION: str = (
    "Number of flattened gate_report_json findings to skip, across every "
    "check, before the returned page window (default 0). Only applies when "
    "view=full. Todo b6ed4b0b."
)

_GATE_FINDINGS_LIMIT_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "description": _GATE_FINDINGS_LIMIT_DESCRIPTION,
    "minimum": 1,
    "maximum": MAX_LIMIT,
}

_GATE_FINDINGS_OFFSET_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "description": _GATE_FINDINGS_OFFSET_DESCRIPTION,
    "minimum": 0,
}

_GATE_FINDINGS_LIMIT_METADATA_PARAM: dict[str, Any] = {
    "type": "integer",
    "description": _GATE_FINDINGS_LIMIT_DESCRIPTION,
    "required": False,
}

_GATE_FINDINGS_OFFSET_METADATA_PARAM: dict[str, Any] = {
    "type": "integer",
    "description": _GATE_FINDINGS_OFFSET_DESCRIPTION,
    "required": False,
}


def gate_findings_pagination_schema_properties() -> dict[str, Any]:
    """Return the JSON-schema `properties` fragment for gate_findings_limit/offset."""
    return {
        "gate_findings_limit": dict(_GATE_FINDINGS_LIMIT_SCHEMA_PROPERTY),
        "gate_findings_offset": dict(_GATE_FINDINGS_OFFSET_SCHEMA_PROPERTY),
    }


def gate_findings_pagination_metadata_params() -> dict[str, Any]:
    """Return the AI-metadata `parameters` fragment for gate_findings_limit/offset."""
    return {
        "gate_findings_limit": dict(_GATE_FINDINGS_LIMIT_METADATA_PARAM),
        "gate_findings_offset": dict(_GATE_FINDINGS_OFFSET_METADATA_PARAM),
    }


def parse_gate_findings_pagination(params: dict[str, Any]) -> Pagination:
    """Validate and normalize gate_findings_limit/gate_findings_offset.

    Mirrors runtime_filtering.parse_pagination's conventions exactly
    (limit default DEFAULT_LIMIT, range [1, MAX_LIMIT]; offset default 0,
    must be >= 0) but is kept as a distinct field-name pair so a caller can
    page gate_report_json's findings independently of the generic
    entries limit/offset (todo b6ed4b0b).

    Args:
        params: The raw command parameters dict as received by the
            command's execute.

    Returns:
        A Pagination with limit in [1, MAX_LIMIT] (default DEFAULT_LIMIT
        when absent) and offset >= 0 (default 0 when absent).

    Raises:
        DomainCommandError: With code "INVALID_PAGINATION" if a provided
        gate_findings_limit or gate_findings_offset is not an integer, or
        if a provided gate_findings_offset is negative, or if a provided
        gate_findings_limit is outside the closed range [1, MAX_LIMIT].
    """
    raw_limit = params.get("gate_findings_limit")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
            raise DomainCommandError(
                "INVALID_PAGINATION", f"gate_findings_limit must be an integer, got {raw_limit!r}"
            )
        if raw_limit < 1 or raw_limit > MAX_LIMIT:
            raise DomainCommandError(
                "INVALID_PAGINATION",
                f"gate_findings_limit must be between 1 and {MAX_LIMIT}, got {raw_limit!r}",
            )
        limit = raw_limit

    raw_offset = params.get("gate_findings_offset")
    if raw_offset is None:
        offset = 0
    else:
        if not isinstance(raw_offset, int) or isinstance(raw_offset, bool):
            raise DomainCommandError(
                "INVALID_PAGINATION", f"gate_findings_offset must be an integer, got {raw_offset!r}"
            )
        if raw_offset < 0:
            raise DomainCommandError(
                "INVALID_PAGINATION", f"gate_findings_offset must be >= 0, got {raw_offset!r}"
            )
        offset = raw_offset

    return Pagination(limit=limit, offset=offset)


def paginate_gate_report_json(gate_report_json: str, limit: int, offset: int) -> tuple[str, int]:
    """Return a bounded rendering of `gate_report_json` plus its true findings total.

    Parses the raw, unbounded canonical JSON produced by
    plan_manager.verify.finding.render_json (one dict per check_id, each
    holding its full, unbounded findings list) and rebuilds it with the
    per-check structure preserved (same check order, same check_id/passed
    fields) but each check's "findings" list narrowed to its slice of the
    [offset, offset + limit) page window computed over the FLATTENED
    findings list across every check in report order -- the same
    "flatten across checks, then page" semantics as the generic entries
    pagination, applied to this nested structure instead. Each check also
    gains a new "finding_count" field: that check's real, unbounded finding
    count, so a caller can see the full per-check shape without every
    finding's body once findings for that check fall outside the current
    window. This function never mutates its input and does not require a
    database connection or the original Report object (todo b6ed4b0b).

    Args:
        gate_report_json: The raw canonical JSON string as produced by
            plan_manager.verify.finding.render_json (or any JSON string
            with the same {"green": bool, "checks": [{"check_id": str,
            "passed": bool, "findings": [...]}]} shape; a missing "checks"
            key is treated as an empty list).
        limit: Maximum number of findings to include in the returned page
            window, applied across the flattened findings list.
        offset: Number of flattened findings to skip before the window.

    Returns:
        A tuple (bounded_json, total): bounded_json is the canonical JSON
        string of {"green": ..., "checks": [...]} with each check's
        "findings" narrowed to its page-window slice and a "finding_count"
        field added; total is the true count of findings across every
        check, before any windowing.
    """
    parsed = json.loads(gate_report_json)
    checks = parsed.get("checks", [])

    flat_index = 0
    total = 0
    bounded_checks: list[dict[str, Any]] = []
    for check in checks:
        findings = check.get("findings", [])
        finding_count = len(findings)
        total += finding_count
        window: list[Any] = []
        for finding in findings:
            if offset <= flat_index < offset + limit:
                window.append(finding)
            flat_index += 1
        bounded_checks.append({
            "check_id": check.get("check_id"),
            "passed": check.get("passed"),
            "finding_count": finding_count,
            "findings": window,
        })

    payload = {"green": parsed.get("green"), "checks": bounded_checks}
    encoded = canonical_json(payload)
    bounded_json = encoded.decode("utf-8") if isinstance(encoded, bytes) else encoded
    return bounded_json, total


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
