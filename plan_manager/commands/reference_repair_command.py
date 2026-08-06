"""Command: repair scalar UUID references whose target row does not exist.

CR-7 G-006/T-002/A-002. Exposes the repair store's three named operations
(:mod:`plan_manager.storage.reference_repair_store`) as one command with an
``operation`` parameter, in increasing order of danger:

1. ``find`` -- read-only. Scans every catalogued single-uuid reference column
   for values the entity identity registry cannot resolve. Always safe.
2. ``clear`` -- nulls one offending field, admitted only when the source
   property's schema statically declares the column nullable; reports the
   (source_table, source_column, source_ref) it changed. NOT gated by
   ``dry_run``: the store's ``clear_reference`` has no preview mode of its
   own, so a ``clear`` call always acts (or is refused outright by
   nullability, never previewed).
3. ``delete_carriers`` -- removes the entities carrying references ``clear``
   cannot repair. ``dry_run`` (default true) reports the would-remove set and
   admission verdict without writing; ``dry_run=false`` performs the real
   removal via the set-wise purge engine underneath the store.

The registry recovery operations the store also exposes (``audit_registry``,
``restore_missing_identities``, ``remove_unreferenced_extra_identities``,
``rebuild_relation_index``, C-009) are deliberately NOT surfaced here: the
frozen step names exactly three operations for this command.

Nothing in this module writes directly to a table or to the relation index --
every write is delegated to the repair store, which this module does not
modify. See the store's own module docstring for the NULLABILITY rationale
behind ``clear``'s refusal and the fixed-point-closure rationale behind
``delete_carriers``.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.domain.entity import EntityNotSoftDeletedError
from plan_manager.runtime.context import db_connection
from plan_manager.storage.errors import NotFoundError
from plan_manager.storage.reference_repair_store import (
    clear_reference,
    delete_carrier,
    find_dangling_references,
    nullability_for,
)

_OPERATIONS: tuple[str, ...] = ("find", "clear", "delete_carriers")


class ReferenceRepairCommand(Command):
    """Find, clear, or remove-the-carrier-of dangling scalar UUID references."""

    name: ClassVar[str] = "reference_repair"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Repair scalar UUID references whose target row does not exist: find "
        "them (read-only), clear a statically-nullable offending column, or "
        "remove the carrier of one that clear cannot repair (dry-run by default)."
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
                "operation": {
                    "type": "string",
                    "description": (
                        "Which repair-store operation to run. 'find': read-only "
                        "scan for dangling scalar UUID references. 'clear': null "
                        "one dangling reference field whose column is statically "
                        "nullable. 'delete_carriers': remove the entities "
                        "carrying references 'clear' cannot repair."
                    ),
                    "enum": list(_OPERATIONS),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "Applies only to operation='delete_carriers'; ignored "
                        "for 'find' and 'clear' (clear has no preview mode of "
                        "its own -- it either acts or is refused). True (the "
                        "default) never writes: it reports the fixed-point "
                        "would-remove set and admission verdict. False performs "
                        "the real removal via the set-wise purge engine."
                    ),
                    "default": True,
                },
                "source_table": {
                    "type": "string",
                    "description": (
                        "operation='clear' only: the catalogued source table of "
                        "the dangling column (a REFERENCE_CATALOG key), e.g. as "
                        "reported in one operation='find' finding's source_table."
                    ),
                },
                "source_column": {
                    "type": "string",
                    "description": (
                        "operation='clear' only: the catalogued source column of "
                        "the dangling reference, paired with source_table -- as "
                        "reported in one operation='find' finding's source_column."
                    ),
                },
                "source_ref": {
                    "type": "string",
                    "format": "uuid",
                    "description": (
                        "operation='clear' only: the referring row's own uuid, "
                        "as reported in one operation='find' finding's source_ref."
                    ),
                },
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                    "minItems": 1,
                    "description": (
                        "operation='delete_carriers' only: the explicit "
                        "starting set of entity ids to remove (or preview "
                        "removing). A live call (dry_run=false) requires every "
                        "id here to already be marked (soft-deleted) -- the "
                        "fixed-point closure then pulls in every marked "
                        "referrer automatically, exactly like runtime_purge_batch."
                    ),
                },
                "changed_by": {
                    "type": "string",
                    "description": (
                        "operation='delete_carriers' with dry_run=false only: "
                        "actor recorded on the audit trail of every row "
                        "removed. Required for a live call; ignored otherwise."
                    ),
                },
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Enforce the operation-specific parameter set the flat schema cannot.

        The schema only requires ``operation`` (the enum itself is schema-
        enforced by the base validator); everything else is conditionally
        required depending on which of the three operations was named, so
        that requirement is checked here instead.

        Raises:
            InvalidParamsError: a 'clear' call is missing source_table,
                source_column, or a well-formed source_ref; a
                'delete_carriers' call is missing a non-empty entity_ids
                array, carries a malformed entry, or (when dry_run=false)
                is missing a non-empty changed_by.
        """
        params = super().validate_params(params)
        operation = params.get("operation")
        if operation == "clear":
            missing = [
                name
                for name in ("source_table", "source_column", "source_ref")
                if name not in params
            ]
            if missing:
                raise InvalidParamsError(
                    f"operation='clear' requires {', '.join(missing)}."
                )
            source_ref = params["source_ref"]
            if not isinstance(source_ref, str):
                raise InvalidParamsError(
                    f"source_ref must be a UUID string, got {source_ref!r}."
                )
            try:
                uuid.UUID(source_ref)
            except ValueError as exc:
                raise InvalidParamsError(
                    f"source_ref is not a valid UUID: {source_ref!r}."
                ) from exc
        elif operation == "delete_carriers":
            entity_ids = params.get("entity_ids")
            if not isinstance(entity_ids, list) or not entity_ids:
                raise InvalidParamsError(
                    "operation='delete_carriers' requires a non-empty entity_ids array."
                )
            for item in entity_ids:
                if not isinstance(item, str):
                    raise InvalidParamsError(
                        f"entity_ids must be an array of UUID strings, got {item!r}."
                    )
                try:
                    uuid.UUID(item)
                except ValueError as exc:
                    raise InvalidParamsError(
                        f"entity_ids entry is not a valid UUID: {item!r}."
                    ) from exc
            if params.get("dry_run") is False:
                changed_by = params.get("changed_by")
                if not isinstance(changed_by, str) or not changed_by.strip():
                    raise InvalidParamsError(
                        "changed_by must be a non-empty string when dry_run is false."
                    )
        return params

    async def execute(
        self,
        operation: str,
        dry_run: bool = True,
        source_table: str | None = None,
        source_column: str | None = None,
        source_ref: str | None = None,
        entity_ids: list[str] | None = None,
        changed_by: str = "system",
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                if operation == "find":
                    findings = find_dangling_references(conn)
                    return SuccessResult(
                        data={
                            "operation": "find",
                            "findings": [_serialize_finding(f) for f in findings],
                            "total": len(findings),
                        }
                    )
                if operation == "clear":
                    try:
                        result = clear_reference(
                            conn,
                            source_table=source_table,
                            source_column=source_column,
                            source_ref=uuid.UUID(source_ref),
                        )
                    except KeyError as exc:
                        message = str(exc.args[0]) if exc.args else str(exc)
                        raise DomainCommandError("RUNTIME_VALIDATION_ERROR", message) from exc
                    except PermissionError as exc:
                        raise DomainCommandError(
                            "REFERENCE_NOT_CLEARABLE",
                            str(exc),
                            {
                                "source_table": source_table,
                                "source_column": source_column,
                                "nullability": nullability_for(source_table, source_column),
                            },
                        ) from exc
                    return SuccessResult(
                        data={"operation": "clear", **_serialize_clear(result)}
                    )
                # operation == "delete_carriers": the schema enum admits no
                # fourth value, and validate_params already required a
                # non-empty, well-formed entity_ids array.
                ids = [uuid.UUID(item) for item in (entity_ids or [])]
                try:
                    result = delete_carrier(
                        conn, ids, dry_run=dry_run, changed_by=changed_by
                    )
                except (NotFoundError, EntityNotSoftDeletedError) as exc:
                    # Mirrors runtime_purge_batch_command's identical mapping:
                    # an explicit id that names no registered entity, or one
                    # that is not currently marked, is a runtime validation
                    # failure -- only an already-marked row may seed the
                    # fixed point for a live removal. EntityReferencedError
                    # (the whole-set refusal) is left to map_exception's own
                    # generic DELETE_BLOCKED mapping below, unmodified.
                    raise DomainCommandError("RUNTIME_VALIDATION_ERROR", str(exc)) from exc
                return SuccessResult(
                    data={
                        "operation": "delete_carriers",
                        **_serialize_delete_carriers(result),
                    }
                )
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
                "One command over the repair store's three named operations "
                "(plan_manager.storage.reference_repair_store), in increasing "
                "order of danger. 'find' scans every catalogued single-uuid "
                "reference column against the entity identity registry and "
                "reports every value that does not resolve, read-only and "
                "audit-free. 'clear' nulls one dangling field and retires its "
                "relation-index triple in the same transaction, admitted only "
                "when the source property's schema statically declares the "
                "column nullable (see nullability_for); it is NOT gated by "
                "dry_run -- the store has no clear preview, so a clear call "
                "either acts or is refused outright. 'delete_carriers' removes "
                "the entities carrying references clear could not repair, "
                "delegating the real removal to the same set-wise purge engine "
                "runtime_purge_batch uses (hard_delete_marked_set), so every "
                "rule of that discipline applies unchanged -- including that "
                "every explicit starting id must already be marked. dry_run "
                "(default true) never writes for delete_carriers: it "
                "independently walks the same fixed-point closure over marked "
                "referrers and reports the same admission verdict the engine "
                "would reach, purely by reading. Only dry_run=false performs "
                "the real removal. Nothing here writes outside the repair "
                "store's own three functions; the store itself is unmodified "
                "by this command."
            ),
            "parameters": {
                "operation": {
                    "type": "string",
                    "description": "Which repair-store operation to run.",
                    "required": True,
                    "enum": list(_OPERATIONS),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "delete_carriers only (ignored otherwise); default "
                        "true. False performs the real removal."
                    ),
                    "required": False,
                },
                "source_table": {
                    "type": "string",
                    "description": "clear only: the catalogued source table.",
                    "required": False,
                },
                "source_column": {
                    "type": "string",
                    "description": "clear only: the catalogued source column.",
                    "required": False,
                },
                "source_ref": {
                    "type": "string",
                    "description": "clear only: the referring row's own uuid.",
                    "required": False,
                },
                "entity_ids": {
                    "type": "array",
                    "description": (
                        "delete_carriers only: the explicit starting set of "
                        "entity ids to remove or preview removing."
                    ),
                    "required": False,
                },
                "changed_by": {
                    "type": "string",
                    "description": (
                        "delete_carriers with dry_run=false only: actor "
                        "recorded on the audit trail of every row removed."
                    ),
                    "required": False,
                },
            },
            "return_value": {
                "success": {
                    "description": (
                        "The shape depends on operation. find: {findings: "
                        "[{source_table, source_column, source_ref, "
                        "property_name, missing_target, target_table, "
                        "nullability}, ...], total}. clear: {source_table, "
                        "source_column, source_ref, cleared: true}. "
                        "delete_carriers dry-run: {dry_run: true, "
                        "would_remove, blocked_by, unresolved, admissible}. "
                        "delete_carriers live: {dry_run: false, removed}. "
                        "Every variant also echoes operation."
                    ),
                    "data": {
                        "operation": "The operation that was run, echoed back.",
                        "findings": "find only: one entry per dangling reference.",
                        "total": "find only: len(findings).",
                        "source_table": "find/clear: the catalogued source table.",
                        "source_column": "find/clear: the catalogued source column.",
                        "source_ref": "find/clear: the referring row's own uuid.",
                        "cleared": "clear only: always true on success.",
                        "dry_run": "delete_carriers only: whether this call wrote anything.",
                        "would_remove": (
                            "delete_carriers dry-run only: the closed working "
                            "set that would be removed."
                        ),
                        "blocked_by": (
                            "delete_carriers dry-run only: the relation-index "
                            "triples that would refuse the whole operation "
                            "(empty when admissible)."
                        ),
                        "unresolved": (
                            "delete_carriers dry-run only: given ids the "
                            "identity registry does not know."
                        ),
                        "admissible": (
                            "delete_carriers dry-run only: true when blocked_by "
                            "is empty -- a live call with the identical "
                            "entity_ids would succeed."
                        ),
                        "removed": "delete_carriers live only: stringified uuids actually removed.",
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
                    "description": "Scan for every dangling scalar UUID reference.",
                    "command": {"operation": "find"},
                },
                {
                    "description": (
                        "Clear one nullable dangling field a prior find "
                        "reported (todo_item.anchor_plan_uuid is NULLABLE)."
                    ),
                    "command": {
                        "operation": "clear",
                        "source_table": "todo_item",
                        "source_column": "anchor_plan_uuid",
                        "source_ref": "11111111-1111-1111-1111-111111111111",
                    },
                },
                {
                    "description": (
                        "Preview removing the carrier of an irreparable "
                        "dangling reference (dry_run defaults to true)."
                    ),
                    "command": {
                        "operation": "delete_carriers",
                        "entity_ids": ["22222222-2222-2222-2222-222222222222"],
                    },
                },
                {
                    "description": "Actually remove it, after confirming the dry-run was admissible.",
                    "command": {
                        "operation": "delete_carriers",
                        "entity_ids": ["22222222-2222-2222-2222-222222222222"],
                        "dry_run": False,
                        "changed_by": "repair-bot",
                    },
                },
            ],
            "error_cases": {
                "REFERENCE_NOT_CLEARABLE": {
                    "description": (
                        "operation='clear' named a column whose nullability "
                        "verdict (nullability_for) is NOT_NULLABLE or UNKNOWN. "
                        "The store deliberately treats both alike: an "
                        "unclearable column is unclearable whether the schema "
                        "forbids it or the module could not find out. Nothing "
                        "was written."
                    ),
                    "message": (
                        "{source_table}.{source_column} is {nullability}; "
                        "clear refused (only a statically-nullable column may "
                        "be cleared)"
                    ),
                    "solution": (
                        "Use operation='delete_carriers' on the referring row "
                        "instead -- an unclearable field can only be repaired "
                        "by removing its carrier."
                    ),
                },
                "RUNTIME_VALIDATION_ERROR": {
                    "description": (
                        "operation='clear' named a (source_table, "
                        "source_column) pair that is not a REFERENCE_CATALOG "
                        "key at all; or operation='delete_carriers' with "
                        "dry_run=false named an explicit entity id that "
                        "resolves to no registered entity, or one that is not "
                        "currently marked (soft-deleted) -- only an "
                        "already-marked row may seed the fixed point."
                    ),
                    "message": "runtime validation failed: {details}",
                    "solution": (
                        "For clear: pass a (source_table, source_column) pair "
                        "reported by a prior operation='find' call. For "
                        "delete_carriers: soft-delete a live row before naming "
                        "it, or drop an id that does not resolve at all."
                    ),
                },
                "DELETE_BLOCKED": {
                    "description": (
                        "operation='delete_carriers' with dry_run=false: the "
                        "fixed-point closure of the requested entity_ids still "
                        "has at least one referrer outside the set that is not "
                        "itself marked, so the whole removal is refused and "
                        "nothing was removed -- identical to runtime_purge_batch's "
                        "refusal. Retry operation='delete_carriers' with "
                        "dry_run=true (the default) first to see this in "
                        "advance via blocked_by/admissible."
                    ),
                    "message": (
                        "hard delete refused: N external unmarked referrer(s) "
                        "still reference the requested set, so the whole "
                        "operation is refused and nothing was removed"
                    ),
                    "solution": (
                        "Soft-delete every blocking referrer first (or purge "
                        "it, if it is itself due), then retry the identical "
                        "call; a referrer that is marked before the retry is "
                        "swept into the fixed point automatically."
                    ),
                },
            },
            "best_practices": [
                "Run operation='find' first. Its nullability field tells you "
                "which findings operation='clear' can repair (NULLABLE) and "
                "which need operation='delete_carriers' instead "
                "(NOT_NULLABLE or UNKNOWN).",
                "operation='clear' is not gated by dry_run: it always acts "
                "when the column is clearable, or is always refused when it "
                "is not. There is no preview for clear -- nullability_for's "
                "verdict, visible in every find finding, is the preview.",
                "For operation='delete_carriers', always inspect the "
                "dry_run=true (default) response's admissible/blocked_by "
                "fields before retrying with dry_run=false. A blocked "
                "preview never becomes an admissible live call by itself; "
                "the blocking referrer must be cleared or marked first.",
                "A live delete_carriers call requires every id in entity_ids "
                "to already be marked (soft-deleted) -- exactly like "
                "runtime_purge_batch. Soft-delete the referring row through "
                "its own delete command before naming it here.",
                "Prefer clearing a NULLABLE dangling reference over deleting "
                "its carrier where both are possible: clear repairs the row "
                "in place, delete_carriers removes it (and any marked "
                "referrer chain) irreversibly.",
            ],
        }


def _serialize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Render one find_dangling_references finding with stringified uuids."""
    return {
        "source_table": finding["source_table"],
        "source_column": finding["source_column"],
        "source_ref": str(finding["source_ref"]),
        "property_name": finding["property_name"],
        "missing_target": str(finding["missing_target"]),
        "target_table": finding["target_table"],
        "nullability": finding["nullability"],
    }


def _serialize_clear(result: dict[str, Any]) -> dict[str, Any]:
    """Render one clear_reference result with a stringified source_ref."""
    return {
        "source_table": result["source_table"],
        "source_column": result["source_column"],
        "source_ref": str(result["source_ref"]),
        "cleared": result["cleared"],
    }


def _serialize_triple(triple: dict[str, Any]) -> dict[str, Any]:
    """Render one relation-index triple (as reported by referrers_of) JSON-safe."""
    target_ref = triple.get("target_ref")
    return {
        "source_ref": str(triple["source_ref"]),
        "target_ref": str(target_ref) if target_ref is not None else None,
        "field_ref": str(triple["field_ref"]),
    }


def _serialize_delete_carriers(result: dict[str, Any]) -> dict[str, Any]:
    """Render one delete_carrier result (either shape) with stringified uuids."""
    if result.get("dry_run"):
        return {
            "dry_run": True,
            "would_remove": [str(item) for item in result["would_remove"]],
            "blocked_by": [_serialize_triple(triple) for triple in result["blocked_by"]],
            "unresolved": [str(item) for item in result["unresolved"]],
            "admissible": result["admissible"],
        }
    return {
        "dry_run": False,
        "removed": [str(item) for item in result["removed"]],
    }
