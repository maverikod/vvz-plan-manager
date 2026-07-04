"""Per-plan PostgreSQL advisory lock (C-019) serializing cascades and identifier assignment.

All plan-lock state lives in PostgreSQL: there are no lock files and no
in-process lock state that a server restart could lose.
"""

from __future__ import annotations

import hashlib
import uuid

import psycopg


class PlanLockError(RuntimeError):
    """Raised when a plan advisory lock operation reports the lock was not held."""


def plan_lock_key(plan_uuid: uuid.UUID) -> int:
    """Derive the deterministic PostgreSQL advisory lock key for a plan.

    Args:
        plan_uuid: The immutable UUID identity of the plan.

    Returns:
        A deterministic signed 64-bit integer key derived from the SHA-256
        digest of the plan UUID's string representation, suitable as the
        key argument to PostgreSQL's pg_advisory_lock and
        pg_advisory_unlock functions.
    """
    digest = hashlib.sha256(str(plan_uuid).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def acquire_plan_lock(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Acquire the per-plan PostgreSQL session-level advisory lock.

    Blocks until the lock is held by this session.

    Args:
        conn: An open psycopg 3 connection; its database session will
            hold the advisory lock.
        plan_uuid: The immutable UUID identity of the plan to lock.

    Returns:
        None.
    """
    key = plan_lock_key(plan_uuid)
    conn.execute("SELECT pg_advisory_lock(%s)", (key,))


def release_plan_lock(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Release the per-plan PostgreSQL session-level advisory lock.

    Args:
        conn: An open psycopg 3 connection whose database session
            currently holds the advisory lock.
        plan_uuid: The immutable UUID identity of the plan to unlock.

    Returns:
        None.

    Raises:
        PlanLockError: If PostgreSQL's pg_advisory_unlock reports (via
            its boolean result column) that the lock was not held by
            this session.
    """
    key = plan_lock_key(plan_uuid)
    row = conn.execute("SELECT pg_advisory_unlock(%s)", (key,)).fetchone()
    if row is None or row[0] is False:
        raise PlanLockError(
            f"plan advisory lock not held by this session for plan {plan_uuid}"
        )
