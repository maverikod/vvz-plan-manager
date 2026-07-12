from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.primary_anchor import PrimaryAnchor, PrimaryAnchorType, validate_anchor
from plan_manager.domain.runtime_validation import (
    RuntimeValidationError,
    FrozenTruthMutationError,
    FROZEN_TRUTH_TABLES,
    guard_frozen_truth,
    validate_priority_nice,
    PRIORITY_NICE_MIN,
    PRIORITY_NICE_MAX,
)
from plan_manager.domain.nice_priority import validate_nice_priority


class _FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row


class _FakeConnection:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def execute(self, sql: str, params: tuple) -> _FakeCursor:
        return _FakeCursor(self._row)


def test_unanchored_todo_anchor_is_accepted() -> None:
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.NONE.value)
    validate_anchor(_FakeConnection(None), anchor)


def test_project_anchored_todo_with_valid_project_id_is_accepted() -> None:
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.PROJECT.value, project_id=uuid.uuid4())
    validate_anchor(_FakeConnection(None), anchor)


def test_project_anchored_todo_without_project_id_is_rejected() -> None:
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.PROJECT.value, project_id=None)
    with pytest.raises(RuntimeValidationError):
        validate_anchor(_FakeConnection(None), anchor)


def test_file_anchored_todo_with_valid_reference_is_accepted() -> None:
    anchor = PrimaryAnchor(
        anchor_type=PrimaryAnchorType.FILE.value,
        project_id=uuid.uuid4(),
        file_path="src/module.py"
    )
    validate_anchor(_FakeConnection(None), anchor)


def test_file_anchored_todo_with_absolute_path_is_rejected() -> None:
    anchor = PrimaryAnchor(
        anchor_type=PrimaryAnchorType.FILE.value,
        project_id=uuid.uuid4(),
        file_path="/etc/passwd"
    )
    with pytest.raises(RuntimeValidationError):
        validate_anchor(_FakeConnection(None), anchor)


def test_frozen_step_anchor_is_accepted_as_valid_reference() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    revision_uuid = uuid.uuid4()
    anchor = PrimaryAnchor(
        anchor_type=PrimaryAnchorType.STEP.value,
        plan_uuid=plan_uuid,
        step_uuid=step_uuid,
        step_path="G-001/T-001"
    )
    fake_conn = _FakeConnection((revision_uuid,))
    validate_anchor(fake_conn, anchor)
    # anchoring a TODO to a frozen step is a valid runtime REFERENCE, not a mutation — must not raise


def test_guard_frozen_truth_rejects_mutation_of_step_table() -> None:
    # guard_frozen_truth is about MUTATING a frozen-truth TABLE, distinct from anchoring/referencing one (see test 6 above)
    with pytest.raises(FrozenTruthMutationError):
        guard_frozen_truth("step")


def test_guard_frozen_truth_accepts_runtime_table() -> None:
    guard_frozen_truth("todo_item")


def test_frozen_truth_tables_contains_exact_member_set() -> None:
    assert FROZEN_TRUTH_TABLES == frozenset({"plan", "revision", "step", "concept", "relation", "paragraph", "node_version", "ref"})


def test_validate_nice_priority_accepts_boundary_values() -> None:
    assert validate_nice_priority(0) == 0
    assert validate_nice_priority(PRIORITY_NICE_MIN) == PRIORITY_NICE_MIN
    assert validate_nice_priority(PRIORITY_NICE_MAX) == PRIORITY_NICE_MAX


def test_validate_nice_priority_rejects_value_below_minimum() -> None:
    with pytest.raises(RuntimeValidationError):
        validate_nice_priority(PRIORITY_NICE_MIN - 1)


def test_validate_nice_priority_rejects_value_above_maximum() -> None:
    with pytest.raises(RuntimeValidationError):
        validate_nice_priority(PRIORITY_NICE_MAX + 1)


def test_validate_priority_nice_accepts_boundary_values() -> None:
    assert validate_priority_nice(PRIORITY_NICE_MIN) == PRIORITY_NICE_MIN
    assert validate_priority_nice(PRIORITY_NICE_MAX) == PRIORITY_NICE_MAX


def test_validate_priority_nice_rejects_out_of_range_value() -> None:
    with pytest.raises(RuntimeValidationError):
        validate_priority_nice(PRIORITY_NICE_MAX + 1)
