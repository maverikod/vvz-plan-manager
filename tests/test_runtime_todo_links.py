from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.todo_link import (
    TodoLink,
    TodoLinkType,
    TODO_LINK_TYPES,
    BLOCKING_LINK_TYPES,
    guard_self_reference,
    guard_no_duplicate,
    guard_no_blocking_cycle,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError


def test_guard_self_reference_rejects_link_to_self() -> None:
    todo_uuid = uuid.uuid4()
    with pytest.raises(RuntimeValidationError):
        guard_self_reference(todo_uuid, todo_uuid)


def test_guard_self_reference_accepts_distinct_todos() -> None:
    guard_self_reference(uuid.uuid4(), uuid.uuid4())


def test_guard_no_duplicate_rejects_existing_candidate() -> None:
    from_uuid = uuid.uuid4()
    to_uuid = uuid.uuid4()
    candidate = (str(from_uuid), str(to_uuid), TodoLinkType.RELATES_TO.value)
    existing = {candidate}
    with pytest.raises(RuntimeValidationError):
        guard_no_duplicate(existing, candidate)


def test_guard_no_duplicate_accepts_new_candidate() -> None:
    candidate = (str(uuid.uuid4()), str(uuid.uuid4()), TodoLinkType.RELATES_TO.value)
    guard_no_duplicate(set(), candidate)


def test_guard_no_blocking_cycle_accepts_acyclic_edges() -> None:
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    guard_no_blocking_cycle([(a, b), (b, c)])


def test_guard_no_blocking_cycle_rejects_cyclic_edges() -> None:
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(RuntimeValidationError):
        guard_no_blocking_cycle([(a, b), (b, c), (c, a)])


def test_guard_no_blocking_cycle_detects_cycle_from_normalized_blocked_by_edges() -> None:
    todo_a = uuid.uuid4()
    todo_b = uuid.uuid4()
    # link 1: todo_a is BLOCKED_BY todo_b -> normalized "blocks" edge is (str(todo_b), str(todo_a))
    edge_1 = (str(todo_b), str(todo_a))
    # link 2: todo_b is BLOCKED_BY todo_a -> normalized "blocks" edge is (str(todo_a), str(todo_b))
    edge_2 = (str(todo_a), str(todo_b))
    with pytest.raises(RuntimeValidationError):
        guard_no_blocking_cycle([edge_1, edge_2])


def test_blocking_link_types_contains_blocks_and_blocked_by() -> None:
    assert BLOCKING_LINK_TYPES == frozenset({"blocks", "blocked_by"})


def test_todo_link_types_matches_enum_members() -> None:
    assert TODO_LINK_TYPES == frozenset(t.value for t in TodoLinkType)


def test_todo_link_to_payload_serializes_uuid_fields_as_strings() -> None:
    link_uuid = uuid.uuid4()
    from_uuid = uuid.uuid4()
    to_uuid = uuid.uuid4()
    link = TodoLink(
        link_uuid=link_uuid,
        from_todo_uuid=from_uuid,
        to_todo_uuid=to_uuid,
        link_type=TodoLinkType.RELATES_TO.value,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )
    payload = link.to_payload()
    assert payload["link_uuid"] == str(link_uuid)
    assert payload["from_todo_uuid"] == str(from_uuid)
    assert payload["to_todo_uuid"] == str(to_uuid)
    assert payload["deleted_at"] is None
