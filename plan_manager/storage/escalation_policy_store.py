"""Escalation policy persistence: create/get/list the standing escalation-policy record with audit trail, over the escalation_policy table (C-012)."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.escalation_policy import (
    EscalationPolicy,
    validate_escalation_policy,
    standing_escalation_policy_defaults,
)
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: dict[str, Any]) -> EscalationPolicy:
    """Convert a database row dict (column name -> value) to an EscalationPolicy instance."""
    return EscalationPolicy(
        policy_uuid=row["uuid"],
        schema_version=row["schema_version"],
        authority_typology=list(row["authority_typology"]),
        max_owner_rounds=row["max_owner_rounds"],
        terminal_parks_wave=row["terminal_parks_wave"],
        owner_timeout_parks=row["owner_timeout_parks"],
        active=row["active"],
        created_by=row["created_by"],
        created_at=row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
        updated_at=row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
        deleted_at=row["deleted_at"].isoformat() if isinstance(row["deleted_at"], datetime) and row["deleted_at"] else row["deleted_at"],
    )


def create_escalation_policy(
    conn: psycopg.Connection,
    *,
    created_by: str,
    schema_version: int | None = None,
    authority_typology: list[str] | None = None,
    max_owner_rounds: int | None = None,
    terminal_parks_wave: bool | None = None,
    owner_timeout_parks: bool | None = None,
    active: bool = True,
) -> EscalationPolicy:
    """Create and store a new escalation policy.

    Args:
        conn: Database connection.
        created_by: User or system identifier creating the policy.
        schema_version: Policy schema version; defaults from standing_escalation_policy_defaults if None.
        authority_typology: List of authority actions; defaults from standing_escalation_policy_defaults if None.
        max_owner_rounds: Maximum escalation rounds; defaults from standing_escalation_policy_defaults if None.
        terminal_parks_wave: Whether terminal escalations park the wave; defaults from standing_escalation_policy_defaults if None.
        owner_timeout_parks: Whether owner timeouts park; defaults from standing_escalation_policy_defaults if None.
        active: Whether the policy is active; defaults to True.

    Returns:
        The created EscalationPolicy instance.

    Raises:
        plan_manager.domain.runtime_validation.RuntimeValidationError: Raised by validate_escalation_policy if the built policy fails validation.
    """
    defaults = standing_escalation_policy_defaults()
    resolved_schema_version = schema_version if schema_version is not None else defaults["schema_version"]
    resolved_authority_typology = authority_typology if authority_typology is not None else defaults["authority_typology"]
    resolved_max_owner_rounds = max_owner_rounds if max_owner_rounds is not None else defaults["max_owner_rounds"]
    resolved_terminal_parks_wave = terminal_parks_wave if terminal_parks_wave is not None else defaults["terminal_parks_wave"]
    resolved_owner_timeout_parks = owner_timeout_parks if owner_timeout_parks is not None else defaults["owner_timeout_parks"]
    policy_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    policy = EscalationPolicy(
        policy_uuid=policy_uuid,
        schema_version=resolved_schema_version,
        authority_typology=list(resolved_authority_typology),
        max_owner_rounds=resolved_max_owner_rounds,
        terminal_parks_wave=resolved_terminal_parks_wave,
        owner_timeout_parks=resolved_owner_timeout_parks,
        active=active,
        created_by=created_by,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        deleted_at=None,
    )
    validate_escalation_policy(policy)
    conn.execute(
        "INSERT INTO escalation_policy (uuid, schema_version, authority_typology, max_owner_rounds, terminal_parks_wave, owner_timeout_parks, active, created_by, created_at, updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            policy_uuid,
            resolved_schema_version,
            Jsonb(list(resolved_authority_typology)),
            resolved_max_owner_rounds,
            resolved_terminal_parks_wave,
            resolved_owner_timeout_parks,
            active,
            created_by,
            now,
            now,
            None,
        ),
    )
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="escalation_policy",
        entity_id=policy_uuid,
        action="create",
        changed_by=created_by,
    )
    return policy


def get_escalation_policy(conn: psycopg.Connection, policy_uuid: uuid.UUID) -> EscalationPolicy | None:
    """Fetch one escalation policy by uuid, or None if no row matches."""
    cursor = conn.execute(
        "SELECT uuid, schema_version, authority_typology, max_owner_rounds, terminal_parks_wave, owner_timeout_parks, active, created_by, created_at, updated_at, deleted_at FROM escalation_policy WHERE uuid = %s",
        (policy_uuid,)
    )
    row = cursor.fetchone()
    if row is None:
        return None
    row_dict = {
        "uuid": row[0],
        "schema_version": row[1],
        "authority_typology": row[2],
        "max_owner_rounds": row[3],
        "terminal_parks_wave": row[4],
        "owner_timeout_parks": row[5],
        "active": row[6],
        "created_by": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "deleted_at": row[10],
    }
    return _row_to_record(row_dict)


def list_escalation_policies(conn: psycopg.Connection, *, active: bool | None = None, include_deleted: bool = False) -> list[EscalationPolicy]:
    """List escalation policy records. When active is given, restrict to rows whose active column equals it. Unless include_deleted is True, rows with a non-null deleted_at are excluded. Ordered by created_at ascending."""
    sql_parts = ["SELECT uuid, schema_version, authority_typology, max_owner_rounds, terminal_parks_wave, owner_timeout_parks, active, created_by, created_at, updated_at, deleted_at FROM escalation_policy WHERE 1=1"]
    params: list[Any] = []
    if active is not None:
        sql_parts.append("AND active = %s")
        params.append(active)
    if not include_deleted:
        sql_parts.append("AND deleted_at IS NULL")
    sql_parts.append("ORDER BY created_at ASC")
    sql = " ".join(sql_parts)
    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    result = []
    for row in rows:
        row_dict = {
            "uuid": row[0],
            "schema_version": row[1],
            "authority_typology": row[2],
            "max_owner_rounds": row[3],
            "terminal_parks_wave": row[4],
            "owner_timeout_parks": row[5],
            "active": row[6],
            "created_by": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "deleted_at": row[10],
        }
        result.append(_row_to_record(row_dict))
    return result


def get_active_escalation_policy(conn: psycopg.Connection) -> EscalationPolicy | None:
    """Return the current standing policy: the most recently created row with active = true and deleted_at IS NULL, or None if no such row exists."""
    cursor = conn.execute(
        "SELECT uuid, schema_version, authority_typology, max_owner_rounds, terminal_parks_wave, owner_timeout_parks, active, created_by, created_at, updated_at, deleted_at FROM escalation_policy WHERE active = TRUE AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row is None:
        return None
    row_dict = {
        "uuid": row[0],
        "schema_version": row[1],
        "authority_typology": row[2],
        "max_owner_rounds": row[3],
        "terminal_parks_wave": row[4],
        "owner_timeout_parks": row[5],
        "active": row[6],
        "created_by": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "deleted_at": row[10],
    }
    return _row_to_record(row_dict)
