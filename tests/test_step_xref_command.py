import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_xref_command import (
    StepXrefCommand,
    _locations_for_hash,
    _resolve_query_hash,
)
from plan_manager.domain.step import Step
from plan_manager.storage.canonical import content_hash
from plan_manager.views.step_fingerprint import build_field_hash_index

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

def _plan_nodes() -> dict[uuid.UUID, Step]:
    shared_text = "shared prompt fragment"
    g1 = _step("00000000-0000-0000-0000-000000000001", 3, "G-001", None, fields={})
    t1 = _step("00000000-0000-0000-0000-000000000002", 4, "T-001", g1.uuid, fields={})
    a1 = _step(
        "00000000-0000-0000-0000-000000000003", 5, "A-001", t1.uuid,
        fields={"prompt": shared_text},
    )
    a2 = _step(
        "00000000-0000-0000-0000-000000000004", 5, "A-002", t1.uuid,
        fields={"prompt": shared_text},
    )
    return {step.uuid: step for step in (g1, t1, a1, a2)}

def test_step_xref_schema_requires_plan_and_exposes_pagination() -> None:
    schema = StepXrefCommand.get_schema()

    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert "text" in schema["properties"]
    assert "step" in schema["properties"]
    assert "field" in schema["properties"]
    assert "limit" in schema["properties"]
    assert "offset" in schema["properties"]

def test_resolve_query_hash_from_text() -> None:
    nodes = _plan_nodes()

    result = _resolve_query_hash(nodes, "shared prompt fragment", None, None)

    assert result == content_hash("shared prompt fragment")

def test_resolve_query_hash_from_step_field() -> None:
    nodes = _plan_nodes()

    result = _resolve_query_hash(nodes, None, "G-001/T-001/A-001", "prompt")

    assert result == content_hash("shared prompt fragment")

def test_resolve_query_hash_rejects_both_text_and_step() -> None:
    nodes = _plan_nodes()

    with pytest.raises(DomainCommandError) as excinfo:
        _resolve_query_hash(nodes, "text", "G-001/T-001/A-001", "prompt")

    assert excinfo.value.code == "INVALID_FILTER"

def test_resolve_query_hash_rejects_neither_text_nor_step() -> None:
    nodes = _plan_nodes()

    with pytest.raises(DomainCommandError) as excinfo:
        _resolve_query_hash(nodes, None, None, None)

    assert excinfo.value.code == "INVALID_FILTER"

def test_resolve_query_hash_rejects_step_without_field() -> None:
    nodes = _plan_nodes()

    with pytest.raises(DomainCommandError) as excinfo:
        _resolve_query_hash(nodes, None, "G-001/T-001/A-001", None)

    assert excinfo.value.code == "INVALID_FILTER"

def test_resolve_query_hash_rejects_unknown_field() -> None:
    nodes = _plan_nodes()

    with pytest.raises(DomainCommandError) as excinfo:
        _resolve_query_hash(nodes, None, "G-001/T-001/A-001", "missing_field")

    assert excinfo.value.code == "INVALID_FILTER"

def test_resolve_query_hash_propagates_step_not_found() -> None:
    nodes = _plan_nodes()

    with pytest.raises(DomainCommandError) as excinfo:
        _resolve_query_hash(nodes, None, "G-999", "prompt")

    assert excinfo.value.code == "STEP_NOT_FOUND"

def test_locations_for_hash_marks_first_by_canonical_order_as_defined() -> None:
    nodes = _plan_nodes()
    index = build_field_hash_index(nodes)
    target_hash = content_hash("shared prompt fragment")

    locations = _locations_for_hash(nodes, index, target_hash)

    assert [loc["path"] for loc in locations] == [
        "G-001/T-001/A-001",
        "G-001/T-001/A-002",
    ]
    assert locations[0]["role"] == "defined"
    assert locations[1]["role"] == "inlined"
    assert all(loc["field"] == "prompt" for loc in locations)
    assert all(loc["content_hash"] == target_hash for loc in locations)

def test_locations_for_hash_empty_for_unmatched_hash() -> None:
    nodes = _plan_nodes()
    index = build_field_hash_index(nodes)

    assert _locations_for_hash(nodes, index, content_hash("nothing matches")) == []
