"""Storage-layer operations for the Step entity (C-005): scaffolded
creation, id assignment, and CRUD against the `step` table.
"""


import uuid

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.step import Step, next_free_step_id, validate_step
from plan_manager.storage.plan_lock import acquire_plan_lock, release_plan_lock


def list_step_ids(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    parent_step_uuid: uuid.UUID | None,
    level: int,
) -> list[str]:
    """List step_id values in one parent scope of the step table.

    Args:
        conn: Open database connection.
        plan_uuid: Plan identity to scope the query to.
        parent_step_uuid: Parent step identity to scope the query to, or
            None to select level-3 steps (whose scope is the plan
            itself). Compared with IS NOT DISTINCT FROM so NULL matches
            NULL.
        level: Plan hierarchy level to scope the query to; one of 3, 4,
            5.

    Returns:
        The step_id values of every row in the step table matching
        plan_uuid, parent_step_uuid (NULL-safe), and level. Order is
        not guaranteed.
    """
    cur = conn.execute(
        "SELECT step_id FROM step "
        "WHERE plan_uuid = %s "
        "AND parent_step_uuid IS NOT DISTINCT FROM %s "
        "AND level = %s",
        (plan_uuid, parent_step_uuid, level),
    )
    return [row[0] for row in cur.fetchall()]


def create_step(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    parent_step_uuid: uuid.UUID | None,
    level: int,
    slug: str,
    fields: dict,
    depends_on: list[str],
    concepts: list[str],
    project_id: str | None = None,
) -> Step:
    """Scaffolded creation of a Step: assign the next free id and insert it.

    Runs the full compute-and-insert sequence between acquire_plan_lock
    and release_plan_lock (release in a finally block) so concurrent
    creates in the same parent scope cannot obtain the same step_id.
    The new row's status is always "draft".

    Steps performed:
        1. acquire_plan_lock(conn, plan_uuid).
        2. list_step_ids(conn, plan_uuid, parent_step_uuid, level) to
           collect the existing step_id values in this parent scope.
        3. next_free_step_id(existing_step_ids, level) to compute the
           new step_id.
        4. Build a Step with a freshly generated uuid.uuid4(), the
           given plan_uuid, parent_step_uuid, level, the computed
           step_id, slug, fields, depends_on, concepts, and status
           "draft".
        5. validate_step(step) on the built Step.
        6. INSERT the row into the step table.
        7. release_plan_lock(conn, plan_uuid) in a finally block,
           whether or not the prior steps succeeded.

    Args:
        conn: Open database connection.
        plan_uuid: Identity of the plan the new step belongs to.
        parent_step_uuid: Identity of the parent step that defines the
            id-uniqueness scope, or None for a level-3 step.
        level: Plan hierarchy level of the new step; one of 3, 4, 5.
        slug: Kebab-case short name for the new step.
        fields: Level-specific required fields, as a plain dict, to
            store as JSON.
        depends_on: step_id values of sibling steps the new step
            depends on.
        concepts: MRS concept_id values referenced by the new step.

    Returns:
        The created Step, with its assigned uuid and step_id
        populated.

    Raises:
        StepValidationError: When the built Step fails validate_step.
    """
    acquire_plan_lock(conn, plan_uuid)
    try:
        existing_step_ids = list_step_ids(conn, plan_uuid, parent_step_uuid, level)
        step_id = next_free_step_id(existing_step_ids, level)
        step = Step(
            uuid=uuid.uuid4(),
            plan_uuid=plan_uuid,
            parent_step_uuid=parent_step_uuid,
            level=level,
            step_id=step_id,
            slug=slug,
            fields=fields,
            depends_on=depends_on,
            concepts=concepts,
            project_id=project_id,
            status="draft",
        )
        validate_step(step)
        conn.execute(
            "INSERT INTO step "
            "(uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
            "fields, depends_on, concepts, project_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                step.uuid,
                step.plan_uuid,
                step.parent_step_uuid,
                step.level,
                step.step_id,
                step.slug,
                Jsonb(step.fields),
                step.depends_on,
                step.concepts,
                step.project_id,
                step.status,
            ),
        )
        return step
    finally:
        release_plan_lock(conn, plan_uuid)


def get_step(conn: psycopg.Connection, step_uuid: uuid.UUID) -> Step:
    """Fetch one Step by its immutable uuid.

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to fetch.

    Returns:
        The Step stored under step_uuid.

    Raises:
        ValueError: When no row in the step table has uuid = step_uuid.
    """
    cur = conn.execute(
        "SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
        "fields, depends_on, concepts, project_id, status "
        "FROM step WHERE uuid = %s",
        (step_uuid,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no step with uuid {step_uuid!r}")
    return Step(
        uuid=row[0],
        plan_uuid=row[1],
        parent_step_uuid=row[2],
        level=row[3],
        step_id=row[4],
        slug=row[5],
        fields=row[6],
        depends_on=row[7],
        concepts=row[8],
        project_id=row[9],
        status=row[10],
    )


def update_step_fields(conn: psycopg.Connection, step_uuid: uuid.UUID, fields: dict) -> None:
    """Overwrite the level-specific fields dict of one step (draft-regime
    direct mutation).

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to update.
        fields: The new level-specific fields dict to store as JSON,
            replacing the row's current fields value in full.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE step SET fields = %s WHERE uuid = %s",
        (Jsonb(fields), step_uuid),
    )


def update_step_fields_and_concepts(
    conn: psycopg.Connection,
    step_uuid: uuid.UUID,
    fields: dict,
    concepts: list[str],
) -> None:
    """Overwrite one step's fields dict and top-level concept bindings.

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to update.
        fields: The new level-specific fields dict to store as JSON.
        concepts: The new top-level concept_id bindings to store.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE step SET fields = %s, concepts = %s WHERE uuid = %s",
        (Jsonb(fields), concepts, step_uuid),
    )


def update_step_fields_concepts_project(
    conn: psycopg.Connection,
    step_uuid: uuid.UUID,
    fields: dict,
    concepts: list[str],
    project_id: str | None,
) -> None:
    """Overwrite one step's fields, concept bindings, and project binding."""
    conn.execute(
        "UPDATE step SET fields = %s, concepts = %s, project_id = %s WHERE uuid = %s",
        (Jsonb(fields), concepts, project_id, step_uuid),
    )


def update_step_depends_on(
    conn: psycopg.Connection,
    step_uuid: uuid.UUID,
    depends_on: list[str],
) -> None:
    """Overwrite one step's top-level depends_on sibling references.

    depends_on is the real top-level graph column, not part of the JSON
    fields dict; this writes it directly so the dependency graph (C-009),
    plan_validate, and graph_order/graph_parallel_map see the new edges.

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to update.
        depends_on: The complete new list of sibling step_id references
            (same parent, same level), replacing the row's current value.

    Returns:
        None.
    """
    conn.execute(
        "UPDATE step SET depends_on = %s WHERE uuid = %s",
        (depends_on, step_uuid),
    )
