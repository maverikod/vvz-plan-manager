"""Command: reserve, release, or resolve an external project UUID.

A reservation claims an identifier in the identity registry before any row
exists for it, so that a project UUID a plan intends to create later cannot
collide with an existing plan, entity, or another reservation. External project
identifiers stay external: nothing here creates a local project row.
"""

from __future__ import annotations

import uuid as uuid_module
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.runtime.context import db_connection
from plan_manager.storage.errors import DuplicateNameError, NotFoundError
from plan_manager.storage.identity import (
    RESERVED_KIND,
    release_project_reservation,
    reserve_project_uuid,
    resolve_entity_identity,
)
from plan_manager.storage.runtime_audit_store import record_runtime_change

_ACTIONS = ("reserve", "release", "resolve")

_RESERVATION_ENTITY_TYPE = "project_uuid_reservation"


class ProjectUuidReserveCommand(Command):
    """Reserve, release, or resolve a project UUID namespace reservation."""

    name: ClassVar[str] = "project_uuid_reserve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Reserve a future external project UUID in the identity registry, "
        "release a reservation, or resolve one."
    )
    category: ClassVar[str] = "project"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "reserve claims the identifier, release frees it, "
                        "resolve reports who holds it."
                    ),
                    "enum": list(_ACTIONS),
                },
                "project_uuid": {
                    "type": "string",
                    "format": "uuid",
                    "description": "The external project UUID to reserve, release, or resolve.",
                },
                "reserved_by": {
                    "type": "string",
                    "description": "Actor claiming or releasing the reservation; recorded in the audit trail.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional free-text justification; accepted only with action=reserve.",
                },
            },
            "required": ["action", "project_uuid", "reserved_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate the action, the identifier, and the action-specific fields.

        Raises:
            InvalidParamsError: if action is outside the enum, project_uuid is
                not a UUID, reserved_by is empty for a mutating action, or note
                is supplied with an action other than reserve.
        """
        params = super().validate_params(params)
        action = params.get("action")
        if action not in _ACTIONS:
            raise InvalidParamsError(
                f"Invalid action: {action!r}. Must be one of {', '.join(_ACTIONS)}."
            )
        raw_uuid = params.get("project_uuid")
        try:
            uuid_module.UUID(str(raw_uuid))
        except (ValueError, AttributeError, TypeError):
            raise InvalidParamsError(f"Invalid project_uuid: {raw_uuid!r} is not a UUID.")
        reserved_by = params.get("reserved_by")
        if not isinstance(reserved_by, str) or not reserved_by.strip():
            raise InvalidParamsError("reserved_by must be a non-empty string.")
        if params.get("note") is not None and action != "reserve":
            raise InvalidParamsError("note is accepted only with action='reserve'.")
        return params

    async def execute(
        self,
        action: str,
        project_uuid: str,
        reserved_by: str,
        note: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            entity_id = uuid_module.UUID(str(project_uuid))
            with db_connection() as conn:
                if action == "reserve":
                    return self._reserve(conn, entity_id, reserved_by, note)
                if action == "release":
                    return self._release(conn, entity_id, reserved_by)
                return self._resolve(conn, entity_id)
        except Exception as exc:
            return map_exception(exc)

    @staticmethod
    def _reserve(conn: Any, entity_id: uuid_module.UUID, reserved_by: str, note: str | None):
        try:
            payload = reserve_project_uuid(conn, entity_id, reserved_by, note)
        except DuplicateNameError as exc:
            # A collision is refused deterministically and writes NO audit row:
            # nothing changed, so there is nothing to record.
            raise DomainCommandError("DUPLICATE_ID", str(exc)) from exc
        record_runtime_change(
            conn,
            plan_uuid=None,
            entity_type=_RESERVATION_ENTITY_TYPE,
            entity_id=entity_id,
            action="project_uuid_reserve",
            changed_by=reserved_by,
            changed_fields={"kind": RESERVED_KIND, "note": note},
        )
        return SuccessResult(data=_serialize(payload))

    @staticmethod
    def _release(conn: Any, entity_id: uuid_module.UUID, reserved_by: str):
        try:
            release_project_reservation(conn, entity_id)
        except NotFoundError as exc:
            raise DomainCommandError("RESERVATION_NOT_FOUND", str(exc)) from exc
        record_runtime_change(
            conn,
            plan_uuid=None,
            entity_type=_RESERVATION_ENTITY_TYPE,
            entity_id=entity_id,
            action="project_uuid_release",
            changed_by=reserved_by,
            changed_fields={"kind": RESERVED_KIND},
        )
        return SuccessResult(data={"project_uuid": str(entity_id), "released": True})

    @staticmethod
    def _resolve(conn: Any, entity_id: uuid_module.UUID):
        # resolve never audits: it is a read.
        try:
            record = resolve_entity_identity(conn, entity_id)
        except NotFoundError as exc:
            raise DomainCommandError(
                "RESERVATION_NOT_FOUND", f"project uuid reservation not found: {entity_id}"
            ) from exc
        if record.get("kind") != RESERVED_KIND:
            raise DomainCommandError(
                "RESERVATION_NOT_FOUND",
                f"project uuid reservation not found: {entity_id} "
                f"(identifier is registered as kind={record.get('kind')})",
            )
        return SuccessResult(data=_serialize(record))

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
                "Claims, frees, or inspects a namespace reservation in the entity identity "
                "registry. A reservation occupies a UUID without creating any local row, so a "
                "plan that will create a new external project can take its identifier at "
                "planning time and be certain no plan, entity, or later reservation can collide "
                "with it. Reserve and release each append one runtime audit record; resolve is a "
                "read and audits nothing. External project identifiers remain external: this "
                "command never creates a local project table row."
            ),
            "parameters": {
                "action": {
                    "type": "string",
                    "description": "One of reserve, release, resolve.",
                    "required": True,
                },
                "project_uuid": {
                    "type": "string",
                    "description": "The external project UUID to act on.",
                    "required": True,
                },
                "reserved_by": {
                    "type": "string",
                    "description": "Actor identity recorded in the audit trail.",
                    "required": True,
                },
                "note": {
                    "type": "string",
                    "description": "Optional justification, accepted only with action=reserve.",
                    "required": False,
                },
            },
            "return_value": {
                "success": {
                    "description": "The reservation payload for reserve and resolve, or a released flag for release.",
                    "data": {
                        "project_uuid": "The reserved identifier.",
                        "kind": "Always 'project_reservation' for a reservation.",
                        "reserved_by": "The actor holding the reservation.",
                        "note": "The optional justification, or null.",
                        "created_at": "ISO 8601 timestamp of the reservation.",
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
                    "description": "Reserve a project UUID at planning time.",
                    "command": {
                        "action": "reserve",
                        "project_uuid": "11111111-1111-1111-1111-111111111111",
                        "reserved_by": "orchestrator",
                        "note": "new doc-store project, created after CR-6 ships",
                    },
                },
                {
                    "description": "Resolve a reservation to see who holds it.",
                    "command": {
                        "action": "resolve",
                        "project_uuid": "11111111-1111-1111-1111-111111111111",
                        "reserved_by": "orchestrator",
                    },
                },
            ],
            "error_cases": {
                "DUPLICATE_ID": {
                    "description": (
                        "The identifier is already registered, for an entity of any kind or "
                        "for another reservation. No audit record is written."
                    ),
                    "message": "entity id already registered: {id} (kind={kind}, table={table})",
                    "solution": (
                        "Resolve the identifier to see what holds it, then reserve a different "
                        "UUID or release the existing reservation first."
                    ),
                },
                "RESERVATION_NOT_FOUND": {
                    "description": (
                        "No reservation exists for the supplied project uuid. Returned by "
                        "release and by resolve, including when the identifier is registered "
                        "as an ordinary entity rather than a reservation."
                    ),
                    "message": "project uuid reservation not found: {project_uuid}",
                    "solution": "Reserve the identifier first, or check for a typo in the UUID.",
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
                "Reserve at planning time, as soon as a plan commits to creating a new external "
                "project, not at creation time; the whole value of the reservation is the window "
                "before the project exists.",
                "A reservation is not a project. No local project row is ever created for it, and "
                "external project UUIDs stay owned by the external system.",
                "Release a reservation the plan abandons, so the identifier does not stay claimed "
                "by a project that will never exist.",
                "Read the written audit records back with audit_list(action='project_uuid_reserve') "
                "or audit_list(action='project_uuid_release').",
            ],
        }


def _serialize(record: dict[str, Any]) -> dict[str, Any]:
    """Render a registry record as a JSON-safe payload."""
    payload = dict(record)
    for key in ("id", "project_uuid"):
        if payload.get(key) is not None:
            payload[key] = str(payload[key])
    payload.setdefault("project_uuid", payload.get("id"))
    created_at = payload.get("created_at")
    if created_at is not None and not isinstance(created_at, str):
        payload["created_at"] = created_at.isoformat()
    payload.pop("table_name", None)
    payload.pop("entity_type", None)
    return payload
