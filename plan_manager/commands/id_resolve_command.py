"""Command: turn a partial identifier into the full UUID(s) it matches.

Identifiers get recorded and quoted as fragments — an 8-character prefix in a
commit message, a doc, a chat line — while every command that consumes an id
needs the whole UUID. Without this command the only way back is to guess a scope
and page through list commands, and a wrong guess returns nothing, which reads as
"no such identifier" rather than "looked in the wrong place".

That failure is not hypothetical. Todo 558cd81a was reported as non-existent
after a project-scoped search came back empty across every list surface tried; it
existed all along, anchored to a plan whose primary project binding is unset, so
transitive project scope never reached it.

Read-only: nothing here writes, and nothing here audits. The entity identity
registry is the single index spanning every entity the service owns, so one query
covers all of them regardless of how a row is anchored.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.identity_search import MIN_FRAGMENT_LENGTH, search_entity_identities
from plan_manager.storage.reference_catalog import known_entity_types, resolve_entity_class

# Checked in order: the first column an entity actually declares wins. A generic
# rule rather than a per-entity table, so a new entity gets a label for free.
_LABEL_COLUMNS = ("title", "name", "summary", "slug", "short_description", "body")

_LABEL_MAX = 120


class IdResolveCommand(Command):
    """Resolve a partial identifier to the full UUID(s) it matches."""

    name: ClassVar[str] = "id_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Resolve a partial identifier (any fragment of a UUID) to the full "
        "identifier(s) it matches, with each match's entity type and label."
    )
    category: ClassVar[str] = "entity"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fragment": {
                    "type": "string",
                    "description": (
                        "Any part of a UUID — leading, trailing or middle. Hex digits "
                        f"and dashes only, at least {MIN_FRAGMENT_LENGTH} characters."
                    ),
                    "minLength": MIN_FRAGMENT_LENGTH,
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Optional filter narrowing the search to one entity type. This "
                        "is the ENTITY_TYPE, never the table name: 'todo', not 'todo_item'."
                    ),
                    "enum": known_entity_types(),
                },
                **pagination_schema_properties(),
            },
            "required": ["fragment"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        fragment: str,
        entity_type: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                try:
                    matches, total = search_entity_identities(
                        conn,
                        fragment,
                        entity_type=entity_type,
                        limit=pagination.limit,
                        offset=pagination.offset,
                    )
                except ValueError as exc:
                    raise DomainCommandError("RUNTIME_VALIDATION_ERROR", str(exc)) from exc
                items = [_serialize(conn, match) for match in matches]
            return SuccessResult(
                data={
                    "fragment": fragment,
                    "entity_type": entity_type,
                    "matches": items,
                    # unique lets a caller act without inspecting the list: a
                    # fragment matching two rows must not be silently narrowed to
                    # one, which is how a wrong id reaches a destructive command.
                    "unique": total == 1,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                }
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        return {
            "name": cls.name,
            "version": cls.version,
            "description": cls.descr,
            "category": cls.category,
            "author": cls.author,
            "email": cls.email,
            "detailed_description": (
                "Searches the entity identity registry, the one index that spans every "
                "entity the service owns, for identifiers whose UUID text contains the "
                "given fragment. Because the registry is anchor-agnostic, a match is found "
                "regardless of whether the row is anchored to a plan, a project, a step or "
                "nothing at all — which is exactly what scope-filtered list commands cannot "
                "promise. Matching is substring, not prefix, since identifiers get quoted "
                "as whatever slice was convenient. Read-only and audit-free."
            ),
            "parameters": {
                "fragment": {
                    "type": "string",
                    "description": (
                        f"Any part of a UUID, {MIN_FRAGMENT_LENGTH} characters or more, "
                        "hex digits and dashes only."
                    ),
                    "required": True,
                },
                "entity_type": {
                    "type": "string",
                    "description": "Optional ENTITY_TYPE filter, never a table name.",
                    "required": False,
                    "enum": schema["properties"]["entity_type"]["enum"],
                },
                **pagination_metadata_params(),
            },
            "return_value": {
                "success": {
                    "description": "The identifiers the fragment matches.",
                    "data": {
                        "fragment": "The fragment searched for, echoed back.",
                        "entity_type": "The entity-type filter applied, or null.",
                        "matches": (
                            "One object per match: uuid, entity_type, table_name, kind, "
                            "label, reserved_by, note, created_at. kind is "
                            "'project_reservation' for a claimed-but-uncreated identifier, "
                            "so a reservation is distinguishable from a live entity."
                        ),
                        "unique": (
                            "True when exactly one identifier matches — the signal that the "
                            "fragment can be used as an id without further disambiguation."
                        ),
                        "total": "Full match count before pagination.",
                        "limit": "The applied limit.",
                        "offset": "The applied offset.",
                    },
                },
                "error": {
                    "description": "Domain error result on failure.",
                    "code": "Stable domain error code string (see error_cases).",
                    "message": "Human-readable error message.",
                },
            },
            "usage_examples": [
                {
                    "description": "Turn an 8-character prefix quoted in a doc into a usable id.",
                    "command": {"fragment": "558cd81a"},
                },
                {
                    "description": "Disambiguate a short fragment within one entity type.",
                    "command": {"fragment": "4375", "entity_type": "bug"},
                },
            ],
            "error_cases": {
                "RUNTIME_VALIDATION_ERROR": {
                    "description": (
                        f"The fragment is shorter than {MIN_FRAGMENT_LENGTH} characters, or "
                        "carries characters no UUID contains. Rejected rather than escaped: a "
                        "UUID has only hex digits and dashes, so anything else is a mistake "
                        "worth reporting, not a pattern to run."
                    ),
                    "message": "identifier fragment carries characters no UUID contains: {chars}",
                    "solution": (
                        "Pass a longer fragment made only of hex digits and dashes; check for a "
                        "copied quote character or trailing punctuation."
                    ),
                },
                "INVALID_PAGINATION": {
                    "description": (
                        "limit or offset is not an integer, offset is negative, or limit is "
                        "outside the uniform pagination range."
                    ),
                    "message": "limit must be between 1 and {max}, got {value}",
                    "solution": "Correct limit/offset and retry.",
                },
            },
            "best_practices": [
                "Check `unique` before feeding a resolved id into a mutating or deleting "
                "command. A short fragment can match several rows, and picking the first is "
                "how a wrong identifier reaches a destructive call.",
                "Prefer this over guessing a scope for a list command. A scope-filtered search "
                "that returns nothing cannot distinguish 'no such identifier' from 'anchored "
                "somewhere the filter does not reach' — the confusion this command exists to "
                "remove.",
                "An empty result here IS meaningful: the registry covers every entity the "
                "service owns, so nothing matching means the identifier is genuinely absent, "
                "not merely out of scope.",
                "A match with kind='project_reservation' names a reserved-but-uncreated "
                "identifier. No entity row exists for it yet.",
                "Eight hex characters are ample in practice; two are accepted but will usually "
                "come back ambiguous, which the `total` field reports honestly.",
            ],
        }


def _serialize(conn: Any, match: dict[str, Any]) -> dict[str, Any]:
    """Render one registry row as a JSON-safe payload with a human label."""
    created_at = match.get("created_at")
    return {
        "uuid": str(match["id"]),
        "entity_type": match.get("entity_type"),
        "table_name": match.get("table_name"),
        "kind": match.get("kind"),
        "label": _label_for(conn, match),
        "reserved_by": match.get("reserved_by"),
        "note": match.get("note"),
        "created_at": created_at if isinstance(created_at, str) or created_at is None
        else created_at.isoformat(),
    }


def _label_for(conn: Any, match: dict[str, Any]) -> str | None:
    """Read a short human label for one match, or None when there is none.

    Best-effort by construction: a label is a convenience, and a resolver that
    failed because one entity's label column was unreadable would be worse than
    one that answers without it.
    """
    entity_type = match.get("entity_type")
    if not entity_type:
        return None
    try:
        entity_cls = resolve_entity_class(str(entity_type))
    except ValueError:
        return None
    columns = getattr(entity_cls, "COLUMNS", ()) or ()
    column = next((name for name in _LABEL_COLUMNS if name in columns), None)
    if column is None:
        return None
    try:
        row = entity_cls.get_by_id(conn, match["id"], include_deleted=True)
    except Exception:
        return None
    if not row:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= _LABEL_MAX else text[: _LABEL_MAX - 1] + "…"
