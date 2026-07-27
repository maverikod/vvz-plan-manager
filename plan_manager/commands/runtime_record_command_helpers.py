"""Shared helpers for simple runtime get/update command flows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import uuid

from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection


def get_command_schema(id_param_name: str, id_description: str) -> dict[str, Any]:
    """Return the common get-command schema for one UUID-addressed entity."""
    return {
        "type": "object",
        "properties": {
            id_param_name: {"type": "string", "format": "uuid", "description": id_description},
        },
        "required": [id_param_name],
        "additionalProperties": False,
    }


def get_command_metadata_params(id_param_name: str, id_description: str) -> dict[str, Any]:
    """Return the common metadata params fragment for one UUID-addressed get command."""
    return {
        id_param_name: {"description": id_description, "type": "string", "required": True},
    }


def require_mutable_patch(update_fields: dict[str, Any], message: str) -> None:
    """Reject patch calls that do not supply any mutable field value."""
    if all(value is None for value in update_fields.values()):
        raise RuntimeValidationError(message)


def perform_runtime_get(
    *,
    raw_entity_id: str,
    get_record: Callable[[Any, uuid.UUID], Any | None],
    not_found_code: str,
    not_found_message: str,
    db_connect: Callable[[], Any] | None = None,
) -> SuccessResult:
    """Fetch one live runtime record by UUID and return its payload."""
    parsed_uuid = validate_uuid(raw_entity_id)
    if db_connect is None:
        db_connect = db_connection
    with db_connect() as conn:
        record = get_record(conn, parsed_uuid)
        if record is None:
            raise DomainCommandError(not_found_code, not_found_message)
        return SuccessResult(data=record.to_payload())


def perform_runtime_create(
    *,
    create_record: Callable[..., Any],
    create_fields: dict[str, Any] | None = None,
    prepare_create_fields: Callable[[Any], dict[str, Any]] | None = None,
    db_connect: Callable[[], Any] | None = None,
    build_result_data: Callable[[Any], dict[str, Any]] | None = None,
) -> SuccessResult:
    """Create one live runtime record and return its payload."""
    if (create_fields is None) == (prepare_create_fields is None):
        raise ValueError("provide exactly one of create_fields or prepare_create_fields")
    if db_connect is None:
        db_connect = db_connection
    with db_connect() as conn:
        prepared_fields = create_fields if create_fields is not None else prepare_create_fields(conn)
        record = create_record(conn, **prepared_fields)
        if build_result_data is None:
            return SuccessResult(data=record.to_payload())
        return SuccessResult(data=build_result_data(record))


def perform_runtime_update(
    *,
    raw_entity_id: str,
    get_record: Callable[[Any, uuid.UUID], Any | None],
    update_record: Callable[..., Any],
    changed_by: str,
    not_found_code: str,
    not_found_message: str,
    update_fields: dict[str, Any],
    db_connect: Callable[[], Any] | None = None,
) -> SuccessResult:
    """Update one live runtime record after confirming it exists."""
    return perform_guarded_runtime_update(
        raw_entity_id=raw_entity_id,
        get_record=get_record,
        update_record=update_record,
        changed_by=changed_by,
        not_found_code=not_found_code,
        not_found_message=not_found_message,
        update_fields=update_fields,
        db_connect=db_connect,
    )


def perform_guarded_runtime_update(
    *,
    raw_entity_id: str,
    get_record: Callable[[Any, uuid.UUID], Any | None],
    update_record: Callable[..., Any],
    changed_by: str,
    not_found_code: str,
    not_found_message: str,
    update_fields: dict[str, Any],
    resolve_scope: Callable[[Any], Any] | None = None,
    pre_update: Callable[[Any, Any, dict[str, Any]], None] | None = None,
    before_store_update: Callable[[Any, uuid.UUID, Any, dict[str, Any]], None] | None = None,
    post_update: Callable[[Any, uuid.UUID, Any, Any, dict[str, Any]], None] | None = None,
    build_result_data: Callable[[Any], dict[str, Any]] | None = None,
    db_connect: Callable[[], Any] | None = None,
) -> SuccessResult:
    """Update one live runtime record with optional guarded hooks.

    Hook order is:
    1. optional resolve_scope(conn)
    2. load existing record or raise *_NOT_FOUND
    3. optional pre_update(conn, existing, update_fields)
    4. optional before_store_update(conn, entity_id, existing, update_fields)
    5. update_record(...)
    6. optional post_update(conn, entity_id, existing, updated_record, update_fields)
    """
    parsed_uuid = validate_uuid(raw_entity_id)
    if db_connect is None:
        db_connect = db_connection
    with db_connect() as conn:
        if resolve_scope is not None:
            resolve_scope(conn)
        existing = get_record(conn, parsed_uuid)
        if existing is None:
            raise DomainCommandError(not_found_code, not_found_message)
        if pre_update is not None:
            pre_update(conn, existing, update_fields)
        if before_store_update is not None:
            before_store_update(conn, parsed_uuid, existing, update_fields)
        record = update_record(conn, parsed_uuid, changed_by=changed_by, **update_fields)
        if post_update is not None:
            post_update(conn, parsed_uuid, existing, record, update_fields)
        if build_result_data is None:
            return SuccessResult(data=record.to_payload())
        return SuccessResult(data=build_result_data(record))
