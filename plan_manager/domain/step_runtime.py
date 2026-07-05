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
    conn.execute(
        "INSERT INTO step_runtime (step_uuid, plan_uuid, data) "
        "VALUES (%s, %s, %s) ON CONFLICT (step_uuid) DO NOTHING",
        (step_uuid, plan_uuid, Jsonb(empty_runtime_record())),
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
