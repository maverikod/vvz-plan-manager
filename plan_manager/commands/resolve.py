"""Plan identity resolution shared by every command (C-023, C-001)."""

import uuid

import psycopg

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.plan import Plan, get_plan


def resolve_plan(conn: psycopg.Connection, plan: str) -> Plan:
    """Resolve a plan by UUID string or unique name (C-001)."""
    try:
        plan_uuid = uuid.UUID(plan)
    except ValueError:
        with conn.cursor() as cur:
            cur.execute("SELECT uuid FROM plan WHERE name = %s", (plan,))
            row = cur.fetchone()
        if row is not None:
            return get_plan(conn, row[0])
        raise DomainCommandError("PLAN_NOT_FOUND", f"plan not found: {plan}")
    try:
        return get_plan(conn, plan_uuid)
    except ValueError:
        raise DomainCommandError("PLAN_NOT_FOUND", f"plan not found: {plan}")


def resolve_plan_guarded(conn: psycopg.Connection, plan: str) -> Plan:
    """Resolve a plan (as resolve_plan) and refuse when it is completed.

    Bug c3950b83 (plan-level completion lock; L1 design ruling
    2026-07-23, superseding an earlier per-step-status carve-out attempt):
    once a plan's `completed` flag is set, every mutating command that
    resolves its `plan` parameter to that plan via this function refuses
    with the PLAN_COMPLETED domain code. Only plan_completed_set and
    plan_comment_set call resolve_plan directly (unguarded), so the flag
    itself, and the plan's comment, always stay reachable. Read-only
    commands also call resolve_plan directly, since reads are never
    blocked by completion.

    Args:
        conn: Open psycopg 3 database connection.
        plan: Plan UUID string or unique name.

    Returns:
        The resolved Plan.

    Raises:
        DomainCommandError: PLAN_NOT_FOUND (propagated from resolve_plan),
            or PLAN_COMPLETED when the resolved plan's `completed` flag is
            True.
    """
    p = resolve_plan(conn, plan)
    if p.completed:
        raise DomainCommandError(
            "PLAN_COMPLETED",
            f"plan {p.uuid} is marked completed; call plan_completed_set "
            "to unset the completion lock before mutating it",
        )
    return p
