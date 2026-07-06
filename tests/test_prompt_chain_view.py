import uuid

import pytest

from plan_manager.domain.step import Step
from plan_manager.views.prompt_chain import (
    cache_key,
    eligible_atomic_steps,
    normalize_role,
    normalize_scope,
    normalize_statuses,
    scope_atomic_steps,
)
from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    status: str = "frozen",
) -> Step:
    fields = {}
    if level == 5:
        fields = {"target_file": "x.py", "operation": "update", "priority": 1}
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status=status,
    )


def test_normalize_scope_accepts_whole_global_and_tactical() -> None:
    assert normalize_scope(None).label == "whole_plan"
    assert normalize_scope("whole_plan").label == "whole_plan"
    assert normalize_scope("G-001").label == "G-001"
    assert normalize_scope("G-001/T-002").label == "G-001/T-002"


def test_normalize_scope_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError):
        normalize_scope("A-001")


def test_normalize_role_accepts_default_and_rejects_unknown() -> None:
    assert normalize_role(None) == "coder"
    assert normalize_role("review") == "review"
    with pytest.raises(ValueError):
        normalize_role("executor")


def test_normalize_statuses_defaults_and_rejects_unknown_values() -> None:
    assert normalize_statuses(None) == ["frozen", "ready_for_review"]
    with pytest.raises(ValueError):
        normalize_statuses(["frozen", "bogus"])


def test_cache_key_is_canonical_and_stable() -> None:
    assert cache_key({"b": 2, "a": 1}) == cache_key({"a": 1, "b": 2})


def test_plan_prompt_chain_schema_matches_rev2_contract() -> None:
    schema = PlanPromptChainCommand.get_schema()

    assert PlanPromptChainCommand.use_queue is True
    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["role"]["enum"] == ["coder", "review", "conscience"]
    assert schema["properties"]["role"]["default"] == "coder"
    assert schema["properties"]["include_statuses"]["default"] == [
        "frozen",
        "ready_for_review",
    ]


def test_scope_and_status_filter_select_atomic_branch_chain() -> None:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid)
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid)
    draft_atomic = _step(
        "00000000-0000-0000-0000-000000000014",
        5,
        "A-002",
        ts.uuid,
        status="draft",
    )
    nodes = {step.uuid: step for step in (gs, ts, atomic, draft_atomic)}

    scoped = scope_atomic_steps(nodes, normalize_scope("G-001/T-001"))
    assert [step.step_id for step in scoped] == ["A-001", "A-002"]

    eligible = eligible_atomic_steps(nodes, scoped, ["frozen", "ready_for_review"])
    assert [step.step_id for step in eligible] == ["A-001"]
