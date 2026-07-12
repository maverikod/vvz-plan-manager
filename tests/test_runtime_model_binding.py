from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.domain.model_binding_inheritance import (
    INHERITANCE_ORDER,
    scope_rank,
    is_more_specific,
    order_by_specificity,
    most_specific,
)
from plan_manager.domain.model_binding import BindingScope, ModelBinding
from plan_manager.domain.model_resolution import (
    ResolutionTarget,
    ModelResolution,
    ModelResolutionError,
    binding_applies,
    resolve_effective_binding,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError


def _make_binding(
    *,
    scope: str,
    provider: str = "anthropic",
    model: str = "sonnet",
    role: str | None = None,
    plan_uuid: uuid.UUID | None = None,
    step_uuid: uuid.UUID | None = None,
    active: bool = True,
    deleted_at: str | None = None,
) -> ModelBinding:
    now = datetime.now(timezone.utc).isoformat()
    return ModelBinding(
        binding_uuid=uuid.uuid4(),
        scope=scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=None,
        branch_step_uuid=None,
        revision_uuid=None,
        step_uuid=step_uuid,
        step_path=None,
        provider=provider,
        model=model,
        fallback_provider=None,
        fallback_model=None,
        max_retries=1,
        timeout=600,
        context_budget=None,
        active=active,
        created_by="test",
        created_at=now,
        updated_at=now,
        deleted_at=deleted_at,
    )


def test_scope_rank_ascending_specificity():
    assert scope_rank("system") == 0
    assert scope_rank("plan") == 1
    assert scope_rank("role") == 5
    assert scope_rank("role") > scope_rank("system")


def test_is_more_specific():
    assert is_more_specific("step", "plan") is True
    assert is_more_specific("plan", "step") is False
    assert is_more_specific("system", "system") is False


def test_order_by_specificity():
    result = order_by_specificity(["role", "system", "step"])
    assert result == ["system", "step", "role"]


def test_most_specific():
    assert most_specific(["plan", "role", "system"]) == "role"


def test_most_specific_empty_raises():
    with pytest.raises(RuntimeValidationError):
        most_specific([])


def test_scope_rank_rejects_unknown_scope():
    with pytest.raises(RuntimeValidationError):
        scope_rank("not_a_scope")


def test_binding_applies_system_scope_always_applies():
    binding = _make_binding(scope="system", role=None)
    target = ResolutionTarget(role="code_executor")
    assert binding_applies(binding, target) is True


def test_binding_applies_plan_scope_requires_matching_plan():
    plan_uuid = uuid.uuid4()
    binding = _make_binding(scope="plan", plan_uuid=plan_uuid, role=None)
    target = ResolutionTarget(role="code_executor", plan_uuid=plan_uuid)
    assert binding_applies(binding, target) is True

    target_other = ResolutionTarget(role="code_executor", plan_uuid=uuid.uuid4())
    assert binding_applies(binding, target_other) is False


def test_binding_applies_step_scope_requires_matching_step():
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    binding = _make_binding(scope="step", plan_uuid=plan_uuid, step_uuid=step_uuid, role=None)
    target = ResolutionTarget(role="code_executor", plan_uuid=plan_uuid, step_uuid=step_uuid)
    assert binding_applies(binding, target) is True

    target_other_step = ResolutionTarget(role="code_executor", plan_uuid=plan_uuid, step_uuid=uuid.uuid4())
    assert binding_applies(binding, target_other_step) is False


def test_binding_applies_rejects_inactive_binding():
    binding = _make_binding(scope="system", active=False)
    assert binding_applies(binding, ResolutionTarget(role="code_executor")) is False


def test_binding_applies_role_gate():
    binding = _make_binding(scope="system", role="code_executor")
    assert binding_applies(binding, ResolutionTarget(role="code_executor")) is True
    assert binding_applies(binding, ResolutionTarget(role="bug_fixer")) is False


def test_resolve_effective_binding_picks_most_specific():
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()

    binding_system = _make_binding(scope="system", provider="anthropic", model="haiku")
    binding_plan = _make_binding(scope="plan", plan_uuid=plan_uuid, provider="anthropic", model="sonnet")
    binding_step = _make_binding(scope="step", plan_uuid=plan_uuid, step_uuid=step_uuid, provider="anthropic", model="opus")

    candidates = [binding_system, binding_plan, binding_step]
    target = ResolutionTarget(role="code_executor", plan_uuid=plan_uuid, step_uuid=step_uuid)
    resolution = resolve_effective_binding(candidates, target)

    assert resolution.effective_model == "opus"
    assert resolution.source == "step"


def test_resolve_effective_binding_no_applicable_candidates_raises():
    binding = _make_binding(scope="plan", plan_uuid=uuid.uuid4())
    target = ResolutionTarget(role="code_executor", plan_uuid=uuid.uuid4())

    with pytest.raises(ModelResolutionError):
        resolve_effective_binding([binding], target)


def test_resolve_effective_binding_less_specific_present_but_overridden():
    plan_uuid = uuid.uuid4()
    binding_system = _make_binding(scope="system", model="haiku", role=None)
    binding_plan = _make_binding(scope="plan", plan_uuid=plan_uuid, model="sonnet", role=None)

    target = ResolutionTarget(role="code_executor", plan_uuid=plan_uuid)
    resolution = resolve_effective_binding([binding_system, binding_plan], target)

    assert resolution.effective_model == "sonnet"
    assert resolution.source == "plan"
