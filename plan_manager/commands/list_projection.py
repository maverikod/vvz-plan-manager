"""Shared response-size projection for the list-family commands (bug 8a13977d).

Every list command inlines the full record for each row by default, which is
unbounded: a moderate page of verbose entities (long descriptions, prompts,
tree content, ...) can produce a response of hundreds of kilobytes -- too
large for an LLM-agent caller with a hard token budget to consume in-band.

This module is the ONE shared seam every touched list command uses to offer
a caller-selected row shape without hand-rolling its own dict comprehension:

- ``view=\"full\"`` (the default, unchanged behavior): the complete record,
  exactly as before this parameter existed.
- ``view=\"summary\"``: a compact projection restricted to the entity's
  declared ``SUMMARY_FIELDS`` (see plan_manager.domain.entity.EntityRecord),
  or to a command-local summary field tuple for rows that are not backed by
  an EntityRecord (e.g. step_list's hand-built entries, para_list's plain
  paragraph dicts).

Per-entity summary field lists are declared next to each entity's own
serialization (its ``to_payload``/dataclass definition), never here; this
module only supplies the uniform parameter surface (schema/metadata
fragments, parsing) and the projection function itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from plan_manager.commands.errors import DomainCommandError

VIEW_FULL: str = "full"
VIEW_SUMMARY: str = "summary"
VIEW_VALUES: tuple[str, ...] = (VIEW_FULL, VIEW_SUMMARY)

_VIEW_DESCRIPTION: str = (
    "Row projection shape. 'full' (default) returns the complete record exactly as "
    "before this parameter existed. 'summary' returns a compact per-entity projection "
    "(identifier, name/title, status/kind, severity or priority where the entity has "
    "one, primary anchor type+ref, updated_at) sized to stay within typical agent "
    "response budgets; full records remain one *_get call away. One of: full, summary."
)

_VIEW_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(VIEW_VALUES),
    "default": VIEW_FULL,
    "description": _VIEW_DESCRIPTION,
}

_VIEW_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _VIEW_DESCRIPTION,
    "required": False,
    "enum": list(VIEW_VALUES),
}


def view_schema_properties() -> dict[str, Any]:
    """Return the JSON-schema ``properties`` fragment for the ``view`` parameter."""
    return {"view": dict(_VIEW_SCHEMA_PROPERTY)}


def view_metadata_params() -> dict[str, Any]:
    """Return the AI-metadata ``parameters`` fragment for the ``view`` parameter."""
    return {"view": dict(_VIEW_METADATA_PARAM)}


def parse_view(raw: str | None, *, default: str = VIEW_FULL) -> str:
    """Validate and normalize a ``view`` argument.

    Args:
        raw: The caller-supplied value, or None when omitted.
        default: The value to use when raw is None (every touched list
            command keeps this at VIEW_FULL for backward compatibility).

    Returns:
        The validated view value.

    Raises:
        DomainCommandError: With code "INVALID_FILTER" if raw is not None
        and not one of VIEW_VALUES.
    """
    if raw is None:
        return default
    if raw not in VIEW_VALUES:
        raise DomainCommandError(
            "INVALID_FILTER", f"view must be one of {list(VIEW_VALUES)}, got {raw!r}"
        )
    return raw


def project_row(payload: Mapping[str, Any], view: str, summary_fields: Sequence[str]) -> dict[str, Any]:
    """Return `payload` unchanged for view=full; whitelisted to `summary_fields` for view=summary.

    Works uniformly on any JSON-safe mapping -- an entity's to_payload() dict
    or a hand-built row dict alike -- so callers never need their own
    per-command projection logic.
    """
    if view == VIEW_SUMMARY:
        return {name: payload.get(name) for name in summary_fields}
    return dict(payload)


def project_rows(
    payloads: Sequence[Mapping[str, Any]], view: str, summary_fields: Sequence[str]
) -> list[dict[str, Any]]:
    """Apply project_row to every payload in `payloads`."""
    return [project_row(payload, view, summary_fields) for payload in payloads]


def project_entities(records: Sequence[Any], view: str) -> list[dict[str, Any]]:
    """Project a sequence of EntityRecord-like objects via their own to_payload/to_summary_payload.

    Each record must expose ``to_payload()`` and ``to_summary_payload()`` (the
    default EntityRecord.to_summary_payload() whitelists SUMMARY_FIELDS from
    to_payload(), see plan_manager.domain.entity). Preferred over project_rows
    for the common case where the row IS an entity record, since it lets each
    entity's own to_summary_payload() decide (e.g. an override), not just a
    fixed field-name whitelist applied from outside.
    """
    if view == VIEW_SUMMARY:
        return [record.to_summary_payload() for record in records]
    return [record.to_payload() for record in records]
