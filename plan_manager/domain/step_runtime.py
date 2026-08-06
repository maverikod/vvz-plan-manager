"""Runtime parameters for plan steps.

This store is intentionally separate from step definition storage. Updates
do not record revisions, do not use cascade admission, and do not touch step
status, gate inputs, or scoring inputs.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.entity import DataclassEntity


class _StepRuntimeRow(DataclassEntity):
    """Descriptor-only seat for the step_runtime attribute bag (CR-7 G-004).

    The table is keyed by step_uuid rather than an identity of its own (it is
    in the registry's EXCLUDED_TABLES), so the engine's Python-side identity
    registration stays off; the class exists to route the row INSERT through
    the unified creation path.
    """

    ENTITY_TYPE = "step_runtime"
    TABLE_NAME = "step_runtime"
    ID_COLUMN = "step_uuid"
    COLUMNS = ("step_uuid", "plan_uuid", "data")
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    CREATED_AT_COLUMN = None
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "step_uuid"  # the attribute bag is owned by its step


EMPTY_RUNTIME_RECORD: dict[str, Any] = {
    "activations": [],
    "execution_attempts": [],
    "journal_aggregates": None,
    "authoring": None,
}


def empty_runtime_record() -> dict[str, Any]:
    """Return a fresh empty runtime record."""
    return deepcopy(EMPTY_RUNTIME_RECORD)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _append_unique(
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    id_key: str,
) -> list[dict[str, Any]]:
    result = [dict(entry) for entry in current]
    seen = {
        entry.get(id_key)
        for entry in result
        if isinstance(entry, dict) and entry.get(id_key) is not None
    }
    for entry in incoming:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get(id_key)
        if entry_id is None or entry_id in seen:
            continue
        result.append(dict(entry))
        seen.add(entry_id)
    return result


def merge_runtime_record(
    current: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge a partial runtime payload into an existing runtime record."""
    result = empty_runtime_record()
    if current:
        result.update(deepcopy(current))
        result.setdefault("activations", [])
        result.setdefault("execution_attempts", [])
        result.setdefault("journal_aggregates", None)
        result.setdefault("authoring", None)

    if "activations" in payload:
        incoming = payload["activations"]
        if isinstance(incoming, list):
            result["activations"] = _append_unique(
                list(result.get("activations") or []),
                incoming,
                "activation_id",
            )
    if "execution_attempts" in payload:
        incoming = payload["execution_attempts"]
        if isinstance(incoming, list):
            result["execution_attempts"] = _append_unique(
                list(result.get("execution_attempts") or []),
                incoming,
                "attempt_id",
            )
    if "journal_aggregates" in payload:
        incoming = payload["journal_aggregates"]
        current_aggregate = result.get("journal_aggregates")
        incoming_time = _parse_time(
            incoming.get("last_linked_at") if isinstance(incoming, dict) else None
        )
        current_time = _parse_time(
            current_aggregate.get("last_linked_at")
            if isinstance(current_aggregate, dict)
            else None
        )
        if isinstance(incoming, dict) and (
            current_time is None
            or incoming_time is None
            or incoming_time >= current_time
        ):
            result["journal_aggregates"] = dict(incoming)
    if "authoring" in payload:
        incoming = payload["authoring"]
        result["authoring"] = dict(incoming) if isinstance(incoming, dict) else incoming
    return result


def ensure_runtime_row(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    step_uuid: uuid.UUID,
) -> None:
    """Ensure an empty runtime row exists for one step."""
    # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
    # engine's creation path; this module no longer composes INSERT SQL.
    # The legacy ON CONFLICT DO NOTHING idempotence is kept as an explicit
    # existence check before the engine create.
    row = conn.execute(
        "SELECT 1 FROM step_runtime WHERE step_uuid = %s",
        (step_uuid,),
    ).fetchone()
    if row is None:
        _StepRuntimeRow.crud_create(
            conn,
            {
                "step_uuid": step_uuid,
                "plan_uuid": plan_uuid,
                "data": Jsonb(empty_runtime_record()),
            },
            returning=False,
        )


def get_runtime_record(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    step_uuid: uuid.UUID,
) -> dict[str, Any]:
    """Read one step runtime record, returning an empty record when absent."""
    cur = conn.execute(
        "SELECT data FROM step_runtime WHERE plan_uuid = %s AND step_uuid = %s",
        (plan_uuid, step_uuid),
    )
    row = cur.fetchone()
    if row is None:
        return empty_runtime_record()
    record = empty_runtime_record()
    record.update(row[0] or {})
    return record


def report_runtime_record(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    step_uuid: uuid.UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Merge and persist runtime data for one step with row-level atomicity."""
    ensure_runtime_row(conn, plan_uuid, step_uuid)
    cur = conn.execute(
        "SELECT data FROM step_runtime WHERE step_uuid = %s FOR UPDATE",
        (step_uuid,),
    )
    row = cur.fetchone()
    current = row[0] if row is not None else empty_runtime_record()
    merged = merge_runtime_record(current, payload)
    conn.execute(
        "UPDATE step_runtime SET data = %s WHERE step_uuid = %s",
        (Jsonb(merged), step_uuid),
    )
    return merged
