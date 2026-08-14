"""Regression suite for bug 74479c06 (group-4 fix): neither review_result nor
execution_attempt had a supersede lifecycle for stale review results/
execution attempts. The approved fix writes a forward superseded_by_uuid
pointer ON THE STALE ROW ONLY (migration 0031); the original `status` is
NEVER touched -- every write-path test below asserts that explicitly.

plan_manager.storage.entity_supersede_store is exercised with monkeypatched
collaborators (get_execution_attempt/get_review_result/crud_update/
record_runtime_change) -- the same fake-store technique
tests/test_store_descriptor_migration_overlay.py::test_tool_store_delegates_to_crud
already uses -- so no live PostgreSQL instance is required. Command-layer
(execution_attempt_supersede / review_result_supersede) parameter validation
is covered separately, directly against the schema/metadata, avoiding a
second full db_connection fake.

Row-loader unpack-safety (bug 0798c162) for the appended superseded_by_uuid
column is covered directly against each store's own _row_to_record.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.review_result import ReviewResult
from plan_manager.storage import entity_supersede_store

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _attempt(**overrides) -> ExecutionAttempt:
    base = dict(
        attempt_uuid=uuid.uuid4(), plan_uuid=uuid.uuid4(), revision_uuid=None,
        step_uuid=uuid.uuid4(), step_path=None, todo_uuid=None, bug_fix_uuid=None,
        assigned_binding_uuid=None, assigned_provider=None, assigned_model=None,
        used_provider=None, used_model=None, runtime=None, vast_instance_id=None,
        started_at=None, finished_at=None, status="succeeded", input_context_hash=None,
        result_summary="original outcome", changed_files=None, command_test_results=None,
        resource_accounting=None, acct_tokens_in=None, acct_tokens_out=None,
        acct_provider=None, acct_model=None, acct_wall_ms=None, acct_cost_estimate=None,
        transcript_ref=None, error=None, escalation_reason=None, parent_attempt_uuid=None,
        created_by="tester", created_at=NOW.isoformat(), updated_at=NOW.isoformat(), deleted_at=None,
        superseded_by_uuid=None,
    )
    base.update(overrides)
    return ExecutionAttempt(**base)


def _review(**overrides) -> ReviewResult:
    base = dict(
        review_uuid=uuid.uuid4(), object_type="execution_attempt",
        reviewed_attempt_uuid=uuid.uuid4(), reviewed_revision_uuid=None,
        reviewer="reviewer", status="accepted", findings="original verdict",
        evidence=None, verification_commands=None, escalation_target_uuid=None,
        created_by="tester", created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        deleted_at=None, superseded_by_uuid=None,
    )
    base.update(overrides)
    return ReviewResult(**base)


class _AttemptFakeStore:
    """In-memory execution_attempt table double: get_* reads, crud_update writes."""

    def __init__(self, *rows: ExecutionAttempt) -> None:
        self.rows: dict[uuid.UUID, ExecutionAttempt] = {r.attempt_uuid: r for r in rows}
        self.audit_calls: list[dict] = []

    def get(self, conn, attempt_uuid):
        return self.rows.get(attempt_uuid)

    def _apply_update(self, entity_id, values) -> None:
        rec = self.rows[entity_id]
        patched = dict(values)
        if "updated_at" in patched:
            patched["updated_at"] = patched["updated_at"].isoformat()
        self.rows[entity_id] = dataclasses.replace(rec, **patched)

    def audit(self, conn, **kwargs):
        self.audit_calls.append(kwargs)


class _ReviewFakeStore:
    """In-memory review_result table double: get_* reads, crud_update writes."""

    def __init__(self, *rows: ReviewResult) -> None:
        self.rows: dict[uuid.UUID, ReviewResult] = {r.review_uuid: r for r in rows}

    def get(self, conn, review_uuid):
        return self.rows.get(review_uuid)

    def _apply_update(self, entity_id, values) -> None:
        rec = self.rows[entity_id]
        patched = dict(values)
        if "updated_at" in patched:
            patched["updated_at"] = patched["updated_at"].isoformat()
        self.rows[entity_id] = dataclasses.replace(rec, **patched)


@pytest.fixture
def wired(monkeypatch):
    """Wire entity_supersede_store's collaborators to fresh, empty fake stores;
    tests populate .rows themselves and read state back off the same fakes.

    ExecutionAttempt.crud_update / ReviewResult.crud_update are real
    classmethods (``cls`` is the first positional argument at call time), so
    the fakes patched in here must accept ``cls`` too -- a plain bound method
    would silently misalign the argument count.
    """
    attempts = _AttemptFakeStore()
    reviews = _ReviewFakeStore()
    monkeypatch.setattr(entity_supersede_store, "get_execution_attempt", attempts.get)
    monkeypatch.setattr(entity_supersede_store, "get_review_result", reviews.get)

    def _attempt_crud_update(cls, conn, entity_id, values, *, returning=True):
        attempts._apply_update(entity_id, values)
        return None

    def _review_crud_update(cls, conn, entity_id, values, *, returning=True):
        reviews._apply_update(entity_id, values)
        return None

    monkeypatch.setattr(ExecutionAttempt, "crud_update", classmethod(_attempt_crud_update))
    monkeypatch.setattr(ReviewResult, "crud_update", classmethod(_review_crud_update))
    monkeypatch.setattr(entity_supersede_store, "record_runtime_change", attempts.audit)
    return attempts, reviews


def test_execution_attempt_supersede_sets_pointer_and_never_touches_status(wired) -> None:
    attempts, _ = wired
    step = uuid.uuid4()
    stale = _attempt(step_uuid=step, status="failed")
    replacement = _attempt(step_uuid=step, status="succeeded")
    attempts.rows = {stale.attempt_uuid: stale, replacement.attempt_uuid: replacement}

    record, already = entity_supersede_store.supersede_execution_attempt(
        object(), stale.attempt_uuid, superseded_by_uuid=replacement.attempt_uuid, changed_by="orchestrator"
    )

    assert already is False
    assert record.superseded_by_uuid == replacement.attempt_uuid
    assert record.status == "failed", "the stale row's own recorded outcome must never be rewritten"
    assert len(attempts.audit_calls) == 1
    call = attempts.audit_calls[0]
    assert call["action"] == "update"
    assert call["entity_type"] == "execution_attempt"
    assert call["entity_id"] == stale.attempt_uuid
    assert call["changed_by"] == "orchestrator"
    assert call["changed_fields"] == {
        "old_superseded_by_uuid": None,
        "new_superseded_by_uuid": str(replacement.attempt_uuid),
    }


def test_review_result_supersede_sets_pointer_and_never_touches_status(wired) -> None:
    _, reviews = wired
    stale = _review(status="rejected")
    replacement = _review(object_type=stale.object_type, reviewed_attempt_uuid=None, status="accepted")
    reviews.rows = {stale.review_uuid: stale, replacement.review_uuid: replacement}

    record, already = entity_supersede_store.supersede_review_result(
        object(), stale.review_uuid, superseded_by_uuid=replacement.review_uuid, changed_by="ts-owner-sonnet"
    )

    assert already is False
    assert record.superseded_by_uuid == replacement.review_uuid
    assert record.status == "rejected", "the stale review's own recorded verdict must never be rewritten"


def test_execution_attempt_supersede_idempotent_same_target(wired) -> None:
    attempts, _ = wired
    step = uuid.uuid4()
    replacement = _attempt(step_uuid=step)
    stale = _attempt(step_uuid=step, superseded_by_uuid=replacement.attempt_uuid)
    attempts.rows = {stale.attempt_uuid: stale, replacement.attempt_uuid: replacement}

    record, already = entity_supersede_store.supersede_execution_attempt(
        object(), stale.attempt_uuid, superseded_by_uuid=replacement.attempt_uuid, changed_by="orchestrator"
    )

    assert already is True
    assert record.superseded_by_uuid == replacement.attempt_uuid
    assert attempts.audit_calls == [], "an idempotent no-op writes nothing, including no audit record"


def test_review_result_supersede_idempotent_same_target(wired) -> None:
    _, reviews = wired
    replacement = _review()
    stale = _review(object_type=replacement.object_type, superseded_by_uuid=replacement.review_uuid)
    reviews.rows = {stale.review_uuid: stale, replacement.review_uuid: replacement}

    record, already = entity_supersede_store.supersede_review_result(
        object(), stale.review_uuid, superseded_by_uuid=replacement.review_uuid, changed_by="x"
    )

    assert already is True
    assert record.superseded_by_uuid == replacement.review_uuid


def test_execution_attempt_resupersede_different_target_refused_and_writes_nothing(wired) -> None:
    attempts, _ = wired
    step = uuid.uuid4()
    first_replacement = _attempt(step_uuid=step)
    other_replacement = _attempt(step_uuid=step)
    stale = _attempt(step_uuid=step, superseded_by_uuid=first_replacement.attempt_uuid)
    attempts.rows = {
        stale.attempt_uuid: stale,
        first_replacement.attempt_uuid: first_replacement,
        other_replacement.attempt_uuid: other_replacement,
    }

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), stale.attempt_uuid, superseded_by_uuid=other_replacement.attempt_uuid, changed_by="x"
        )

    assert excinfo.value.code == "EXECUTION_ATTEMPT_ALREADY_SUPERSEDED"
    assert attempts.rows[stale.attempt_uuid].superseded_by_uuid == first_replacement.attempt_uuid
    assert attempts.audit_calls == []


def test_review_result_resupersede_different_target_refused_and_writes_nothing(wired) -> None:
    _, reviews = wired
    first_replacement = _review()
    other_replacement = _review(object_type=first_replacement.object_type)
    stale = _review(object_type=first_replacement.object_type, superseded_by_uuid=first_replacement.review_uuid)
    reviews.rows = {
        stale.review_uuid: stale,
        first_replacement.review_uuid: first_replacement,
        other_replacement.review_uuid: other_replacement,
    }

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_review_result(
            object(), stale.review_uuid, superseded_by_uuid=other_replacement.review_uuid, changed_by="x"
        )

    assert excinfo.value.code == "REVIEW_RESULT_ALREADY_SUPERSEDED"
    assert reviews.rows[stale.review_uuid].superseded_by_uuid == first_replacement.review_uuid


def test_execution_attempt_supersede_self_forbidden(wired) -> None:
    attempts, _ = wired
    stale = _attempt()
    attempts.rows = {stale.attempt_uuid: stale}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), stale.attempt_uuid, superseded_by_uuid=stale.attempt_uuid, changed_by="x"
        )
    assert excinfo.value.code == "EXECUTION_ATTEMPT_SELF_SUPERSEDE"


def test_review_result_supersede_self_forbidden(wired) -> None:
    _, reviews = wired
    stale = _review()
    reviews.rows = {stale.review_uuid: stale}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_review_result(
            object(), stale.review_uuid, superseded_by_uuid=stale.review_uuid, changed_by="x"
        )
    assert excinfo.value.code == "REVIEW_RESULT_SELF_SUPERSEDE"


def test_execution_attempt_supersede_missing_replacement_not_found(wired) -> None:
    attempts, _ = wired
    stale = _attempt()
    attempts.rows = {stale.attempt_uuid: stale}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), stale.attempt_uuid, superseded_by_uuid=uuid.uuid4(), changed_by="x"
        )
    assert excinfo.value.code == "EXECUTION_ATTEMPT_NOT_FOUND"


def test_execution_attempt_supersede_missing_stale_not_found(wired) -> None:
    attempts, _ = wired
    replacement = _attempt()
    attempts.rows = {replacement.attempt_uuid: replacement}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), uuid.uuid4(), superseded_by_uuid=replacement.attempt_uuid, changed_by="x"
        )
    assert excinfo.value.code == "EXECUTION_ATTEMPT_NOT_FOUND"


def test_review_result_supersede_missing_replacement_not_found(wired) -> None:
    _, reviews = wired
    stale = _review()
    reviews.rows = {stale.review_uuid: stale}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_review_result(
            object(), stale.review_uuid, superseded_by_uuid=uuid.uuid4(), changed_by="x"
        )
    assert excinfo.value.code == "REVIEW_RESULT_NOT_FOUND"


def test_execution_attempt_supersede_refuses_soft_deleted_stale(wired) -> None:
    attempts, _ = wired
    step = uuid.uuid4()
    stale = _attempt(step_uuid=step, deleted_at=NOW.isoformat())
    replacement = _attempt(step_uuid=step)
    attempts.rows = {stale.attempt_uuid: stale, replacement.attempt_uuid: replacement}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), stale.attempt_uuid, superseded_by_uuid=replacement.attempt_uuid, changed_by="x"
        )
    assert excinfo.value.code == "EXECUTION_ATTEMPT_NOT_FOUND"


def test_execution_attempt_supersede_lineage_guard_different_step_refused(wired) -> None:
    attempts, _ = wired
    stale = _attempt(step_uuid=uuid.uuid4())
    replacement = _attempt(step_uuid=uuid.uuid4())  # a DIFFERENT step
    attempts.rows = {stale.attempt_uuid: stale, replacement.attempt_uuid: replacement}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_execution_attempt(
            object(), stale.attempt_uuid, superseded_by_uuid=replacement.attempt_uuid, changed_by="x"
        )
    assert excinfo.value.code == "EXECUTION_ATTEMPT_LINEAGE_MISMATCH"


def test_review_result_supersede_lineage_guard_object_type_mismatch_refused(wired) -> None:
    _, reviews = wired
    stale = _review(object_type="execution_attempt")
    replacement = _review(object_type="revision", reviewed_attempt_uuid=None, reviewed_revision_uuid=uuid.uuid4())
    reviews.rows = {stale.review_uuid: stale, replacement.review_uuid: replacement}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_review_result(
            object(), stale.review_uuid, superseded_by_uuid=replacement.review_uuid, changed_by="x"
        )
    assert excinfo.value.code == "REVIEW_RESULT_LINEAGE_MISMATCH"


def test_review_result_supersede_lineage_guard_different_step_attempts_refused(wired, monkeypatch) -> None:
    attempts, reviews = wired
    step_a, step_b = uuid.uuid4(), uuid.uuid4()
    attempt_a = _attempt(step_uuid=step_a)
    attempt_b = _attempt(step_uuid=step_b)
    attempts.rows = {attempt_a.attempt_uuid: attempt_a, attempt_b.attempt_uuid: attempt_b}
    monkeypatch.setattr(entity_supersede_store, "get_execution_attempt", attempts.get)

    stale = _review(object_type="execution_attempt", reviewed_attempt_uuid=attempt_a.attempt_uuid)
    replacement = _review(object_type="execution_attempt", reviewed_attempt_uuid=attempt_b.attempt_uuid)
    reviews.rows = {stale.review_uuid: stale, replacement.review_uuid: replacement}

    with pytest.raises(DomainCommandError) as excinfo:
        entity_supersede_store.supersede_review_result(
            object(), stale.review_uuid, superseded_by_uuid=replacement.review_uuid, changed_by="x"
        )
    assert excinfo.value.code == "REVIEW_RESULT_LINEAGE_MISMATCH"


def test_review_result_supersede_same_step_attempts_allowed(wired, monkeypatch) -> None:
    attempts, reviews = wired
    step = uuid.uuid4()
    attempt_a = _attempt(step_uuid=step)
    attempt_b = _attempt(step_uuid=step)
    attempts.rows = {attempt_a.attempt_uuid: attempt_a, attempt_b.attempt_uuid: attempt_b}
    monkeypatch.setattr(entity_supersede_store, "get_execution_attempt", attempts.get)

    stale = _review(object_type="execution_attempt", reviewed_attempt_uuid=attempt_a.attempt_uuid)
    replacement = _review(object_type="execution_attempt", reviewed_attempt_uuid=attempt_b.attempt_uuid)
    reviews.rows = {stale.review_uuid: stale, replacement.review_uuid: replacement}

    record, already = entity_supersede_store.supersede_review_result(
        object(), stale.review_uuid, superseded_by_uuid=replacement.review_uuid, changed_by="x"
    )
    assert already is False
    assert record.superseded_by_uuid == replacement.review_uuid


# to_payload() exposure and row-loader unpack-safety (bug 0798c162) for the
# appended superseded_by_uuid column are covered in the sibling file
# tests/test_bug_74479c06_supersede_payload_unpack.py (kept separate to stay
# under the project's 400-line-per-file guideline).
