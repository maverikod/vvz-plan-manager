"""Plan aggregate: the root domain entity for a development plan.

Implements C-001 (Plan) per docs/plans/2026-07-02-plan-manager/spec.yaml.
Storage: PostgreSQL table `plan` (columns: uuid, name, status,
context_budget, head_revision_uuid), accessed via psycopg 3 with plain SQL
(no ORM). DDL for this table is owned by SQL migrations outside this module;
this module never emits DDL.
"""

from dataclasses import dataclass
import uuid

import psycopg


DEFAULT_CONTEXT_BUDGET = 4000


class PlanNotFoundError(ValueError):
    """Raised when no Plan row exists for a given uuid."""


@dataclass
class Plan:
    """Domain representation of the Plan aggregate (C-001).

    Attributes:
        uuid: Immutable primary identity of the plan (PostgreSQL uuid
            column, generated via uuid.uuid4() at creation).
        name: Human-readable plan name.
        status: Current lifecycle status stored as text; set to 'draft' at
            creation. Legal status values and transition enforcement
            (C-007) are owned outside this module.
        context_budget: User-set context budget in tokens consumed by
            prompt assembly; defaults to DEFAULT_CONTEXT_BUDGET at
            creation and is changeable later.
        head_revision_uuid: Identity of the current head revision in the
            version store (C-018), or None if no revision has been
            recorded yet.
    """

    uuid: uuid.UUID
    name: str
    status: str
    context_budget: int
    head_revision_uuid: uuid.UUID | None


def create_plan(
    conn: psycopg.Connection,
    name: str,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> Plan:
    """Create a new Plan aggregate row and return its domain representation.

    Validates that name is non-empty and context_budget is strictly
    positive, generates a new uuid4 primary identity, inserts the row with
    status 'draft' and a NULL head_revision_uuid, and returns the
    resulting Plan.

    Args:
        conn: Open psycopg 3 database connection to use for the insert.
        name: Human-readable plan name; must be non-empty after stripping
            whitespace.
        context_budget: User-set context budget in tokens; must be > 0.
            Defaults to DEFAULT_CONTEXT_BUDGET (4000).

    Returns:
        The newly created Plan with status 'draft' and head_revision_uuid
        set to None.

    Raises:
        ValueError: If name is empty (or whitespace-only) or if
            context_budget is not strictly positive.
    """
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    if context_budget <= 0:
        raise ValueError("context_budget must be > 0")
    plan_uuid = uuid.uuid4()
    conn.execute(
        "INSERT INTO plan (uuid, name, status, context_budget, "
        "head_revision_uuid) VALUES (%s, %s, 'draft', %s, NULL)",
        (plan_uuid, name, context_budget),
    )
    return Plan(
        uuid=plan_uuid,
        name=name,
        status="draft",
        context_budget=context_budget,
        head_revision_uuid=None,
    )


def get_plan(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> Plan:
    """Fetch a Plan aggregate by its primary identity.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        plan_uuid: Primary identity of the plan to fetch.

    Returns:
        The Plan matching plan_uuid.

    Raises:
        PlanNotFoundError: If no plan row with uuid = plan_uuid exists.
    """
    cur = conn.execute(
        "SELECT uuid, name, status, context_budget, head_revision_uuid "
        "FROM plan WHERE uuid = %s",
        (plan_uuid,),
    )
    row = cur.fetchone()
    if row is None:
        raise PlanNotFoundError(f"plan not found: {plan_uuid}")
    return Plan(
        uuid=row[0],
        name=row[1],
        status=row[2],
        context_budget=row[3],
        head_revision_uuid=row[4],
    )


def list_plans(conn: psycopg.Connection) -> list[Plan]:
    """Return the plan catalog: every Plan row ordered by name.

    Args:
        conn: Open psycopg 3 database connection to use for the query.

    Returns:
        A list of Plan objects, one per row in the plan table, ordered
        ascending by name. Empty list if no plans exist.
    """
    cur = conn.execute(
        "SELECT uuid, name, status, context_budget, head_revision_uuid "
        "FROM plan ORDER BY name"
    )
    return [
        Plan(
            uuid=row[0],
            name=row[1],
            status=row[2],
            context_budget=row[3],
            head_revision_uuid=row[4],
        )
        for row in cur.fetchall()
    ]


def set_context_budget(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    context_budget: int,
) -> None:
    """Update the context budget of an existing Plan.

    Args:
        conn: Open psycopg 3 database connection to use for the update.
        plan_uuid: Primary identity of the plan to update.
        context_budget: New context budget in tokens; must be > 0.

    Returns:
        None.

    Raises:
        ValueError: If context_budget is not strictly positive.
    """
    if context_budget <= 0:
        raise ValueError("context_budget must be > 0")
    conn.execute(
        "UPDATE plan SET context_budget = %s WHERE uuid = %s",
        (context_budget, plan_uuid),
    )


def set_head_revision(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    revision_uuid: uuid.UUID,
) -> None:
    """Advance the Plan's head revision pointer.

    Called by the version store (C-018) per revision during draft editing
    and on cascade publication, to record the plan's current head
    revision.

    Args:
        conn: Open psycopg 3 database connection to use for the update.
        plan_uuid: Primary identity of the plan whose head revision
            pointer is being advanced.
        revision_uuid: Identity of the revision to record as the new
            head.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE plan SET head_revision_uuid = %s WHERE uuid = %s",
        (revision_uuid, plan_uuid),
    )
