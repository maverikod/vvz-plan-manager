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
