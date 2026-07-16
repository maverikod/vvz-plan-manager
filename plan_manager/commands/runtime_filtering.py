"""Uniform runtime-listing filters and pagination for the command surface (C-030)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plan_manager.commands.errors import DomainCommandError


FILTER_FIELDS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "project": (
        {"type": "string", "format": "uuid", "description": "Project UUID to filter by."},
        {"description": "Project UUID to filter by.", "type": "string", "required": False},
    ),
    "file": (
        {"type": "string", "description": "Project-relative file path to filter by. Requires project to also be provided."},
        {"description": "Project-relative file path to filter by. Requires project to also be provided.", "type": "string", "required": False},
    ),
    "anchor_plan": (
        {"type": "string", "format": "uuid", "description": "Plan UUID of the entity's primary anchor, for anchor-plan filtering."},
        {"description": "Plan UUID of the entity's primary anchor, for anchor-plan filtering.", "type": "string", "required": False},
    ),
    "revision": (
        {"type": "string", "format": "uuid", "description": "Revision UUID to filter by."},
        {"description": "Revision UUID to filter by.", "type": "string", "required": False},
    ),
    "step": (
        {"type": "string", "format": "uuid", "description": "Step UUID to filter by."},
        {"description": "Step UUID to filter by.", "type": "string", "required": False},
    ),
    "status": (
        {"type": "string", "description": "Entity status to filter by."},
        {"description": "Entity status to filter by.", "type": "string", "required": False},
    ),
    "kind": (
        {"type": "string", "description": "Entity kind to filter by."},
        {"description": "Entity kind to filter by.", "type": "string", "required": False},
    ),
    "severity": (
        {"type": "string", "description": "Severity to filter by."},
        {"description": "Severity to filter by.", "type": "string", "required": False},
    ),
    "impact_type": (
        {"type": "string", "description": "Impact type to filter by."},
        {"description": "Impact type to filter by.", "type": "string", "required": False},
    ),
    "priority": (
        {"type": "integer", "description": "Nice-scale priority value to filter by (-20 to 19)."},
        {"description": "Nice-scale priority value to filter by (-20 to 19).", "type": "integer", "required": False},
    ),
    "owner": (
        {"type": "string", "description": "Owner identifier to filter by."},
        {"description": "Owner identifier to filter by.", "type": "string", "required": False},
    ),
    "assignee": (
        {"type": "string", "description": "Assignee identifier to filter by."},
        {"description": "Assignee identifier to filter by.", "type": "string", "required": False},
    ),
    "model": (
        {"type": "string", "description": "Model identifier to filter by."},
        {"description": "Model identifier to filter by.", "type": "string", "required": False},
    ),
    "created_after": (
        {"type": "string", "format": "date-time", "description": "ISO-8601 timestamp; only entities created after this instant are included."},
        {"description": "ISO-8601 timestamp; only entities created after this instant are included.", "type": "string", "required": False},
    ),
    "created_before": (
        {"type": "string", "format": "date-time", "description": "ISO-8601 timestamp; only entities created before this instant are included."},
        {"description": "ISO-8601 timestamp; only entities created before this instant are included.", "type": "string", "required": False},
    ),
    "active_only": (
        {"type": "boolean", "description": "When true, only non-terminal (active) entities are included."},
        {"description": "When true, only non-terminal (active) entities are included.", "type": "boolean", "required": False},
    ),
    "unanchored_only": (
        {"type": "boolean", "description": "When true, only entities with no primary anchor are included."},
        {"description": "When true, only entities with no primary anchor are included.", "type": "boolean", "required": False},
    ),
    "unresolved_impacts": (
        {"type": "boolean", "description": "When true, only bug impacts that are not yet resolved are included."},
        {"description": "When true, only bug impacts that are not yet resolved are included.", "type": "boolean", "required": False},
    ),
    "unverified_fixes": (
        {"type": "boolean", "description": "When true, only bug fixes that are not yet verified are included."},
        {"description": "When true, only bug fixes that are not yet verified are included.", "type": "boolean", "required": False},
    ),
    "actor": (
        {"type": "string", "description": "Actor identifier (changed_by) to filter by."},
        {"description": "Actor identifier (changed_by) to filter by.", "type": "string", "required": False},
    ),
    "action": (
        {"type": "string", "description": "Recorded runtime-audit action to filter by."},
        {"description": "Recorded runtime-audit action to filter by.", "type": "string", "required": False},
    ),
    "entity_type": (
        {"type": "string", "description": "Audited entity's type to filter by."},
        {"description": "Audited entity's type to filter by.", "type": "string", "required": False},
    ),
    "entity_id": (
        {"type": "string", "format": "uuid", "description": "Audited entity's identifier (UUID) to filter by."},
        {"description": "Audited entity's identifier (UUID) to filter by.", "type": "string", "required": False},
    ),
    "plan": (
        {"type": "string", "format": "uuid", "description": "Plan UUID the audit record is anchored to, to filter by."},
        {"description": "Plan UUID the audit record is anchored to, to filter by.", "type": "string", "required": False},
    ),
}

PAGINATION_FIELDS: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "limit": (
        {"type": "integer", "description": "Maximum number of results to return (default 50, max 200).", "minimum": 1, "maximum": 200},
        {"description": "Maximum number of results to return (default 50, max 200).", "type": "integer", "required": False},
    ),
    "offset": (
        {"type": "integer", "description": "Number of results to skip before returning results (default 0).", "minimum": 0},
        {"description": "Number of results to skip before returning results (default 0).", "type": "integer", "required": False},
    ),
}

DEFAULT_LIMIT: int = 50
MAX_LIMIT: int = 200


@dataclass(frozen=True)
class Pagination:
    """Holds a validated, clamped limit/offset pair."""

    limit: int
    offset: int


@dataclass(frozen=True)
class RuntimeFilters:
    """Holds only the applicable, provided-and-parsed filter values, keyed by canonical filter field name."""

    values: dict[str, Any]

    def get(self, name: str, default: Any = None) -> Any:
        """Return the parsed value for filter field `name`, or `default` if not present."""
        return self.values.get(name, default)


def _with_enum_vocabulary(
    base: dict[str, Any], name: str, enum_overrides: dict[str, list[str]] | None, is_schema: bool
) -> dict[str, Any]:
    """Return a copy of `base` enriched with an enumerated vocabulary for field `name`.

    When `enum_overrides` supplies an ordered value list for `name`, the returned
    fragment appends "One of: v1, v2, ..." to the description so the concrete
    vocabulary is published in both the JSON-schema and the AI metadata surface
    (metadata params copy the description). For the JSON-schema fragment
    (is_schema=True) an explicit `enum` array is also attached.
    """
    result = dict(base)
    if enum_overrides and name in enum_overrides:
        values = list(enum_overrides[name])
        result["description"] = result["description"].rstrip(".") + ". One of: " + ", ".join(values) + "."
        if is_schema:
            result["enum"] = values
    return result


def filter_schema_properties(
    fields: list[str], enum_overrides: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """Return the JSON-schema `properties` fragment for the given list of canonical filter field names.

    `enum_overrides` optionally maps a filter field name (e.g. "status", "kind",
    "severity") to the ordered list of values that field accepts for the calling
    command's entity; the vocabulary is published in the field description and as
    an `enum` array so callers never have to discover it via an INVALID_FILTER error.
    """
    return {name: _with_enum_vocabulary(FILTER_FIELDS[name][0], name, enum_overrides, True) for name in fields}


def filter_metadata_params(
    fields: list[str], enum_overrides: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """Return the metadata `parameters` fragment for the given list of canonical filter field names.

    `enum_overrides` optionally maps a filter field name to the ordered list of
    values that field accepts for the calling command's entity; the vocabulary is
    appended to the field description so it appears in the command's AI metadata.
    """
    return {name: _with_enum_vocabulary(FILTER_FIELDS[name][1], name, enum_overrides, False) for name in fields}


def pagination_schema_properties() -> dict[str, Any]:
    """Return the JSON-schema `properties` fragment for both pagination fields."""
    return {name: prop for name, (prop, _param) in PAGINATION_FIELDS.items()}


def pagination_metadata_params() -> dict[str, Any]:
    """Return the metadata `parameters` fragment for both pagination fields."""
    return {name: param for name, (_prop, param) in PAGINATION_FIELDS.items()}


def _is_valid_uuid(value: str) -> bool:
    """Return True if `value` parses as a UUID string."""
    import uuid as _uuid
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _is_valid_iso8601(value: str) -> bool:
    """Return True if `value` parses as an ISO-8601 timestamp string."""
    import datetime as _datetime
    try:
        _datetime.datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_filters(
    params: dict[str, Any],
    fields: list[str],
    enums: dict[str, frozenset[str]] | None = None,
) -> RuntimeFilters:
    """Parse and validate filter parameters.

    Args:
        params: The raw command parameters dict as received by the command's execute.
        fields: The canonical filter field names this command supports (a subset of FILTER_FIELDS keys).
        enums: Optional mapping of filter field name to the frozenset of values that field may take.
            For any name in fields that is also a key of enums, after normal type validation the
            parsed string value must be a member of enums[name] or INVALID_FILTER is raised.
            Defaults to None, which preserves prior behavior (no vocabulary check).

    Returns:
        A RuntimeFilters holding only the fields from fields that are present (not None) in params,
        validated and normalized.

    Raises:
        ValueError: If any name in fields is not a key of FILTER_FIELDS (a programming error).
        DomainCommandError: With code "INVALID_FILTER" if a provided filter value fails validation,
        including failing an enums membership check when one is configured for that field.
    """
    for name in fields:
        if name not in FILTER_FIELDS:
            raise ValueError(f"unknown filter field: {name!r}")

    values: dict[str, Any] = {}
    for name in fields:
        raw = params.get(name)
        if raw is None:
            continue
        prop, _param = FILTER_FIELDS[name]
        schema_type = prop.get("type")
        if schema_type == "string" and prop.get("format") == "uuid":
            if not isinstance(raw, str) or not _is_valid_uuid(raw):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be a valid UUID string, got {raw!r}")
            values[name] = raw
        elif schema_type == "string" and prop.get("format") == "date-time":
            if not isinstance(raw, str) or not _is_valid_iso8601(raw):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be a valid ISO-8601 timestamp string, got {raw!r}")
            values[name] = raw
        elif schema_type == "integer":
            if not isinstance(raw, int) or isinstance(raw, bool):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be an integer, got {raw!r}")
            if name == "priority" and not (-20 <= raw <= 19):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be in range [-20, 19], got {raw!r}")
            values[name] = raw
        elif schema_type == "boolean":
            if not isinstance(raw, bool):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be a boolean, got {raw!r}")
            values[name] = raw
        else:
            if not isinstance(raw, str):
                raise DomainCommandError("INVALID_FILTER", f"{name!r} must be a string, got {raw!r}")
            values[name] = raw

        if enums is not None and name in enums and name in values:
            allowed = enums[name]
            if values[name] not in allowed:
                raise DomainCommandError(
                    "INVALID_FILTER",
                    f"{name!r} must be one of {sorted(allowed)}; got {values[name]!r}",
                )
    return RuntimeFilters(values=values)


def parse_pagination(params: dict[str, Any]) -> Pagination:
    """Parse and validate pagination parameters.

    Args:
        params: The raw command parameters dict.

    Returns:
        A Pagination with limit in [1, MAX_LIMIT] (default DEFAULT_LIMIT when absent)
        and offset >= 0 (default 0 when absent).

    Raises:
        DomainCommandError: With code "INVALID_PAGINATION" if a provided limit or offset is not
        an integer, or if a provided offset is negative, or if a provided limit is outside the
        closed range [1, MAX_LIMIT].
    """
    raw_limit = params.get("limit")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
            raise DomainCommandError("INVALID_PAGINATION", f"limit must be an integer, got {raw_limit!r}")
        if raw_limit < 1 or raw_limit > MAX_LIMIT:
            raise DomainCommandError(
                "INVALID_PAGINATION",
                f"limit must be between 1 and {MAX_LIMIT}, got {raw_limit!r}",
            )
        limit = raw_limit

    raw_offset = params.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        if not isinstance(raw_offset, int) or isinstance(raw_offset, bool):
            raise DomainCommandError("INVALID_PAGINATION", f"offset must be an integer, got {raw_offset!r}")
        if raw_offset < 0:
            raise DomainCommandError("INVALID_PAGINATION", f"offset must be >= 0, got {raw_offset!r}")
        offset = raw_offset

    return Pagination(limit=limit, offset=offset)
