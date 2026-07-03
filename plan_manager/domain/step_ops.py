"""Structural mutation operations for the Step entity (C-005): move,
delete, and status-transition operations that touch more than the row
being mutated.
"""


import uuid

import psycopg

from plan_manager.domain.step import Step, next_free_step_id
from plan_manager.domain.step_store import get_step, list_step_ids
from plan_manager.domain.status_model import validate_transition


def move_step(
    conn: psycopg.Connection,
    step_uuid: uuid.UUID,
    new_parent_uuid: uuid.UUID | None,
) -> Step:
    """Re-parent one step, re-assigning its id in the new scope and
    rewriting every reference to the moved id in one operation (C-005).

    Implements the normative move algorithm:
        a. Fetch the step and its old parent (step.parent_step_uuid).
           When new_parent_uuid equals the step's current
           parent_step_uuid, this is a no-op: return the step unchanged.
        b. Level guard: the new parent must sit exactly one level above
           the moved step (new parent's level == step.level - 1), except
           that new_parent_uuid is allowed to be None only when the
           moved step is level 3 (its scope is the plan itself, which
           has no Step row). Any other case raises ValueError.
        c. Old-scope reference scrub: for every other step in the OLD
           scope (same plan_uuid, same old parent_step_uuid, same
           level, excluding the moved step itself), remove the moved
           step's old step_id from that step's depends_on list, if
           present.
        d. Compute the next free step_id in the NEW scope (same
           plan_uuid, new_parent_uuid, same level) via list_step_ids
           and next_free_step_id, the same way create_step computes a
           new id.
        e. The moved step's own depends_on entries reference OLD-scope
           siblings and become invalid under the new id and new scope;
           they are cleared to an empty list.
        f. Update the moved row in one UPDATE statement setting
           parent_step_uuid, step_id, and depends_on together.
        g. Re-read and return the moved step from the database.

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to move.
        new_parent_uuid: Identity of the new parent step, or None when
            the moved step is level 3 (whose scope is the plan itself).

    Returns:
        The moved Step, re-read from the database after the update.

    Raises:
        ValueError: When new_parent_uuid does not sit exactly one level
            above the moved step (or is None for a step whose level is
            not 3).
    """
    step = get_step(conn, step_uuid)
    old_parent_uuid = step.parent_step_uuid

    if new_parent_uuid == old_parent_uuid:
        return step

    if new_parent_uuid is None:
        if step.level != 3:
            raise ValueError("invalid parent level")
    else:
        new_parent = get_step(conn, new_parent_uuid)
        if new_parent.level != step.level - 1:
            raise ValueError("invalid parent level")

    cur = conn.execute(
        "SELECT uuid, depends_on FROM step "
        "WHERE plan_uuid = %s "
        "AND parent_step_uuid IS NOT DISTINCT FROM %s "
        "AND level = %s "
        "AND uuid != %s",
        (step.plan_uuid, old_parent_uuid, step.level, step.uuid),
    )
    for sibling_uuid, sibling_depends_on in cur.fetchall():
        if step.step_id in sibling_depends_on:
            new_depends_on = [d for d in sibling_depends_on if d != step.step_id]
            conn.execute(
                "UPDATE step SET depends_on = %s WHERE uuid = %s",
                (new_depends_on, sibling_uuid),
            )

    existing_step_ids = list_step_ids(conn, step.plan_uuid, new_parent_uuid, step.level)
    new_step_id = next_free_step_id(existing_step_ids, step.level)

    conn.execute(
        "UPDATE step SET parent_step_uuid = %s, step_id = %s, depends_on = %s "
        "WHERE uuid = %s",
        (new_parent_uuid, new_step_id, [], step.uuid),
    )

    return get_step(conn, step_uuid)


def delete_step(conn: psycopg.Connection, step_uuid: uuid.UUID) -> None:
    """Delete one step, refusing when it has children and scrubbing the
    deleted id from same-scope siblings' depends_on lists (C-005).

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to delete.

    Returns:
        None.

    Raises:
        ValueError: When the step has one or more children (rows whose
            parent_step_uuid equals step_uuid).
    """
    step = get_step(conn, step_uuid)

    cur = conn.execute(
        "SELECT count(*) FROM step WHERE parent_step_uuid = %s",
        (step_uuid,),
    )
    child_count = cur.fetchone()[0]
    if child_count > 0:
        raise ValueError("step has children")

    cur = conn.execute(
        "SELECT uuid, depends_on FROM step "
        "WHERE plan_uuid = %s "
        "AND parent_step_uuid IS NOT DISTINCT FROM %s "
        "AND level = %s "
        "AND uuid != %s",
        (step.plan_uuid, step.parent_step_uuid, step.level, step.uuid),
    )
    for sibling_uuid, sibling_depends_on in cur.fetchall():
        if step.step_id in sibling_depends_on:
            new_depends_on = [d for d in sibling_depends_on if d != step.step_id]
            conn.execute(
                "UPDATE step SET depends_on = %s WHERE uuid = %s",
                (new_depends_on, sibling_uuid),
            )

    conn.execute("DELETE FROM step WHERE uuid = %s", (step_uuid,))


def set_step_status(
    conn: psycopg.Connection,
    step_uuid: uuid.UUID,
    new_status: str,
    via_cascade: bool = False,
) -> None:
    """Validate and apply a status transition for one step (C-005, C-007).

    Args:
        conn: Open database connection.
        step_uuid: Immutable primary identity of the step to transition.
        new_status: The requested new status string.
        via_cascade: True if this transition is applied as part of
            cascade propagation, False for a direct request. Defaults
            to False.

    Returns:
        None.

    Raises:
        StatusTransitionError: When validate_transition rejects the
            requested transition.
    """
    step = get_step(conn, step_uuid)
    validate_transition(
        step.status, new_status, is_atomic_step=(step.level == 5), via_cascade=via_cascade
    )
    conn.execute(
        "UPDATE step SET status = %s WHERE uuid = %s",
        (new_status, step_uuid),
    )
