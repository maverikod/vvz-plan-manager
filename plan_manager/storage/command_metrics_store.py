"""Command timing metrics persistence: append-only recorder for per-command invocation timing (C-005), read by the command_timing_stats aggregate (C-004)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

import psycopg

from plan_manager.domain.entity import DataclassEntity


ALLOWED_MODES: frozenset[str] = frozenset({"direct", "queued"})
ALLOWED_OUTCOMES: frozenset[str] = frozenset({"success", "error"})


@dataclass(frozen=True)
class CommandMetricRecord(DataclassEntity):
    """One append-only command-invocation timing row.

    Append-only: the table has no soft-delete/updated-at columns, so
    SOFT_DELETE_COLUMN/UPDATED_AT_COLUMN are None (which makes the base's
    soft_delete/delete/hard_delete/purge helpers raise instead of
    mutating), and crud_update is overridden to refuse. Records are created
    only through record_command_metric (a raw INSERT).
    """

    ENTITY_TYPE: ClassVar[str] = "command_metric"
    ENTITY_ID_FIELD: ClassVar[str] = "metric_uuid"
    TABLE_NAME: ClassVar[str] = "command_metric"
    COLUMNS: ClassVar[tuple[str, ...]] = (
        "uuid",
        "command_name",
        "duration_ms",
        "mode",
        "outcome",
        "created_at",
    )
    SOFT_DELETE_COLUMN: ClassVar[str | None] = None
    UPDATED_AT_COLUMN: ClassVar[str | None] = None

    metric_uuid: uuid.UUID
    command_name: str
    duration_ms: float
    mode: str
    outcome: str
    created_at: str

    @classmethod
    def crud_update(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("command_metric is append-only; records cannot be updated")

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.metric_uuid),
            "command_name": self.command_name,
            "duration_ms": self.duration_ms,
            "mode": self.mode,
            "outcome": self.outcome,
            "created_at": self.created_at,
        }


def _row_to_record(row: tuple[Any, ...]) -> CommandMetricRecord:
    return CommandMetricRecord(
        metric_uuid=row[0],
        command_name=row[1],
        duration_ms=row[2],
        mode=row[3],
        outcome=row[4],
        created_at=row[5].isoformat(),
    )


def record_command_metric(
    conn: psycopg.Connection,
    *,
    command_name: str,
    duration_ms: float,
    mode: str,
    outcome: str,
) -> CommandMetricRecord:
    """Append one immutable timing record for a command invocation.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the INSERT. This function never
            commits or closes conn; the caller's context manager controls
            transaction boundaries.
        command_name: str
            The invoked command's registered name.
        duration_ms: float
            Wall-clock duration of the invocation in milliseconds.
        mode: str
            One of ALLOWED_MODES ("direct" or "queued").
        outcome: str
            One of ALLOWED_OUTCOMES ("success" or "error").

    Returns:
        CommandMetricRecord
            The persisted metric record.

    Raises:
        ValueError
            If mode is not a member of ALLOWED_MODES, or outcome is not a
            member of ALLOWED_OUTCOMES.

    This function only INSERTs into command_metric. It never issues UPDATE
    or DELETE against command_metric.
    """
    if mode not in ALLOWED_MODES:
        raise ValueError(f"invalid mode: {mode}")
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")

    metric_uuid = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO command_metric "
        "(uuid, command_name, duration_ms, mode, outcome, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            metric_uuid,
            command_name,
            duration_ms,
            mode,
            outcome,
            created_at,
        ),
    )
    return CommandMetricRecord(
        metric_uuid=metric_uuid,
        command_name=command_name,
        duration_ms=duration_ms,
        mode=mode,
        outcome=outcome,
        created_at=created_at.isoformat(),
    )


def list_command_metrics(
    conn: psycopg.Connection,
    *,
    command_name: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> list[CommandMetricRecord]:
    """Return matching command_metric rows, oldest first.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the SELECT.
        command_name: str | None
            When given, restrict to rows with this exact command_name.
        created_after: str | None
            When given (ISO-8601 timestamp string), restrict to rows with
            created_at >= this value.
        created_before: str | None
            When given (ISO-8601 timestamp string), restrict to rows with
            created_at <= this value.

    Returns:
        list[CommandMetricRecord]
            The matching rows ordered by created_at ascending.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if command_name is not None:
        conditions.append("command_name = %s")
        params.append(command_name)
    if created_after is not None:
        conditions.append("created_at >= %s")
        params.append(created_after)
    if created_before is not None:
        conditions.append("created_at <= %s")
        params.append(created_before)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        "SELECT uuid, command_name, duration_ms, mode, outcome, created_at FROM command_metric"
        + where_clause
        + " ORDER BY created_at ASC",
        tuple(params),
    ).fetchall()
    return [_row_to_record(row) for row in rows]
