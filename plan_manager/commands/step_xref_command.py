"""Cross-reference report command for step field fingerprints."""
from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.commands.step_xref_metadata import get_step_xref_metadata
from plan_manager.domain.step import Step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.canonical import content_hash
from plan_manager.views.dependency_graph import load_steps, tie_break_key
from plan_manager.views.step_fingerprint import build_field_hash_index, step_field_hash


def _resolve_query_hash(
    nodes: dict[uuid.UUID, Step], text: str | None, step: str | None, field: str | None
) -> str:
    """Resolve the single query content hash for a step_xref lookup.

    Exactly one of `text` or the pair (`step`, `field`) must be given.
    Raises DomainCommandError for invalid input combinations.
    """
    # Check for conflicting inputs
    if text is not None and (step is not None or field is not None):
        raise DomainCommandError(
            "INVALID_FILTER",
            "provide either text or (step and field), not both"
        )

    # Check that at least one query path is provided
    if text is None and step is None and field is None:
        raise DomainCommandError(
            "INVALID_FILTER",
            "provide either text or (step and field)"
        )

    # Text path: return hash of literal text
    if text is not None:
        return content_hash(text)

    # Step/field path: both must be provided
    if step is None or field is None:
        raise DomainCommandError(
            "INVALID_FILTER",
            "step and field must be provided together"
        )

    # Resolve step reference (may raise STEP_NOT_FOUND or AMBIGUOUS_STEP_ID)
    resolved = resolve_step_ref(nodes, step)

    # Check field exists on resolved step
    if field not in resolved.fields:
        raise DomainCommandError(
            "INVALID_FILTER",
            f"field {field!r} not found on step {step!r}"
        )

    # Return hash of field value
    return step_field_hash(resolved, field)


def _locations_for_hash(
    nodes: dict[uuid.UUID, Step],
    index: dict[str, list[tuple[uuid.UUID, str]]],
    target_hash: str,
) -> list[dict[str, Any]]:
    """Build the sorted, role-annotated location list for one query hash.

    Sorts locations by (tie_break_key, field_name).
    First occurrence gets role "defined", rest get "inlined".
    Returns empty list if hash not found in index.
    """
    raw = index.get(target_hash, [])

    # Sort by tie_break_key then field_name
    sorted_entries = sorted(
        raw,
        key=lambda entry: (tie_break_key(nodes, entry[0]), entry[1])
    )

    # Build location dicts with role annotation
    locations = []
    for idx, (step_uuid, field_name) in enumerate(sorted_entries):
        role = "defined" if idx == 0 else "inlined"
        locations.append({
            "path": canonical_step_path(nodes, nodes[step_uuid]),
            "field": field_name,
            "role": role,
            "content_hash": target_hash,
        })

    return locations


class StepXrefCommand(Command):
    """Cross-reference report over per-field content fingerprints."""

    name: ClassVar[str] = "step_xref"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Cross-reference report over per-field content fingerprints: report where a signature/text fragment or a given step field is DEFINED versus where it is INLINED across the plan."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return JSON schema for command parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or uuid) resolved against the catalog.",
                },
                "text": {
                    "type": "string",
                    "description": "Literal text/signature fragment to search for; provide either text or step+field.",
                },
                "step": {
                    "type": "string",
                    "description": "Step reference (uuid, canonical path, or step_id) supplying the field to cross-reference.",
                },
                "field": {
                    "type": "string",
                    "description": "Field name on the referenced step supplying the query fingerprint.",
                },
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return command metadata."""
        return get_step_xref_metadata(cls)

    async def execute(
        self,
        plan: str,
        text: str | None = None,
        step: str | None = None,
        field: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Execute the cross-reference query.

        Returns a paginated list of locations where the queried content
        appears (defined or inlined).
        """
        try:
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                nodes = load_steps(conn, plan_obj.uuid)
                target_hash = _resolve_query_hash(nodes, text, step, field)
                index = build_field_hash_index(nodes)
                all_locations = _locations_for_hash(nodes, index, target_hash)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                total = len(all_locations)
                page = all_locations[pagination.offset : pagination.offset + pagination.limit]
                data = {
                    "locations": page,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
