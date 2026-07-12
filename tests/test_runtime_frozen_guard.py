"""Frozen-truth mutation guard test coverage (C-035, HRS {d118} bullet 20)."""

import pytest

from plan_manager.domain.runtime_validation import FrozenTruthMutationError, guard_frozen_truth

FROZEN_TRUTH_TABLES = (
    "plan",
    "revision",
    "step",
    "concept",
    "relation",
    "paragraph",
    "node_version",
    "ref",
)

RUNTIME_TABLES = (
    "todo_item",
    "todo_link",
    "model_binding",
    "runtime_comment",
    "execution_attempt",
    "review_result",
    "escalation",
    "bug_report",
    "bug_impact",
    "project_dependency",
    "bug_fix",
    "bug_fix_propagation",
)

@pytest.mark.parametrize("table", FROZEN_TRUTH_TABLES)
def test_guard_frozen_truth_rejects_every_frozen_truth_table(table: str) -> None:
    with pytest.raises(FrozenTruthMutationError):
        guard_frozen_truth(table)

@pytest.mark.parametrize("table", RUNTIME_TABLES)
def test_guard_frozen_truth_passes_every_runtime_table(table: str) -> None:
    assert guard_frozen_truth(table) is None
