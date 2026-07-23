"""Escalation routing persistence helpers: routing column projection, chain assembly, and blocking-linkage resolution over the escalation table (C-009)."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any

import psycopg

from plan_manager.domain.escalation import Escalation
from plan_manager.domain.primary_anchor import anchor_from_columns


ROUTING_INSERT_COLUMNS: list[str] = [
    "addressee_level",
    "addressee_role",
    "forwarded_from_uuid",
    "chain_root_uuid",
    "sweep_priority",
    "blocks_subtree",
]


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    """Cast a candidate routing UUID column value to uuid.UUID, passing None through unchanged."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def routing_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project the six routing columns off a raw escalation row dict, uuid-casting the two reference columns.

    Parameters:
        row: A raw escalation table row as a dict keyed by column name, containing at least
            the keys addressee_level, addressee_role, forwarded_from_uuid, chain_root_uuid,
            sweep_priority, blocks_subtree.

    Returns:
        dict[str, Any]: A dict with exactly the six keys addressee_level, addressee_role,
            forwarded_from_uuid, chain_root_uuid, sweep_priority, blocks_subtree; the two
            uuid columns are uuid.UUID instances (or None), the rest pass through unchanged.
    """
    return {
        "addressee_level": row["addressee_level"],
        "addressee_role": row["addressee_role"],
        "forwarded_from_uuid": _uuid_or_none(row["forwarded_from_uuid"]),
        "chain_root_uuid": _uuid_or_none(row["chain_root_uuid"]),
        "sweep_priority": row["sweep_priority"],
        "blocks_subtree": row["blocks_subtree"],
    }


def routing_insert_params(
    *,
    addressee_level: str | None,
    addressee_role: str | None,
    forwarded_from_uuid: uuid.UUID | None,
    chain_root_uuid: uuid.UUID | None,
    sweep_priority: int | None,
    blocks_subtree: bool,
) -> tuple[Any, ...]:
    """Build the six-value params tuple matching ROUTING_INSERT_COLUMNS order for an INSERT.

    Parameters:
        addressee_level: The addressee level routing value, or None.
        addressee_role: The addressee role routing value, or None.
        forwarded_from_uuid: The escalation this one was forwarded from, or None.
        chain_root_uuid: The originating escalation of the forwarding chain, or None.
        sweep_priority: The nice-scale sweep priority, or None.
        blocks_subtree: Whether this open escalation blocks its anchored step's subtree.

    Returns:
        tuple[Any, ...]: The six values in ROUTING_INSERT_COLUMNS order, ready to append to
            an INSERT params tuple.
    """
    return (
        addressee_level,
        addressee_role,
        forwarded_from_uuid,
        chain_root_uuid,
        sweep_priority,
        blocks_subtree,
    )


_ESCALATION_ROW_COLUMNS: tuple[str, ...] = (
    "uuid",
    "primary_anchor_type",
    "anchor_project_id",
    "anchor_file_path",
    "anchor_plan_uuid",
    "anchor_revision_uuid",
    "anchor_step_uuid",
    "anchor_step_path",
    "anchor_ref_id",
    "reason",
    "from_level",
    "to_level",
    "status",
    "resolution",
    "resolved_by",
    "resolved_at",
    "created_by",
    "created_at",
    "updated_at",
    "deleted_at",
    "addressee_level",
    "addressee_role",
    "forwarded_from_uuid",
    "chain_root_uuid",
    "sweep_priority",
    "blocks_subtree",
)


def _fetch_escalation_row(conn: psycopg.Connection, escalation_uuid: uuid.UUID) -> dict[str, Any] | None:
    """Fetch one escalation row by uuid as a column-name-keyed dict, or None if no row exists."""
    cursor = conn.execute(
        "SELECT uuid, primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid, "
        "anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id, reason, from_level, "
        "to_level, status, resolution, resolved_by, resolved_at, created_by, created_at, updated_at, "
        "deleted_at, addressee_level, addressee_role, forwarded_from_uuid, chain_root_uuid, "
        "sweep_priority, blocks_subtree FROM escalation WHERE uuid = %s",
        (escalation_uuid,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(_ESCALATION_ROW_COLUMNS, row))


def _row_to_escalation(row: dict[str, Any]) -> Escalation:
    """Convert a raw escalation row dict (as produced by _fetch_escalation_row) into an Escalation, hydrating routing fields via routing_from_row."""
    anchor_columns = {
        "primary_anchor_type": row["primary_anchor_type"],
        "anchor_project_id": row["anchor_project_id"],
        "anchor_file_path": row["anchor_file_path"],
        "anchor_plan_uuid": row["anchor_plan_uuid"],
        "anchor_revision_uuid": row["anchor_revision_uuid"],
        "anchor_step_uuid": row["anchor_step_uuid"],
        "anchor_step_path": row["anchor_step_path"],
        "anchor_ref_id": row["anchor_ref_id"],
    }
    anchor = anchor_from_columns(anchor_columns)
    routing = routing_from_row(row)

    created_at_str = row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"]
    updated_at_str = row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"]
    resolved_at_str = (
        row["resolved_at"].isoformat() if isinstance(row["resolved_at"], datetime) and row["resolved_at"] else row["resolved_at"]
    )
    deleted_at_str = (
        row["deleted_at"].isoformat() if isinstance(row["deleted_at"], datetime) and row["deleted_at"] else row["deleted_at"]
    )

    return Escalation(
        escalation_uuid=row["uuid"],
        primary_anchor_type=anchor.anchor_type,
        anchor_project_id=anchor.project_id,
        anchor_file_path=anchor.file_path,
        anchor_plan_uuid=anchor.plan_uuid,
        anchor_revision_uuid=anchor.revision_uuid,
        anchor_step_uuid=anchor.step_uuid,
        anchor_step_path=anchor.step_path,
        anchor_ref_id=anchor.ref_id,
        reason=row["reason"],
        from_level=row["from_level"],
        to_level=row["to_level"],
        status=row["status"],
        resolution=row["resolution"],
        resolved_by=row["resolved_by"],
        resolved_at=resolved_at_str,
        created_by=row["created_by"],
        created_at=created_at_str,
        updated_at=updated_at_str,
        deleted_at=deleted_at_str,
        **routing,
    )


def assemble_chain(conn: psycopg.Connection, escalation_uuid: uuid.UUID) -> list[Escalation]:
    """Walk the forwarding chain containing escalation_uuid and return it ordered root-to-tip.

    The forwarding chain is the linked list formed by each escalation's forwarded_from_uuid
    pointing at the escalation it was forwarded from. Starting at escalation_uuid, this walks
    backward via forwarded_from_uuid until forwarded_from_uuid is None (the chain root),
    collecting every escalation visited, then returns them ordered from the root (first) to
    escalation_uuid (last, the tip of the walk).

    Parameters:
        conn: An open psycopg 3 connection.
        escalation_uuid: The uuid of any escalation in the chain to assemble.

    Returns:
        list[Escalation]: The chain from root to escalation_uuid, in that order. Returns an
            empty list if no escalation row with escalation_uuid exists. Returns a single-item
            list containing only escalation_uuid's own record when that record's
            forwarded_from_uuid is None (it is itself the chain root).
    """
    row = _fetch_escalation_row(conn, escalation_uuid)
    if row is None:
        return []
    chain_rows: list[dict[str, Any]] = [row]
    current = row
    while current["forwarded_from_uuid"] is not None:
        parent_row = _fetch_escalation_row(conn, current["forwarded_from_uuid"])
        if parent_row is None:
            break
        chain_rows.append(parent_row)
        current = parent_row
    chain_rows.reverse()
    return [_row_to_escalation(r) for r in chain_rows]


def list_blocking_escalations(
    conn: psycopg.Connection,
    *,
    anchor_plan_uuid: uuid.UUID,
    anchor_step_uuid: uuid.UUID | None,
    anchor_step_path: str | None = None,
    include_subtree: bool = True,
) -> list[Escalation]:
    """Return open escalations blocking a step (and, when requested, its subtree).

    An escalation blocks a step for dispatch purposes when it is open (status = 'open'),
    not soft-deleted (deleted_at IS NULL), anchored to anchor_plan_uuid, and either:
      - its anchor_step_uuid equals the given anchor_step_uuid (direct block), or
      - include_subtree is True AND its blocks_subtree column is True AND anchor_step_path
        is given AND its own anchor_step_path equals anchor_step_path or starts with
        anchor_step_path followed by '/' (the step itself or a descendant in its subtree).

    Parameters:
        conn: An open psycopg 3 connection.
        anchor_plan_uuid: The plan the candidate blocking escalations must be anchored to.
        anchor_step_uuid: The step uuid to check direct blocks against, or None to skip the
            direct-match clause.
        anchor_step_path: The step path used for subtree prefix matching, or None to skip the
            subtree-match clause.
        include_subtree: When False, only direct anchor_step_uuid matches are returned,
            regardless of blocks_subtree or anchor_step_path.

    Returns:
        list[Escalation]: The matching open, non-deleted escalations, ordered by created_at
            ascending. Empty list when neither anchor_step_uuid nor (include_subtree and
            anchor_step_path) is usable to build a match clause.
    """
    clauses: list[str] = ["status = 'open'", "deleted_at IS NULL", "anchor_plan_uuid = %s"]
    params: list[Any] = [anchor_plan_uuid]
    match_clauses: list[str] = []
    if anchor_step_uuid is not None:
        match_clauses.append("anchor_step_uuid = %s")
        params.append(anchor_step_uuid)
    if include_subtree and anchor_step_path is not None:
        match_clauses.append("(blocks_subtree = TRUE AND (anchor_step_path = %s OR anchor_step_path LIKE %s))")
        params.append(anchor_step_path)
        params.append(anchor_step_path + "/%")
    if not match_clauses:
        return []
    clauses.append("(" + " OR ".join(match_clauses) + ")")
    sql = (
        "SELECT uuid, primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid, "
        "anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id, reason, from_level, "
        "to_level, status, resolution, resolved_by, resolved_at, created_by, created_at, updated_at, "
        "deleted_at, addressee_level, addressee_role, forwarded_from_uuid, chain_root_uuid, "
        "sweep_priority, blocks_subtree FROM escalation WHERE " + " AND ".join(clauses) + " ORDER BY created_at ASC"
    )
    cursor = conn.execute(sql, params)
    rows = [dict(zip(_ESCALATION_ROW_COLUMNS, r)) for r in cursor.fetchall()]
    return [_row_to_escalation(r) for r in rows]
