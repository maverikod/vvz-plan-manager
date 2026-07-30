"""Command: purge a batch of already soft-deleted rows for one entity type.

Second phase of the two-phase deletion contract (C-009). The first phase marks a
row deleted; this one removes it physically, but only where nothing still refers
to it. Rows that are still referenced come back in ``refused`` rather than
failing the batch, so one blocked row never hides the progress made on the rest.

This command writes NO audit record of its own. The hard-delete guard beneath it
is the single audit point and records one row per removal and one per refusal;
a write here would audit every purged row twice.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.runtime.context import db_connection
from plan_manager.storage.reference_catalog import (
    purge_capable_entity_types,
    resolve_entity_class,
)

_DEFAULT_LIMIT = 1000
_MAX_LIMIT = 10000


class RuntimePurgeBatchCommand(Command):
    """Physically remove a batch of soft-deleted rows of one entity type."""

    name: ClassVar[str] = "runtime_purge_batch"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Purge a batch of already soft-deleted rows of one entity type, "
        "reporting per-row removals and reference-blocked refusals."
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
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Entity type to purge. This is the ENTITY_TYPE, never the table "
                        "name: 'comment', not 'runtime_comment'; 'todo', not 'todo_item'."
                    ),
                    # Derived from the live entity registry, so an entity that
                    # gains or loses soft-delete support changes this enum by its
                    # own declaration and no hand-kept list can drift from it.
                    "enum": purge_capable_entity_types(),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to consider in this batch.",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "default": _DEFAULT_LIMIT,
                },
                "changed_by": {
                    "type": "string",
                    "description": "Actor recorded on every audit record the purge produces.",
                },
            },
            "required": ["entity_type", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate the entity type, the actor, and the batch limit.

        Raises:
            InvalidParamsError: if entity_type names no entity, names one that
                declares SOFT_DELETE_COLUMN=None, changed_by is empty, or limit
                is outside the documented range.
        """
        # Checked BEFORE the base validator: the schema enum already excludes
        # non-purgeable types, so the base would reject 'concept' with a generic
        # enum message that never says why. The specific reason is the useful
        # one, and it must survive.
        entity_type = params.get("entity_type")
        if isinstance(entity_type, str):
            try:
                entity_cls = resolve_entity_class(entity_type)
            except ValueError:
                entity_cls = None
            if entity_cls is not None and getattr(entity_cls, "SOFT_DELETE_COLUMN", None) is None:
                raise InvalidParamsError(
                    f"entity type {entity_type!r} declares SOFT_DELETE_COLUMN=None, so it has "
                    "no soft-deleted state to purge; it can only be deleted directly."
                )
        params = super().validate_params(params)
        entity_type = params.get("entity_type")
        try:
            resolve_entity_class(str(entity_type))
        except ValueError as exc:
            raise InvalidParamsError(str(exc)) from exc
        changed_by = params.get("changed_by")
        if not isinstance(changed_by, str) or not changed_by.strip():
            raise InvalidParamsError("changed_by must be a non-empty string.")
        limit = params.get("limit", _DEFAULT_LIMIT)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise InvalidParamsError(f"limit must be an integer, got {limit!r}.")
        if not 1 <= limit <= _MAX_LIMIT:
            raise InvalidParamsError(f"limit must be between 1 and {_MAX_LIMIT}, got {limit}.")
        return params

    async def execute(
        self,
        entity_type: str,
        changed_by: str,
        limit: int = _DEFAULT_LIMIT,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            entity_cls = resolve_entity_class(str(entity_type))
            # Re-checked here, not only in validate_params: execute() is a public
            # entry point that internal callers and tests invoke directly, and a
            # DomainCommandError raised from validate_params would escape the
            # adapter's run() unmapped. This is the path that yields the
            # documented ENTITY_NOT_PURGEABLE code.
            if getattr(entity_cls, "SOFT_DELETE_COLUMN", None) is None:
                raise DomainCommandError(
                    "ENTITY_NOT_PURGEABLE",
                    f"entity type {entity_type!r} declares SOFT_DELETE_COLUMN=None, so it "
                    "has no soft-deleted state to purge",
                )
            with db_connection() as conn:
                outcome = entity_cls.crud_purge_soft_deleted_batch(
                    conn, limit=limit, changed_by=changed_by
                )
            return SuccessResult(
                data={
                    "entity_type": entity_type,
                    "deleted": outcome.get("deleted", []),
                    "refused": outcome.get("refused", []),
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
                "Completes the two-phase deletion contract. Rows already marked deleted are "
                "removed physically, one at a time, each admitted only after the central "
                "reference guard confirms nothing live still points at it. A row that is still "
                "referenced is reported in refused with the referring column counts and the "
                "batch continues, so one blocked row never masks the rows that were removed. "
                "Every removal and every refusal is audited once, by the guard; this command "
                "adds no audit record of its own."
            ),
            "parameters": {
                "entity_type": {
                    "type": "string",
                    "description": (
                        "The ENTITY_TYPE to purge, never the table name. Only types whose "
                        "class declares a soft-delete column are accepted."
                    ),
                    "required": True,
                },
                "changed_by": {
                    "type": "string",
                    "description": "Actor identity recorded on each audit record.",
                    "required": True,
                },
                "limit": {
                    "type": "integer",
                    "description": f"Batch size, 1..{_MAX_LIMIT}. Defaults to {_DEFAULT_LIMIT}.",
                    "required": False,
                },
            },
            "return_value": {
                "success": {
                    "description": "Per-row outcomes for the batch.",
                    "data": {
                        "entity_type": "The entity type that was purged.",
                        "deleted": "List of the removed row payloads.",
                        "refused": (
                            "List of {id, references} objects for rows a live reference "
                            "still blocks. Identifiers are stringified."
                        ),
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
                    "description": "Purge up to 100 soft-deleted todos.",
                    "command": {
                        "entity_type": "todo",
                        "changed_by": "orchestrator",
                        "limit": 100,
                    },
                },
                {
                    "description": "Purge soft-deleted comments with the default batch size.",
                    "command": {"entity_type": "comment", "changed_by": "orchestrator"},
                },
            ],
            "error_cases": {
                "ENTITY_NOT_PURGEABLE": {
                    "description": (
                        "entity_type names an entity whose class declares "
                        "SOFT_DELETE_COLUMN=None (concept, relation, step) and therefore has "
                        "no soft-deleted state a purge could act on. An entity_type naming no "
                        "entity at all is rejected earlier, by the schema enum."
                    ),
                    "message": (
                        "entity type {entity_type} declares SOFT_DELETE_COLUMN=None, so it "
                        "has no soft-deleted state to purge"
                    ),
                    "solution": (
                        "Pick an entity type from the schema enum; delete a non-soft-deletable "
                        "entity through its own delete command instead."
                    ),
                },
                "RUNTIME_VALIDATION_ERROR": {
                    "description": (
                        "A runtime write failed a shared runtime validation check, for example "
                        "an actor identity that does not satisfy the audit trail's contract."
                    ),
                    "message": "runtime validation failed: {details}",
                    "solution": "Correct the offending field and retry.",
                },
            },
            "best_practices": [
                "Batch purge is idempotent: a second run over the same entity type finds nothing "
                "left to remove and is a no-op, so it is safe to schedule repeatedly.",
                "Read refused rather than treating a non-empty result as failure. A refusal names "
                "the referring column, so detaching or purging that referrer first lets the next "
                "run succeed.",
                "Pass a distinctive changed_by per caller; it is the only thing that distinguishes "
                "one purge run from another in the audit trail.",
                "Keep limit modest on a busy database: the whole batch runs in one transaction.",
            ],
        }
