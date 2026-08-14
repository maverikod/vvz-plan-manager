"""Regression suite for bug 74479c06 (group-4 fix), split from
tests/test_bug_74479c06_supersede_lifecycle.py to stay under the project's
400-line-per-file guideline (the guard/idempotency/audit store tests live in
that sibling file).

Covers, per the group-4 acceptance checklist:
  * to_payload() exposes superseded_by_uuid on both entities;
  * row-loader unpack-safety (bug 0798c162) for the appended column, on both
    execution_attempt_store._row_to_record (dict-keyed) and
    review_result_store._row_to_record (also converted to dict-keyed by this
    fix -- see that store's docstring).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.review_result import ReviewResult
from plan_manager.storage import execution_attempt_store, review_result_store

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _attempt(**overrides) -> ExecutionAttempt:
    base = dict(
        attempt_uuid=uuid.uuid4(), plan_uuid=uuid.uuid4(), revision_uuid=None,
        step_uuid=uuid.uuid4(), step_path=None, todo_uuid=None, bug_fix_uuid=None,
        assigned_binding_uuid=None, assigned_provider=None, assigned_model=None,
        used_provider=None, used_model=None, runtime=None, vast_instance_id=None,
        started_at=None, finished_at=None, status="succeeded", input_context_hash=None,
        result_summary=None, changed_files=None, command_test_results=None,
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
        reviewer="reviewer", status="accepted", findings=None,
        evidence=None, verification_commands=None, escalation_target_uuid=None,
        created_by="tester", created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        deleted_at=None, superseded_by_uuid=None,
    )
    base.update(overrides)
    return ReviewResult(**base)


def test_execution_attempt_payload_exposes_superseded_by_uuid() -> None:
    target = uuid.uuid4()
    record = _attempt(superseded_by_uuid=target)
    payload = record.to_payload()
    assert payload["superseded_by_uuid"] == str(target)

    record_none = _attempt(superseded_by_uuid=None)
    assert record_none.to_payload()["superseded_by_uuid"] is None


def test_review_result_payload_exposes_superseded_by_uuid() -> None:
    target = uuid.uuid4()
    record = _review(superseded_by_uuid=target)
    payload = record.to_payload()
    assert payload["superseded_by_uuid"] == str(target)

    record_none = _review(superseded_by_uuid=None)
    assert record_none.to_payload()["superseded_by_uuid"] is None


def test_execution_attempt_row_to_record_unpack_safe_with_superseded_by_uuid() -> None:
    """bug 0798c162: appending a column must not silently misalign the row unpack.

    execution_attempt_store._row_to_record accepts either a dict (the normal
    crud_get/crud_list return shape, keyed by column name) or a raw tuple
    (zipped onto _COLUMNS by name before any field is read) -- both are
    exercised here.
    """
    attempt_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    superseded_by = uuid.uuid4()

    row_as_dict = {name: None for name in execution_attempt_store._COLUMNS}
    row_as_dict.update(
        uuid=attempt_uuid, plan_uuid=uuid.uuid4(), step_uuid=step_uuid, status="succeeded",
        created_by="tester", created_at=NOW, updated_at=NOW, superseded_by_uuid=superseded_by,
    )
    record = execution_attempt_store._row_to_record(row_as_dict)
    assert record.attempt_uuid == attempt_uuid
    assert record.step_uuid == step_uuid
    assert record.superseded_by_uuid == superseded_by

    row_as_tuple = tuple(row_as_dict[name] for name in execution_attempt_store._COLUMNS)
    record_from_tuple = execution_attempt_store._row_to_record(row_as_tuple)
    assert record_from_tuple.attempt_uuid == attempt_uuid
    assert record_from_tuple.superseded_by_uuid == superseded_by


def test_review_result_row_to_record_unpack_safe_with_superseded_by_uuid() -> None:
    """bug 0798c162: appending a column must not silently misalign the row unpack.

    review_result_store._row_to_record now zips the row into a dict keyed by
    _REVIEW_RESULT_COLUMN_NAMES before reading any field by name (this fix's
    own unpack-safety hardening; previously it read the row by raw positional
    index, which a future appended column would have silently misaligned).
    """
    review_uuid = uuid.uuid4()
    superseded_by = uuid.uuid4()
    row = (
        review_uuid, "execution_attempt", uuid.uuid4(), None, "reviewer",
        "accepted", None, None, None, None,
        "tester", NOW, NOW, None, superseded_by,
    )
    assert len(row) == len(review_result_store._REVIEW_RESULT_COLUMN_NAMES)
    record = review_result_store._row_to_record(row)
    assert record.review_uuid == review_uuid
    assert record.status == "accepted"
    assert record.superseded_by_uuid == superseded_by
