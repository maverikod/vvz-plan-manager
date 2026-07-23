"""Plan aggregate: the root domain entity for a development plan.

Implements C-001 (Plan) per docs/plans/2026-07-02-plan-manager/spec.yaml.
Storage: PostgreSQL table `plan` (columns: uuid, name, status,
context_budget, head_revision_uuid, project_ids, primary_project_id),
accessed via psycopg 3 with plain SQL
(no ORM). DDL for this table is owned by SQL migrations outside this module;
this module never emits DDL.
"""

from dataclasses import dataclass
from datetime import datetime
import uuid

import psycopg

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck


DEFAULT_CONTEXT_BUDGET = 4000


class PlanNotFoundError(ValueError):
    """Raised when no Plan row exists for a given uuid."""


class PlanCompletedError(ValueError):
    """Raised when a mutating command is refused because its target plan is
    marked completed (bug c3950b83: plan-level completion lock). Mapped to
    the PLAN_COMPLETED domain code at the commands layer."""


@dataclass
class Plan(DataclassEntity):
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
        deleted_at: Soft-deletion timestamp, or None for a live plan. A
            soft-deleted plan is hidden from the default plan catalog but
            otherwise behaves normally and stays resolvable by uuid or
            name.
        completed: Plan-level completion lock (bug c3950b83). Defaults to
            False. When True, every mutating command that resolves its
            `plan` parameter to this plan via resolve_plan_guarded refuses
            with PLAN_COMPLETED; only plan_completed_set and
            plan_comment_set stay reachable. Always directly settable via
            plan_completed_set regardless of freeze or completion state.
        comment: Free-form note attached to the plan, or None. Always
            directly settable via plan_comment_set regardless of freeze or
            completion state.
    """

    ENTITY_TYPE = "plan"
    ENTITY_ID_FIELD = "uuid"
    TABLE_NAME = "plan"
    HARD_DELETE_REFERENCE_CHECKS = (
        ReferenceCheck("todo_item", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("model_binding", "plan_uuid", live_column="deleted_at"),
        ReferenceCheck("runtime_comment", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "plan_uuid", live_column="deleted_at"),
        ReferenceCheck("escalation", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "source_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_impact", "target_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix_propagation", "linked_plan_uuid", live_column="deleted_at"),
    )

    uuid: uuid.UUID
    name: str
    status: str
    context_budget: int
    head_revision_uuid: uuid.UUID | None
    project_ids: list[str]
    primary_project_id: str | None
    deleted_at: datetime | None = None
    completed: bool = False
    comment: str | None = None


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
        "head_revision_uuid, project_ids, primary_project_id, completed, comment) "
        "VALUES (%s, %s, 'draft', %s, NULL, %s, NULL, false, NULL)",
        (plan_uuid, name, context_budget, []),
    )
    return Plan(
        uuid=plan_uuid,
        name=name,
        status="draft",
        context_budget=context_budget,
        head_revision_uuid=None,
        project_ids=[],
        primary_project_id=None,
        completed=False,
        comment=None,
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
        "SELECT uuid, name, status, context_budget, head_revision_uuid, "
        "project_ids, primary_project_id, deleted_at, completed, comment "
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
        project_ids=list(row[5]) if row[5] else [],
        primary_project_id=row[6],
        deleted_at=row[7],
        completed=row[8],
        comment=row[9],
    )


def list_plans(conn: psycopg.Connection, show_deleted: bool = False) -> list[Plan]:
    """Return the plan catalog ordered by name.

    Args:
        conn: Open psycopg 3 database connection to use for the query.
        show_deleted: When False (the default), soft-deleted plans (those
            with a non-NULL ``deleted_at``) are excluded. When True, every
            plan is returned, including soft-deleted ones.

    Returns:
        A list of Plan objects ordered ascending by name. Empty list if no
        plans match.
    """
    sql = (
        "SELECT uuid, name, status, context_budget, head_revision_uuid, "
        "project_ids, primary_project_id, deleted_at, completed, comment "
        "FROM plan"
    )
    if not show_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY name"
    cur = conn.execute(sql)
    return [
        Plan(
            uuid=row[0],
            name=row[1],
            status=row[2],
            context_budget=row[3],
            head_revision_uuid=row[4],
            project_ids=list(row[5]) if row[5] else [],
            primary_project_id=row[6],
            deleted_at=row[7],
            completed=row[8],
            comment=row[9],
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


def soft_delete_plan(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Mark a Plan soft-deleted, hiding it from the default catalog.

    Stamps ``deleted_at`` with the current time only for a live plan; a
    plan that is already soft-deleted is left untouched, so the operation
    is idempotent and never overwrites the original deletion time. The plan
    row and all of its children are preserved; the plan stays resolvable by
    uuid or name and every other command keeps working on it unchanged.

    Args:
        conn: Open psycopg 3 database connection to use for the update.
        plan_uuid: Primary identity of the plan to soft-delete.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE plan SET deleted_at = now() "
        "WHERE uuid = %s AND deleted_at IS NULL",
        (plan_uuid,),
    )


def hard_delete_plan(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Permanently delete a Plan and every artifact belonging to it.

    Deletes the plan row; all child rows (revisions, paragraphs, concepts,
    relations, steps, node versions, refs, cascades, step runtime, context
    blocks) are removed by the ON DELETE CASCADE foreign keys that reference
    ``plan(uuid)``. This is irreversible and applies regardless of whether
    the plan was previously soft-deleted.

    Args:
        conn: Open psycopg 3 database connection to use for the delete.
        plan_uuid: Primary identity of the plan to delete permanently.

    Returns:
        None.
    """
    conn.execute("DELETE FROM plan WHERE uuid = %s", (plan_uuid,))


def set_plan_completed(conn: psycopg.Connection, plan_uuid: uuid.UUID, completed: bool) -> None:
    """Set or unset a Plan's completion lock (bug c3950b83).

    Always allowed regardless of the plan's freeze state or current
    completed value (idempotent no-op when unchanged). Callers are
    responsible for recording the runtime audit entry; this function only
    updates the stored column.

    Args:
        conn: Open psycopg 3 database connection to use for the update.
        plan_uuid: Primary identity of the plan to update.
        completed: The new completion-lock value.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE plan SET completed = %s WHERE uuid = %s",
        (completed, plan_uuid),
    )


def set_plan_comment(conn: psycopg.Connection, plan_uuid: uuid.UUID, comment: str | None) -> None:
    """Set, replace, or clear a Plan's free-form comment.

    Always allowed regardless of the plan's freeze state or completion
    lock. Callers are responsible for recording the runtime audit entry;
    this function only updates the stored column.

    Args:
        conn: Open psycopg 3 database connection to use for the update.
        plan_uuid: Primary identity of the plan to update.
        comment: The new comment text, or None to clear it.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE plan SET comment = %s WHERE uuid = %s",
        (comment, plan_uuid),
    )
