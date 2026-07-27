"""Shared helpers for runtime CRUD delete commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import uuid

from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.entity import EntityReferencedError
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_audit_store import record_runtime_change


def delete_command_schema(id_param_name: str, id_description: str) -> dict[str, Any]:
    """Return the common delete-command schema for one UUID-addressed entity."""
    return {
        "type": "object",
        "properties": {
            id_param_name: {"type": "string", "format": "uuid", "description": id_description},
            "changed_by": {
                "type": "string",
                "description": "Identity of the actor performing the deletion; recorded on the audit trail.",
            },
            "hard": {
                "type": "boolean",
                "description": (
                    "When false (the default), soft-delete: recoverable, hidden from listings. "
                    "When true, irreversibly remove the row; gated by the inbound-reference integrity check."
                ),
                "default": False,
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "When true, write nothing: report the deletion target, mode, whether it would be blocked, "
                    "and the live referencing records as a dict mapping 'table.column' to the count of live "
                    "referencing rows."
                ),
                "default": False,
            },
        },
        "required": [id_param_name, "changed_by"],
        "additionalProperties": False,
    }


def delete_command_metadata_params(id_param_name: str, id_description: str) -> dict[str, Any]:
    """Return the common metadata params for one UUID-addressed delete command."""
    return {
        id_param_name: {"description": id_description, "type": "string", "required": True},
        "changed_by": {
            "description": "Identity of the actor performing the deletion; recorded on the audit trail.",
            "type": "string",
            "required": True,
        },
        "hard": {
            "description": (
                "False (default): soft-delete - recoverable, hidden from listings. "
                "True: irreversible row removal, gated by the inbound-reference integrity check."
            ),
            "type": "boolean",
            "required": False,
            "default": False,
        },
        "dry_run": {
            "description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.",
            "type": "boolean",
            "required": False,
            "default": False,
        },
    }


def validate_delete_uuid_param(params: dict[str, Any], id_param_name: str) -> dict[str, Any]:
    """Validate one UUID-shaped delete selector after the base schema check."""
    raw_value = params.get(id_param_name)
    if raw_value is not None:
        validate_uuid(raw_value)
    return params


def perform_runtime_delete(
    *,
    raw_entity_id: str,
    changed_by: str,
    hard: bool,
    dry_run: bool,
    entity_cls: Any,
    get_record: Callable[[Any, uuid.UUID], Any | None],
    soft_delete: Callable[..., Any],
    not_found_code: str,
    not_found_message: str,
    payload_key: str,
    entity_label: str | None = None,
    pre_delete: Callable[[Any, Any], None] | None = None,
    hard_delete: Callable[..., None] | None = None,
    audit_plan_uuid: Callable[[Any], Any | None] | None = None,
) -> SuccessResult:
    """Execute the common runtime delete lifecycle.

    Preserves the established command behavior:
    - `dry_run` reports references without mutating
    - `pre_delete` preserves command-specific guards (for example completed-plan refusal)
    - live inbound references still block non-dry-run deletion
    - `hard_delete` can preserve a legacy audited wrapper when a command already exposes one
    - otherwise `hard` delegates to `entity_cls.crud_hard_delete()` and records audit
    - soft delete delegates to the supplied store function
    """
    parsed_uuid = validate_uuid(raw_entity_id)
    with db_connection() as conn:
        record = get_record(conn, parsed_uuid)
        if record is None:
            raise DomainCommandError(not_found_code, not_found_message)
        references = entity_cls.crud_reference_counts(conn, parsed_uuid)
        if dry_run:
            return SuccessResult(
                data={
                    "dry_run": True,
                    "would_delete": str(parsed_uuid),
                    "mode": "hard" if hard else "soft",
                    "blocked": bool(references),
                    "references": references,
                }
            )
        if pre_delete is not None:
            pre_delete(conn, record)
        if references:
            raise EntityReferencedError(entity_label or entity_cls.entity_type(), parsed_uuid, references)
        if hard:
            if hard_delete is not None:
                hard_delete(conn, parsed_uuid, changed_by=changed_by)
            else:
                entity_cls.crud_hard_delete(conn, parsed_uuid, returning=False, require_soft_deleted=False)
                record_runtime_change(
                    conn,
                    plan_uuid=audit_plan_uuid(record) if audit_plan_uuid is not None else None,
                    entity_type=entity_cls.entity_type(),
                    entity_id=parsed_uuid,
                    action="hard_delete",
                    changed_by=changed_by,
                )
            return SuccessResult(data={"dry_run": False, "mode": "hard", "deleted_uuid": str(parsed_uuid)})
        deleted = soft_delete(conn, parsed_uuid, changed_by=changed_by)
        return SuccessResult(data={"dry_run": False, "mode": "soft", payload_key: deleted.to_payload()})
