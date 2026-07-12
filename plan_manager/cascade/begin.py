"""Cascade opening operation: begins a new cascade anchored at the plan head revision."""

import uuid
from datetime import datetime, timezone

import psycopg

from plan_manager.cascade.record import CascadeError, CascadeRecord, get_open_cascade, insert_cascade
from plan_manager.domain.plan import get_plan
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
from plan_manager.storage.plan_lock import acquire_plan_lock, release_plan_lock
from plan_manager.storage.version_store import create_ref


def _all_steps_frozen(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> bool:
    """Return True when the plan has at least one step and every step is frozen.

    Plan-level status is never set to 'frozen' by any command surface; a fully
    frozen plan manifests as a non-empty step set whose every row has
    step.status = 'frozen'. An empty step set is authoring-stage and not frozen.
    """
    has_steps = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM step WHERE plan_uuid = %s)",
        (plan_uuid,),
    ).fetchone()[0]
    if not has_steps:
        return False
    has_non_frozen = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM step WHERE plan_uuid = %s AND status != 'frozen')",
        (plan_uuid,),
    ).fetchone()[0]
    return not has_non_frozen


def begin_cascade(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    allow_all_frozen: bool = False,
) -> CascadeRecord:
    """Open a new cascade on a plan, anchored at its current head revision.

    Acquires the per-plan advisory lock for the duration of the operation.
    Raises CascadeError("plan already has an open cascade") if the plan
    already has an open cascade record. Raises CascadeError("cannot open
    a cascade on a plan with no head revision") if the plan has no
    recorded head revision to anchor at. Otherwise: generates a new
    cascade uuid, builds the cascade reference name
    "cascade/<cascade uuid>", creates that reference in the version store
    pointing at the plan's head revision, builds and inserts the new
    cascade record in the open state anchored at that head revision, and
    returns the inserted record. The per-plan lock is always released
    before returning or raising, whether the operation succeeded or
    raised any of the above conditions.

    ``allow_all_frozen`` is an internal escape hatch reserved for the
    audited plan_unfreeze command: when True, the all-steps-frozen refusal
    is bypassed so the ONLY documented door out of full freeze can open a
    cascade. It does NOT relax the ``plan.status == 'frozen'`` guard, and
    it defaults to False so every public caller (cascade_begin) keeps the
    full frozen-truth protection. This is the only sanctioned bypass; the
    public FROZEN_TRUTH_WRITE guard of cascade_begin is unchanged.
    """
    acquire_plan_lock(conn, plan_uuid)
    try:
        if get_open_cascade(conn, plan_uuid) is not None:
            raise CascadeError("plan already has an open cascade")
        plan = get_plan(conn, plan_uuid)
        if plan.status == "frozen":
            raise FrozenTruthMutationError(
                f"cannot open a cascade on frozen plan {plan_uuid}: frozen plan truth is read-only"
            )
        if not allow_all_frozen and _all_steps_frozen(conn, plan_uuid):
            raise FrozenTruthMutationError(
                f"cannot open a cascade on plan {plan_uuid}: every step is frozen; frozen plan truth is read-only"
            )
        if plan.head_revision_uuid is None:
            raise CascadeError("cannot open a cascade on a plan with no head revision")
        cascade_uuid = uuid.uuid4()
        name = f"cascade/{cascade_uuid}"
        create_ref(conn, plan_uuid, name, plan.head_revision_uuid)
        record = CascadeRecord(
            uuid=cascade_uuid,
            plan_uuid=plan_uuid,
            name=name,
            base_revision_uuid=plan.head_revision_uuid,
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        insert_cascade(conn, record)
        return record
    finally:
        release_plan_lock(conn, plan_uuid)
