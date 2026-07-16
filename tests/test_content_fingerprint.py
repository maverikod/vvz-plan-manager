import uuid

import pytest

from plan_manager.domain.step import Step
from plan_manager.storage.canonical import content_hash
from plan_manager.views.step_fingerprint import (
    build_field_hash_index,
    step_field_hash,
    step_field_hashes,
)

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    fields: dict,
) -> Step:
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
        status="draft",
    )

def test_step_field_hash_matches_content_hash_of_field_value() -> None:
    step = _step(
        "00000000-0000-0000-0000-000000000011", 5, "A-001", None,
        fields={"prompt": "do the thing"},
    )

    assert step_field_hash(step, "prompt") == content_hash("do the thing")

def test_step_field_hash_raises_key_error_for_missing_field() -> None:
    step = _step("00000000-0000-0000-0000-000000000011", 5, "A-001", None, fields={})

    with pytest.raises(KeyError):
        step_field_hash(step, "prompt")

def test_step_field_hashes_covers_every_field() -> None:
    step = _step(
        "00000000-0000-0000-0000-000000000011", 5, "A-001", None,
        fields={"prompt": "do the thing", "priority": 1},
    )

    hashes = step_field_hashes(step)

    assert hashes == {
        "prompt": content_hash("do the thing"),
        "priority": content_hash(1),
    }

def test_step_field_hashes_empty_for_no_fields() -> None:
    step = _step("00000000-0000-0000-0000-000000000011", 5, "A-001", None, fields={})

    assert step_field_hashes(step) == {}

def test_build_field_hash_index_groups_matching_content_across_steps() -> None:
    shared_text = "shared prompt fragment"
    a1 = _step(
        "00000000-0000-0000-0000-000000000011", 5, "A-001", None,
        fields={"prompt": shared_text},
    )
    a2 = _step(
        "00000000-0000-0000-0000-000000000012", 5, "A-002", None,
        fields={"prompt": shared_text, "target_file": "x.py"},
    )
    nodes = {step.uuid: step for step in (a1, a2)}

    index = build_field_hash_index(nodes)

    shared_hash = content_hash(shared_text)
    assert set(index[shared_hash]) == {(a1.uuid, "prompt"), (a2.uuid, "prompt")}
    assert index[content_hash("x.py")] == [(a2.uuid, "target_file")]

def test_build_field_hash_index_empty_for_no_steps() -> None:
    assert build_field_hash_index({}) == {}
