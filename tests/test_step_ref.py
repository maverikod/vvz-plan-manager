import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=[],
        concepts=[],
        status="draft",
    )


def test_resolve_step_ref_refuses_ambiguous_local_id() -> None:
    g1 = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    g2 = _step("00000000-0000-0000-0000-000000000012", 3, "G-002", None)
    t1 = _step("00000000-0000-0000-0000-000000000021", 4, "T-001", g1.uuid)
    t2 = _step("00000000-0000-0000-0000-000000000022", 4, "T-001", g2.uuid)
    nodes = {step.uuid: step for step in (g1, g2, t1, t2)}

    with pytest.raises(DomainCommandError) as excinfo:
        resolve_step_ref(nodes, "T-001")

    assert excinfo.value.code == "AMBIGUOUS_STEP_ID"
    assert excinfo.value.details["matches"] == ["G-001/T-001", "G-002/T-001"]


def test_resolve_step_ref_accepts_path_and_uuid() -> None:
    g1 = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    g2 = _step("00000000-0000-0000-0000-000000000012", 3, "G-002", None)
    t1 = _step("00000000-0000-0000-0000-000000000021", 4, "T-001", g1.uuid)
    t2 = _step("00000000-0000-0000-0000-000000000022", 4, "T-001", g2.uuid)
    nodes = {step.uuid: step for step in (g1, g2, t1, t2)}

    assert resolve_step_ref(nodes, "G-002/T-001").uuid == t2.uuid
    assert resolve_step_ref(nodes, str(t1.uuid)).uuid == t1.uuid
    assert canonical_step_path(nodes, t1) == "G-001/T-001"
