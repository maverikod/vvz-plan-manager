"""Cascade-scoped write path for CascadeChange (C-016).

Records, for an admitted in-cascade mutation already applied to the
stored entity rows (C-035), one revision in the version store (C-018)
attributed to the cascade under the cascade reference, applying
accompanying step status updates validated by the status model (C-007).
"""

import uuid

import psycopg

from plan_manager.cascade.record import CascadeError, CascadeRecord
from plan_manager.domain.status_model import validate_transition
from plan_manager.domain.step_store import Step, get_step
from plan_manager.storage.version_store import get_ref, record_revision


def step_snapshot(step: Step, status: str) -> dict:
    """Build the full post-change content snapshot of a step node for
    the version store (C-018).

    The snapshot reflects `status`, not `step.status` — the caller
    passes the new status the step is being written under.

    Args:
        step: the step whose fields are snapshotted.
        status: the status value to record in the snapshot.

    Returns:
        A dict with exactly these keys, in this order: "kind", "uuid",
        "plan_uuid", "parent_step_uuid", "level", "step_id", "slug",
        "fields", "depends_on", "concepts", "status". "kind" is always
        the literal string "step". "uuid" and "plan_uuid" are `str(...)`
        of the corresponding Step uuid fields. "parent_step_uuid" is
        `str(step.parent_step_uuid)` when it is not None, else None.
        "level", "step_id", "slug", "fields", "depends_on", and
        "concepts" are copied verbatim from `step`. "status" is the
        `status` argument, not `step.status`.
    """
    return {
        "kind": "step",
        "uuid": str(step.uuid),
        "plan_uuid": str(step.plan_uuid),
        "parent_step_uuid": str(step.parent_step_uuid) if step.parent_step_uuid is not None else None,
        "level": step.level,
        "step_id": step.step_id,
        "slug": step.slug,
        "fields": step.fields,
        "depends_on": step.depends_on,
        "concepts": step.concepts,
        "status": status,
    }


def apply_status_updates(
    conn: psycopg.Connection, updates: list[tuple[uuid.UUID, str]]
) -> list[tuple[uuid.UUID, dict]]:
    """Apply cascade-driven status updates to the stored step rows (C-035).

    For each `(step_uuid, new_status)` pair in `updates`, in list order:
    load the step via `get_step`; if its current status already equals
    `new_status`, skip it (no SQL statement is executed and no snapshot
    is appended for it); otherwise validate the transition by calling
    `validate_transition(step.status, new_status, is_atomic_step=(step.level == 5), via_cascade=True)`,
    execute the SQL statement `UPDATE step SET status = %s WHERE uuid = %s`
    with parameters `(new_status, step_uuid)`, and append
    `(step_uuid, step_snapshot(step, new_status))` to the result list.

    Args:
        conn: open database connection.
        updates: list of (step_uuid, new_status) pairs to apply, in the
            order they must be applied.

    Returns:
        The list of (step_uuid, snapshot) pairs for every step actually
        updated (i.e. excluding skipped no-op updates), in the order the
        updates were processed.

    Raises:
        StatusTransitionError: propagated from `validate_transition`
            when a transition is illegal.
    """
    snapshots: list[tuple[uuid.UUID, dict]] = []
    for step_uuid, new_status in updates:
        step = get_step(conn, step_uuid)
        if step.status == new_status:
            continue
        validate_transition(step.status, new_status, is_atomic_step=(step.level == 5), via_cascade=True)
        conn.execute("UPDATE step SET status = %s WHERE uuid = %s", (new_status, step_uuid))
        snapshots.append((step_uuid, step_snapshot(step, new_status)))
    return snapshots


def cascade_write(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    cascade: CascadeRecord,
    node_uuid: uuid.UUID,
    node_snapshot: dict,
    status_updates: list[tuple[uuid.UUID, str]],
    author: str,
    message: str,
) -> uuid.UUID:
    """Record one revision in the version store (C-018) for an admitted
    in-cascade mutation, attributed to the cascade under its own
    reference, without moving the plan head.

    `node_snapshot` is the full post-change content snapshot of the
    mutated node, produced verbatim by the owning domain operation (it
    already carries its own "kind" key); this function records it as-is,
    without modification. The revision's change set is
    `[(node_uuid, node_snapshot)]` followed by the (step_uuid, snapshot)
    pairs returned by applying `status_updates` via
    `apply_status_updates`. The revision is recorded against the
    cascade's own ref (`cascade.name`), whose current target is used as
    the new revision's parent; the plan's head reference is never
    touched by this function.

    Args:
        conn: open database connection.
        plan_uuid: identity of the plan the cascade belongs to.
        cascade: the plan's open CascadeRecord.
        node_uuid: uuid of the mutated node.
        node_snapshot: full post-change content snapshot of the mutated
            node, produced by the owning domain operation.
        status_updates: (step_uuid, new_status) pairs to apply alongside
            the node mutation, in the order they must be applied.
        author: revision author.
        message: revision message.

    Returns:
        The uuid of the newly recorded revision.

    Raises:
        CascadeError: if `cascade.status != "open"`.
    """
    if cascade.status != "open":
        raise CascadeError(f"cascade {cascade.uuid} is not open")
    parent = get_ref(conn, plan_uuid, cascade.name)
    snaps = apply_status_updates(conn, status_updates)
    changes = [(node_uuid, node_snapshot)] + snaps
    return record_revision(conn, plan_uuid, author, message, changes, parent, ref_name=cascade.name)
