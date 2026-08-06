"""Command: hard-delete the fixed-point-closed set of marked entities.

CR-7 G-006/T-001/A-002 reverses this command's earlier per-entity-type,
report-one-and-continue shape (see docs/delivery for the CR-7 governance
record filed at G-008) onto the set-wise engine landed by the sibling step
A-001 (``storage.runtime_hard_delete.hard_delete_marked_set``).

The shipped shape this replaces purged one entity type at a time
(``entity.purge_soft_deleted_batch``, driven by ``crud_purge_soft_deleted_batch``):
each already-marked row was admitted for physical removal by checking only its
LIVE inbound references, and a row that was still referenced came back in a
per-row ``refused`` list while the batch continued with the rest. That
admission check never looked at referrers that were themselves already
marked -- so a marked-but-not-yet-purged referrer never blocked anything, and
if that referrer was not purged in the very same run (a different entity
type, or simply not yet reached), it was left pointing at a row the purge had
just removed: a dangling reference the purge itself manufactured, with no
later pass that ever cleans it up, because nothing about a successful
removal is recorded as "still owes a followup".

hard_delete_marked_set closes this hole by deciding on the WHOLE set before
touching a single row: the starting set (explicit identifiers, or -- by
default -- every entity currently marked across every soft-delete-capable
type) is expanded to its fixed point of marked referrers, and only removed
atomically if every referrer of the closed set is itself a member. If any
referrer outside the set remains, it is necessarily unmarked (a marked one
would already have been folded in), and the WHOLE operation is refused --
nothing is removed, not even the members that had no blocking referrer of
their own. There is no more per-row ``refused`` list: one call either
removes its whole computed set or removes nothing, and a refusal names every
external unmarked referrer that blocked it.

This command writes NO audit record of its own. The hard-delete guard beneath
the engine is the single audit point and records one row per removal; a write
here would audit every removed row twice.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.domain.entity import EntityNotSoftDeletedError, EntityReferencedError
from plan_manager.runtime.context import db_connection
from plan_manager.storage.errors import NotFoundError
from plan_manager.storage.identity import resolve_entity_identities_batch
from plan_manager.storage.reference_catalog import purge_capable_entity_types, resolve_entity_class
from plan_manager.storage.runtime_hard_delete import hard_delete_marked_set


def _describe_blocking_referrers(
    conn: Any, exc: EntityReferencedError
) -> list[dict[str, Any]]:
    """Resolve each blocking referrer's entity_type so the refusal names WHAT blocked it.

    Called only on the refusal path: hard_delete_marked_set raises before
    removing anything, so every blocking id named here is still a live row
    the identity registry can resolve. entity_type stands in for "table" in
    this payload -- project convention names entities by ENTITY_TYPE, never
    the raw table name, everywhere else on this command surface.
    """
    referrer_ids = [referrer["referrer_id"] for referrer in exc.referrers]
    resolved = resolve_entity_identities_batch(conn, referrer_ids)
    described = []
    for referrer in exc.referrers:
        referrer_id = referrer["referrer_id"]
        info = resolved.get(referrer_id)
        described.append(
            {
                "entity_type": info["entity_type"] if info is not None else None,
                "id": str(referrer_id),
                # field_ref: the relation index's own opaque property key: it
                # identifies WHICH field on the referrer points at the closed
                # set, but is not itself a human-readable column name (see
                # storage.reference_catalog.reference_field).
                "field_ref": str(referrer.get("column")),
            }
        )
    return described


def _refusal_message(described: list[dict[str, Any]]) -> str:
    names = ", ".join(f"{item['entity_type'] or 'unknown'}:{item['id']}" for item in described)
    return (
        f"hard delete refused: {len(described)} external unmarked referrer(s) still "
        f"reference the requested set, so the whole operation is refused and nothing "
        f"was removed -- {names}"
    )


class RuntimePurgeBatchCommand(Command):
    """Irreversibly remove the fixed-point-closed set of marked entities, atomically."""

    name: ClassVar[str] = "runtime_purge_batch"
    version: ClassVar[str] = "2.0.0"
    descr: ClassVar[str] = (
        "Hard-delete the fixed-point-closed set of marked (soft-deleted) entities -- "
        "explicit identifiers, or every marked entity by default -- atomically: the "
        "whole computed set is removed, or the whole operation is refused and nothing "
        "is removed."
    )
    category: ClassVar[str] = "runtime"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "identifiers": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                    "description": (
                        "Explicit starting set of already-marked (soft-deleted) entity "
                        "identifiers, of ANY soft-delete-capable entity type in one "
                        "call -- the engine underneath is cross-kind. Every id here "
                        "must already be marked; the fixed-point closure then pulls in "
                        "every marked referrer automatically. Omit (or pass null) to "
                        "default to every entity currently marked across every "
                        "soft-delete-capable type -- hard_delete_marked_set's own "
                        "default."
                    ),
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Optional, informational only: the engine is cross-kind and "
                        "this never filters or scopes identifiers -- it only pre-checks "
                        "that the named type is capable of being purged at all "
                        "(declares a soft-delete column), before any lookup runs. This "
                        "is the ENTITY_TYPE, never the table name."
                    ),
                    "enum": purge_capable_entity_types(),
                },
                "changed_by": {
                    "type": "string",
                    "description": "Actor recorded on the audit trail of every row removed.",
                },
            },
            "required": ["changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate the identifiers array shape, entity_type, and the actor.

        Raises:
            InvalidParamsError: if identifiers is present but not an array of
                UUID strings, entity_type names an entity that declares
                SOFT_DELETE_COLUMN=None, or changed_by is empty.
        """
        # Checked BEFORE the base validator, matching this command's earlier
        # convention: the schema enum already excludes non-purgeable types, so
        # the base would reject an out-of-enum value with a generic message
        # that never says why. The specific reason is the useful one.
        entity_type = params.get("entity_type")
        if isinstance(entity_type, str):
            try:
                entity_cls = resolve_entity_class(entity_type)
            except ValueError:
                entity_cls = None
            if entity_cls is not None and getattr(entity_cls, "SOFT_DELETE_COLUMN", None) is None:
                raise InvalidParamsError(
                    f"entity type {entity_type!r} declares SOFT_DELETE_COLUMN=None, so it has "
                    "no soft-deleted state and can never be part of a marked-set purge."
                )
        params = super().validate_params(params)
        identifiers = params.get("identifiers")
        if identifiers is not None:
            if not isinstance(identifiers, list):
                raise InvalidParamsError(f"identifiers must be an array, got {identifiers!r}.")
            for item in identifiers:
                if not isinstance(item, str):
                    raise InvalidParamsError(
                        f"identifiers must be an array of UUID strings, got {item!r}."
                    )
                try:
                    uuid.UUID(item)
                except ValueError as exc:
                    raise InvalidParamsError(
                        f"identifiers entry is not a valid UUID: {item!r}."
                    ) from exc
        changed_by = params.get("changed_by")
        if not isinstance(changed_by, str) or not changed_by.strip():
            raise InvalidParamsError("changed_by must be a non-empty string.")
        return params

    async def execute(
        self,
        changed_by: str,
        identifiers: list[str] | None = None,
        entity_type: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            # Re-checked here, not only in validate_params: execute() is a public
            # entry point that internal callers and tests invoke directly (same
            # reasoning this command has always used for this exact check).
            if entity_type is not None:
                entity_cls = resolve_entity_class(str(entity_type))
                if getattr(entity_cls, "SOFT_DELETE_COLUMN", None) is None:
                    raise DomainCommandError(
                        "ENTITY_NOT_PURGEABLE",
                        f"entity type {entity_type!r} declares SOFT_DELETE_COLUMN=None, so it "
                        "has no soft-deleted state and can never be part of a marked-set purge",
                    )
            entity_ids = (
                [uuid.UUID(item) for item in identifiers] if identifiers is not None else None
            )
            with db_connection() as conn:
                try:
                    outcome = hard_delete_marked_set(conn, entity_ids, changed_by=changed_by)
                except (NotFoundError, EntityNotSoftDeletedError) as exc:
                    # An explicit identifier that names no registered entity, or
                    # names one that is not currently marked: only an
                    # already-marked row may seed the fixed point.
                    raise DomainCommandError("RUNTIME_VALIDATION_ERROR", str(exc)) from exc
                except EntityReferencedError as exc:
                    described = _describe_blocking_referrers(conn, exc)
                    raise DomainCommandError(
                        "DELETE_BLOCKED",
                        _refusal_message(described),
                        {"blocking_referrers": described, "removed": []},
                    ) from exc
            removed = [str(entity_id) for entity_id in outcome.get("removed", [])]
            return SuccessResult(data={"removed": removed, "removed_count": len(removed)})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "version": cls.version,
            "description": cls.descr,
            "category": cls.category,
            "author": cls.author,
            "email": cls.email,
            "detailed_description": (
                "CR-7 G-006/T-001/A-002: this command reverses its earlier "
                "per-entity-type, report-one-and-continue purge onto the set-wise "
                "hard-delete engine (storage.runtime_hard_delete.hard_delete_marked_set, "
                "sibling step A-001). The shape it replaced "
                "(entity.purge_soft_deleted_batch, per entity type) admitted a row "
                "for physical removal by checking only its LIVE inbound references; a "
                "referrer that was itself already marked (soft-deleted) never blocked "
                "anything, and if that marked referrer was not purged in the very same "
                "run, it was left pointing at a row that no longer existed -- a "
                "dangling reference the purge itself manufactured, with no later pass "
                "that ever cleans it up. This command now computes the full fixed "
                "point of marked referrers first (via the relation index, not the "
                "live-only FK catalogue) and only then decides: if every referrer of "
                "the closed set is itself a member, the WHOLE set is removed "
                "atomically; if any referrer outside the set remains -- necessarily "
                "unmarked, since a marked one would already have been folded in -- the "
                "WHOLE operation is refused and nothing is removed. There is no more "
                "per-row refused list: one call either removes everything in its "
                "computed set or removes nothing, and a refusal names every external "
                "unmarked referrer that blocked it. entity_type no longer scopes "
                "anything: the engine is cross-kind by construction (a single call "
                "may close over and remove a mix of entity types), so a per-call "
                "type filter would only misleadingly narrow the STARTING set while "
                "the closure could still cross type boundaries regardless. It is kept "
                "purely as an optional pre-flight sanity check (still capable of the "
                "documented ENTITY_NOT_PURGEABLE refusal), never as a filter; "
                "identifiers (any mix of types, or omitted for every marked entity) "
                "is the only real scoping knob. limit is gone entirely: the atomic "
                "whole-set-or-nothing contract has no partial-batch concept to bound."
            ),
            "parameters": {
                "identifiers": {
                    "type": "array",
                    "description": (
                        "Explicit starting identifiers, of any soft-delete-capable "
                        "entity type -- the engine is cross-kind, so a single call may "
                        "close over and remove a mix of entity types in one pass. "
                        "Every one must already be marked (soft-deleted); an id that "
                        "is not refuses the call before any referrer is even looked "
                        "up. Omitted or null defaults to every entity currently "
                        "marked across every soft-delete-capable type -- "
                        "hard_delete_marked_set's own default, so 'purge everything "
                        "that is due' is the default call, not an opt-in."
                    ),
                    "required": False,
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Optional and informational only: never filters or scopes "
                        "identifiers (the engine is cross-kind), only pre-checks "
                        "up front that the named type can be purged at all."
                    ),
                    "required": False,
                },
                "changed_by": {
                    "type": "string",
                    "description": "Actor identity recorded on the audit trail of every row removed.",
                    "required": True,
                },
            },
            "return_value": {
                "success": {
                    "description": (
                        "The fixed-point-closed set that was actually removed, "
                        "atomically. Never partial: every id here was removed, in "
                        "referrer-before-target order."
                    ),
                    "data": {
                        "removed": (
                            "Stringified uuids of every row removed, ordered so a "
                            "referrer always precedes the target it referenced."
                        ),
                        "removed_count": "len(removed) -- for a caller that only needs the count.",
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
                    "description": "Purge every currently marked entity across every type (the default).",
                    "command": {"changed_by": "sweeper"},
                },
                {
                    "description": (
                        "Purge one explicit, already-marked todo, plus whatever "
                        "marked referrers close over it."
                    ),
                    "command": {
                        "identifiers": ["11111111-1111-1111-1111-111111111111"],
                        "changed_by": "orchestrator",
                    },
                },
            ],
            "error_cases": {
                "ENTITY_NOT_PURGEABLE": {
                    "description": (
                        "entity_type was supplied and names an entity whose class "
                        "declares SOFT_DELETE_COLUMN=None (concept, relation, step), "
                        "so it can never carry a marked (soft-deleted) state and can "
                        "never take part in this command's fixed-point purge. Purely "
                        "an optional up-front sanity check: entity_type never scopes "
                        "identifiers, so leaving it out never avoids this class of "
                        "mistake for an identifier of that type -- it just skips the "
                        "early, named refusal in favor of whatever hard_delete_marked_set "
                        "itself raises."
                    ),
                    "message": (
                        "entity type {entity_type} declares SOFT_DELETE_COLUMN=None, so it "
                        "has no soft-deleted state and can never be part of a marked-set purge"
                    ),
                    "solution": (
                        "Omit entity_type, or pass one whose class supports soft "
                        "delete; delete a non-soft-deletable entity through its own "
                        "delete command instead."
                    ),
                },
                "DELETE_BLOCKED": {
                    "description": (
                        "The fixed-point closure of the requested set still has at "
                        "least one referrer outside the set that is not itself "
                        "marked. This replaces the old per-row 'refused' list: the "
                        "refusal covers the WHOLE call and nothing was removed, not "
                        "even the members of the set that had no blocking referrer of "
                        "their own. details.blocking_referrers names every blocking "
                        "referrer by entity_type and id."
                    ),
                    "message": (
                        "hard delete refused: N external unmarked referrer(s) still "
                        "reference the requested set, so the whole operation is "
                        "refused and nothing was removed -- entity_type:id, ..."
                    ),
                    "solution": (
                        "Soft-delete every named blocking referrer first (or purge it, "
                        "if it is itself due), then retry the identical call; a "
                        "referrer that is marked before the retry is swept into the "
                        "fixed point automatically."
                    ),
                },
                "RUNTIME_VALIDATION_ERROR": {
                    "description": (
                        "A runtime write failed a shared runtime validation check. "
                        "For this command specifically: an explicit identifier in "
                        "identifiers that names no registered entity at all, or "
                        "names one that is not currently marked (soft-deleted) -- "
                        "only an already-marked row may seed the fixed point."
                    ),
                    "message": "runtime validation failed: {details}",
                    "solution": (
                        "Drop identifiers that do not resolve to a registered entity; "
                        "soft-delete a live row before naming it here, or omit it and "
                        "let it be swept in by the default call once it is marked."
                    ),
                },
            },
            "best_practices": [
                "The default call (identifiers omitted) is idempotent: with nothing "
                "currently marked it removes an empty set, so it is safe to schedule "
                "repeatedly.",
                "A DELETE_BLOCKED refusal removes nothing at all, not even the "
                "members of the requested set with no blocking referrer of their "
                "own; read details.blocking_referrers, clear every one, then retry "
                "the identical call.",
                "Pass a distinctive changed_by per caller; it is the only thing that "
                "distinguishes one purge run from another in the audit trail.",
                "Prefer the default call (identifiers omitted) over naming "
                "identifiers explicitly unless a narrower starting set is actually "
                "required: the default already covers every entity due for removal "
                "and needs no enumeration.",
            ],
        }
