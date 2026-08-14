"""Shared supersede-lifecycle storage for review_result and execution_attempt
(bug 74479c06 group-4 fix): the two entities had no way to record that a
stale record was REPLACED by a specific later one without either leaving the
stale record looking current forever, or overwriting its own `status` --
which would falsify the outcome it actually recorded.

FIX SHAPE (ORCHESTRATOR-APPROVED design): a forward pointer written ONLY on
the STALE row (migration 0031's superseded_by_uuid column on both tables).
The original row's `status` is NEVER written by either function below --
enforced by construction: neither function's UPDATE payload ever contains
"status", only {"superseded_by_uuid", "updated_at"}.

Both entry points share the same shape, mirroring
plan_manager.storage.entity_reanchor_store's precedent for a small,
audited, cross-entity mutation living in ONE shared module rather than
duplicated per entity:

  * fetch the stale row; refuse NOT_FOUND (missing or soft-deleted)
  * refuse self-supersede (stale uuid == replacement uuid)
  * fetch the replacement row; refuse NOT_FOUND if missing
  * apply the lineage guard (see each function's docstring for what is
    cleanly derivable for that entity)
  * idempotency: if the stale row already carries a superseded_by_uuid,
    the SAME target is a no-op success (nothing written, the caller is told
    via the returned `already_superseded` flag); a DIFFERENT target is
    refused outright -- a partially applied re-supersede would be worse
    than a refused one
  * write the pointer via the entity's own crud_update (never through the
    entity's ordinary report/create store functions, which do not carry
    superseded_by_uuid in their own whitelists) and append exactly one
    runtime_audit_log row shaped {"old_superseded_by_uuid": ..., "new_superseded_by_uuid": ...}

DomainCommandError is imported inside each function, not at module level,
to avoid a storage->commands->storage import cycle (the same technique
entity_reanchor_store.reanchor_owner_form_entity already uses).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg

from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.review_result import ReviewResult
from plan_manager.storage.execution_attempt_store import get_execution_attempt
from plan_manager.storage.review_result_store import get_review_result
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _record_supersede_audit(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    changed_by: str,
    new_pointer: uuid.UUID,
) -> None:
    """Append the one shared audit-record shape both supersede functions use --
    the sole place this shape is built (mirrors
    entity_reanchor_store._record_reanchor_audit's role for re-anchoring)."""
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type=entity_type,
        entity_id=entity_id,
        action="update",
        changed_by=changed_by,
        changed_fields={"old_superseded_by_uuid": None, "new_superseded_by_uuid": str(new_pointer)},
    )


def supersede_execution_attempt(
    conn: psycopg.Connection,
    stale_attempt_uuid: uuid.UUID,
    *,
    superseded_by_uuid: uuid.UUID,
    changed_by: str,
) -> tuple[ExecutionAttempt, bool]:
    """Record that stale_attempt_uuid was replaced by superseded_by_uuid, without
    touching the stale row's `status` (its recorded run outcome stays intact).

    Lineage guard: replacement.step_uuid must equal stale.step_uuid.
    execution_attempt.step_uuid is NOT NULL (migration 0012), so this is
    cleanly derivable for every row and is enforced unconditionally.

    Parameters:
        conn: Open connection; the caller owns the transaction.
        stale_attempt_uuid: The execution attempt being superseded.
        superseded_by_uuid: The replacement execution attempt.
        changed_by: Actor recorded on the appended audit record.

    Returns:
        (record, already_superseded): record is the execution attempt after
        the write (or the unchanged stale record when already_superseded is
        True); already_superseded is True exactly when stale_attempt_uuid
        already carried this SAME superseded_by_uuid and nothing was written.

    Raises:
        DomainCommandError: EXECUTION_ATTEMPT_SELF_SUPERSEDE when
            stale_attempt_uuid == superseded_by_uuid; EXECUTION_ATTEMPT_NOT_FOUND
            when either uuid does not resolve to a live (not soft-deleted, for
            the stale side) row; EXECUTION_ATTEMPT_LINEAGE_MISMATCH when the
            replacement belongs to a different step;
            EXECUTION_ATTEMPT_ALREADY_SUPERSEDED when stale_attempt_uuid already
            points at a DIFFERENT replacement.
    """
    from plan_manager.commands.errors import DomainCommandError

    if stale_attempt_uuid == superseded_by_uuid:
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_SELF_SUPERSEDE",
            f"execution attempt {stale_attempt_uuid} may not supersede itself",
        )

    stale = get_execution_attempt(conn, stale_attempt_uuid)
    if stale is None or stale.deleted_at is not None:
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_NOT_FOUND", f"execution attempt not found: {stale_attempt_uuid}"
        )

    replacement = get_execution_attempt(conn, superseded_by_uuid)
    if replacement is None:
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_NOT_FOUND", f"replacement execution attempt not found: {superseded_by_uuid}"
        )

    if replacement.step_uuid != stale.step_uuid:
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_LINEAGE_MISMATCH",
            f"replacement execution attempt {superseded_by_uuid} belongs to step {replacement.step_uuid}, "
            f"not the stale attempt's step {stale.step_uuid}",
        )

    if stale.superseded_by_uuid is not None:
        if stale.superseded_by_uuid == superseded_by_uuid:
            return stale, True
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_ALREADY_SUPERSEDED",
            f"execution attempt {stale_attempt_uuid} is already superseded by "
            f"{stale.superseded_by_uuid}, not {superseded_by_uuid}; a partially applied "
            "re-supersede is refused outright",
        )

    now = datetime.now(timezone.utc)
    ExecutionAttempt.crud_update(
        conn, stale_attempt_uuid, {"superseded_by_uuid": superseded_by_uuid, "updated_at": now}, returning=False
    )
    updated = get_execution_attempt(conn, stale_attempt_uuid)
    if updated is None:
        raise DomainCommandError(
            "EXECUTION_ATTEMPT_NOT_FOUND", f"execution attempt not found: {stale_attempt_uuid}"
        )

    _record_supersede_audit(
        conn,
        plan_uuid=stale.plan_uuid,
        entity_type="execution_attempt",
        entity_id=stale_attempt_uuid,
        changed_by=changed_by,
        new_pointer=superseded_by_uuid,
    )
    return updated, False


def supersede_review_result(
    conn: psycopg.Connection,
    stale_review_uuid: uuid.UUID,
    *,
    superseded_by_uuid: uuid.UUID,
    changed_by: str,
) -> tuple[ReviewResult, bool]:
    """Record that stale_review_uuid was replaced by superseded_by_uuid, without
    touching the stale row's `status` (the verdict it recorded stays intact).

    Lineage guard: replacement.object_type must equal stale.object_type.
    When both are "execution_attempt" reviews, this additionally requires the
    two reviewed execution attempts to share a step_uuid (execution_attempt.
    step_uuid is NOT NULL, so that join is cleanly derivable with one extra
    get_execution_attempt lookup per side). DEVIATION/REPORTED OMISSION: when
    object_type is "revision", no equivalent step-sharing check is applied --
    plan_manager.domain.revision carries no step_uuid column this store could
    join through cleanly (a revision is a whole-plan snapshot, not
    step-scoped), so only existence + object_type match + not-self is
    enforced for that branch, exactly as the approved design allows.

    Parameters:
        conn: Open connection; the caller owns the transaction.
        stale_review_uuid: The review result being superseded.
        superseded_by_uuid: The replacement review result.
        changed_by: Actor recorded on the appended audit record.

    Returns:
        (record, already_superseded): record is the review result after the
        write (or the unchanged stale record when already_superseded is
        True); already_superseded is True exactly when stale_review_uuid
        already carried this SAME superseded_by_uuid and nothing was written.

    Raises:
        DomainCommandError: REVIEW_RESULT_SELF_SUPERSEDE when
            stale_review_uuid == superseded_by_uuid; REVIEW_RESULT_NOT_FOUND
            when either uuid does not resolve to a live (not soft-deleted, for
            the stale side) row; REVIEW_RESULT_LINEAGE_MISMATCH when
            object_type differs, or both are execution_attempt reviews whose
            reviewed attempts belong to different steps;
            REVIEW_RESULT_ALREADY_SUPERSEDED when stale_review_uuid already
            points at a DIFFERENT replacement.
    """
    from plan_manager.commands.errors import DomainCommandError

    if stale_review_uuid == superseded_by_uuid:
        raise DomainCommandError(
            "REVIEW_RESULT_SELF_SUPERSEDE",
            f"review result {stale_review_uuid} may not supersede itself",
        )

    stale = get_review_result(conn, stale_review_uuid)
    if stale is None or stale.deleted_at is not None:
        raise DomainCommandError("REVIEW_RESULT_NOT_FOUND", f"review result not found: {stale_review_uuid}")

    replacement = get_review_result(conn, superseded_by_uuid)
    if replacement is None:
        raise DomainCommandError(
            "REVIEW_RESULT_NOT_FOUND", f"replacement review result not found: {superseded_by_uuid}"
        )

    if replacement.object_type != stale.object_type:
        raise DomainCommandError(
            "REVIEW_RESULT_LINEAGE_MISMATCH",
            f"replacement review result {superseded_by_uuid} reviews a {replacement.object_type!r}, "
            f"not the stale review's {stale.object_type!r}",
        )

    if (
        stale.object_type == "execution_attempt"
        and stale.reviewed_attempt_uuid is not None
        and replacement.reviewed_attempt_uuid is not None
    ):
        stale_attempt = get_execution_attempt(conn, stale.reviewed_attempt_uuid)
        replacement_attempt = get_execution_attempt(conn, replacement.reviewed_attempt_uuid)
        if (
            stale_attempt is not None
            and replacement_attempt is not None
            and stale_attempt.step_uuid != replacement_attempt.step_uuid
        ):
            raise DomainCommandError(
                "REVIEW_RESULT_LINEAGE_MISMATCH",
                f"replacement review {superseded_by_uuid} reviews execution attempt "
                f"{replacement.reviewed_attempt_uuid} (step {replacement_attempt.step_uuid}), which does "
                f"not share a step with the stale review's attempt {stale.reviewed_attempt_uuid} "
                f"(step {stale_attempt.step_uuid})",
            )

    if stale.superseded_by_uuid is not None:
        if stale.superseded_by_uuid == superseded_by_uuid:
            return stale, True
        raise DomainCommandError(
            "REVIEW_RESULT_ALREADY_SUPERSEDED",
            f"review result {stale_review_uuid} is already superseded by "
            f"{stale.superseded_by_uuid}, not {superseded_by_uuid}; a partially applied "
            "re-supersede is refused outright",
        )

    now = datetime.now(timezone.utc)
    ReviewResult.crud_update(
        conn, stale_review_uuid, {"superseded_by_uuid": superseded_by_uuid, "updated_at": now}, returning=False
    )
    updated = get_review_result(conn, stale_review_uuid)
    if updated is None:
        raise DomainCommandError("REVIEW_RESULT_NOT_FOUND", f"review result not found: {stale_review_uuid}")

    _record_supersede_audit(
        conn,
        plan_uuid=None,
        entity_type="review_result",
        entity_id=stale_review_uuid,
        changed_by=changed_by,
        new_pointer=superseded_by_uuid,
    )
    return updated, False
