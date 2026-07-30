"""reference_inspect command regression suite (CR-6 G-004/T-004, C-012).

Fakes only — lookup_referrers is monkeypatched and db_connection yields a dummy,
so nothing here touches a database.

Module-name note: the authoring step named the command module
reference_inspection_command.py, but the registry derives a command's module from
its name, so the shipped module is reference_inspect_command.py. This test file
keeps the step's filename.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from plan_manager.commands import reference_inspect_command as module
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.commands.reference_inspect_command import ReferenceInspectCommand
from plan_manager.views.dependents_closure import DEFAULT_DEPTH_LIMIT, MAX_DEPTH_LIMIT


@contextmanager
def _fake_db():
    yield object()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)


def _run(**params: Any) -> Any:
    return asyncio.run(ReferenceInspectCommand().execute(**params))


def _referrer(table: str, column: str, referrer_id: Any) -> dict[str, Any]:
    return {
        "table": table,
        "column": column,
        "referrer_id": referrer_id,
        "referrer_kind": table,
    }


def _install_lookup(
    monkeypatch: pytest.MonkeyPatch, graph: dict[tuple[str, str], list[dict[str, Any]]]
) -> list[tuple[str, Any]]:
    """Replace lookup_referrers with a graph-driven fake, recording every probe."""
    probes: list[tuple[str, Any]] = []

    def _lookup(conn: Any, table: str, entity_id: Any) -> list[dict[str, Any]]:
        probes.append((table, entity_id))
        return graph.get((table, str(entity_id)), [])

    monkeypatch.setattr(module, "lookup_referrers", _lookup)
    return probes


# ---------------------------------------------------------------- direct listing


def test_direct_referrers_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = uuid.uuid4()
    todo_id = uuid.uuid4()
    bug_id = uuid.uuid4()
    probes = _install_lookup(
        monkeypatch,
        {
            ("plan", str(plan_id)): [
                _referrer("todo_item", "anchor_plan_uuid", todo_id),
                _referrer("bug_report", "source_plan_uuid", bug_id),
            ]
        },
    )

    result = _run(entity_type="plan", entity_id=str(plan_id), recursive=False)

    assert result.data["entity_type"] == "plan"
    assert result.data["entity_id"] == str(plan_id)
    assert result.data["direct_referrers"] == [
        {
            "table": "todo_item",
            "column": "anchor_plan_uuid",
            "referrer_kind": "todo_item",
            "referrer_id": str(todo_id),
        },
        {
            "table": "bug_report",
            "column": "source_plan_uuid",
            "referrer_kind": "bug_report",
            "referrer_id": str(bug_id),
        },
    ]
    # referrer_kind, never referrer_type: the key set must match the guard and
    # the DELETE_BLOCKED payload exactly.
    for row in result.data["direct_referrers"]:
        assert set(row) == {"table", "column", "referrer_kind", "referrer_id"}
    assert "traversal" not in result.data, "a non-recursive call must not traverse"
    assert len(probes) == 1, f"one hop must issue exactly one probe, got {probes}"


@pytest.mark.parametrize(
    ("entity_type", "table"),
    [("todo", "todo_item"), ("comment", "runtime_comment"), ("bug", "bug_report")],
)
def test_entity_type_resolves_to_table_name(
    monkeypatch: pytest.MonkeyPatch, entity_type: str, table: str
) -> None:
    """The ENTITY_TYPE must be converted before the guard sees it.

    Handing the entity type straight to lookup_referrers matches no catalog entry
    and returns zero referrers, which reads as "nothing references this" when in
    truth everything does (bugs e52daeab, 113a7888).
    """
    entity_id = uuid.uuid4()
    probes = _install_lookup(monkeypatch, {})

    _run(entity_type=entity_type, entity_id=str(entity_id), recursive=False)

    assert probes == [(table, entity_id)]
    assert probes[0][0] != entity_type, (
        f"the raw entity type {entity_type!r} reached the guard instead of {table!r}"
    )


# ---------------------------------------------------------------- traversal


def test_recursive_traversal_with_cycle_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # a -> b -> c -> a: without a visited set this never terminates.
    _install_lookup(
        monkeypatch,
        {
            ("plan", str(a)): [_referrer("todo_item", "anchor_plan_uuid", b)],
            ("todo_item", str(b)): [_referrer("runtime_comment", "anchor_ref_id", c)],
            ("runtime_comment", str(c)): [_referrer("plan", "uuid", a)],
        },
    )

    result = _run(entity_type="plan", entity_id=str(a), recursive=True, depth_limit=10)

    traversal = result.data["traversal"]
    assert traversal["cycles_detected"] > 0, "the closing edge must be counted as a cycle"
    # origin plus the two fresh nodes; the origin is never re-expanded.
    assert traversal["nodes_visited"] == 3
    assert traversal["edges_traversed"] == 3
    reached = {row["referrer_id"] for row in result.data["items"]}
    assert reached == {str(b), str(c)}


def test_depth_limit_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [uuid.uuid4() for _ in range(5)]
    graph: dict[tuple[str, str], list[dict[str, Any]]] = {
        ("plan", str(ids[0])): [_referrer("todo_item", "anchor_plan_uuid", ids[1])]
    }
    for index in range(1, 4):
        graph[("todo_item", str(ids[index]))] = [
            _referrer("todo_item", "anchor_plan_uuid", ids[index + 1])
        ]
    _install_lookup(monkeypatch, graph)

    result = _run(entity_type="plan", entity_id=str(ids[0]), recursive=True, depth_limit=2)

    depths = {row["depth"] for row in result.data["items"]}
    assert depths == {1, 2}, f"nodes beyond depth 2 leaked in: {result.data['items']}"
    reached = {row["referrer_id"] for row in result.data["items"]}
    assert reached == {str(ids[1]), str(ids[2])}
    assert str(ids[3]) not in reached


def test_depth_limit_clamping(monkeypatch: pytest.MonkeyPatch) -> None:
    clamped: list[int] = []
    real_traverse = module._traverse

    def _spy(conn: Any, table: str, entity_id: Any, depth_limit: int):
        clamped.append(depth_limit)
        return real_traverse(conn, table, entity_id, depth_limit)

    monkeypatch.setattr(module, "_traverse", _spy)
    _install_lookup(monkeypatch, {})

    _run(
        entity_type="plan",
        entity_id=str(uuid.uuid4()),
        recursive=True,
        depth_limit=MAX_DEPTH_LIMIT + 500,
    )

    assert clamped == [MAX_DEPTH_LIMIT], "an over-large depth must be clamped, not honoured"
    assert module._clamp_depth(0) == 1
    assert module._clamp_depth("many") == DEFAULT_DEPTH_LIMIT


# ---------------------------------------------------------------- pagination


def test_pagination_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = uuid.uuid4()
    referrers = [
        _referrer("todo_item", "anchor_plan_uuid", uuid.uuid4()) for _ in range(20)
    ]
    _install_lookup(monkeypatch, {("plan", str(plan_id)): referrers})

    result = _run(entity_type="plan", entity_id=str(plan_id), limit=10, offset=5)

    assert result.data["total"] == 20, "total is the full count before the window"
    assert result.data["limit"] == 10
    assert result.data["offset"] == 5
    assert len(result.data["items"]) == 10
    assert result.data["items"][0]["referrer_id"] == str(referrers[5]["referrer_id"])
    # direct_referrers stays complete; only items is windowed.
    assert len(result.data["direct_referrers"]) == 20


@pytest.mark.parametrize(("limit", "offset"), [(0, None), (None, -1)])
def test_invalid_pagination_rejected(
    monkeypatch: pytest.MonkeyPatch, limit: int | None, offset: int | None
) -> None:
    _install_lookup(monkeypatch, {})

    result = _run(entity_type="plan", entity_id=str(uuid.uuid4()), limit=limit, offset=offset)

    assert result.details["domain_code"] == "INVALID_PAGINATION"


def test_recursive_total_count_matches_the_paginated_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_id = uuid.uuid4()
    referrers = [_referrer("todo_item", "anchor_plan_uuid", uuid.uuid4()) for _ in range(4)]
    _install_lookup(monkeypatch, {("plan", str(plan_id)): referrers})

    result = _run(entity_type="plan", entity_id=str(plan_id), recursive=True, limit=2)

    assert result.data["total"] == 4
    assert result.data["traversal"]["total_count"] == 4, (
        "traversal.total_count must report the full closure, not the page"
    )
    assert len(result.data["items"]) == 2


# ---------------------------------------------------------------- validation/metadata


def test_entity_id_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_lookup(monkeypatch, {})

    result = _run(entity_type="plan", entity_id="not-a-uuid")

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_unknown_entity_type_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared resolver's naming ValueError must not escape as a crash."""
    _install_lookup(monkeypatch, {})

    with pytest.raises(ValueError) as excinfo:
        _run(entity_type="no_such_entity", entity_id=str(uuid.uuid4()))
    assert "no_such_entity" in str(excinfo.value)
    assert "known types are" in str(excinfo.value)


def test_command_metadata_complete() -> None:
    metadata = ReferenceInspectCommand.metadata()
    assert metadata["name"] == "reference_inspect"
    assert metadata["version"] == "1.0.0"
    assert metadata["category"] == "entity"
    assert {"entity_type", "entity_id", "recursive", "depth_limit", "limit", "offset"} <= set(
        metadata["parameters"]
    )
    assert set(metadata["error_cases"]) == {"RUNTIME_VALIDATION_ERROR", "INVALID_PAGINATION"}
    for code, case in metadata["error_cases"].items():
        assert "description" in case and "solution" in case, f"{code} breaks the error_cases shape"
    assert metadata["best_practices"]
    assert any("cycle" in practice for practice in metadata["best_practices"])


def test_schema_declares_the_entity_type_enum_and_pagination() -> None:
    schema = ReferenceInspectCommand.get_schema()
    properties = schema["properties"]
    assert "plan" in properties["entity_type"]["enum"]
    assert "todo" in properties["entity_type"]["enum"]
    # The enum carries entity types, never table names.
    assert "todo_item" not in properties["entity_type"]["enum"]
    assert properties["depth_limit"]["maximum"] == MAX_DEPTH_LIMIT
    assert properties["depth_limit"]["default"] == DEFAULT_DEPTH_LIMIT
    assert properties["recursive"]["default"] is False
    assert {"limit", "offset"} <= set(properties)
    assert schema["required"] == ["entity_type", "entity_id"]
    assert schema["additionalProperties"] is False


def test_command_is_registered_read_only() -> None:
    assert "reference_inspect" in INVENTORY
    assert "reference_inspect" not in MUTATING, "reference_inspect is a read; it must not mutate"
