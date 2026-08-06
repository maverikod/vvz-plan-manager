"""CR-7 G-006/T-001/A-001: the set-wise hard-delete engine.

Fake psycopg connections and monkeypatched collaborators throughout -- no live
database. resolve_entity_identities_batch and referrers_of are monkeypatched at
their source modules (both are imported locally, inside the function body, by
runtime_hard_delete, so a source-module patch is picked up on every call).
Marked/unmarked status is controlled by monkeypatching each entity class's own
crud_get, matching the convention tests/test_hard_delete_guard.py already uses
for the same module's six single-row wrappers.

Covers the reversal the frozen step mandates: a fixed point of MARKED referrers
is swept in automatically (even when the caller never named them), while any
UNMARKED referrer left outside the closed set refuses the WHOLE operation
before a single row is touched -- the opposite of the shipped report-one-and-
continue purge (entity.purge_soft_deleted_batch), which only ever looks at live
referrers and can leave a marked-but-unlisted referrer dangling forever.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

import plan_manager.storage.identity as identity_module
import plan_manager.storage.relation_index_store as relation_index_module
import plan_manager.storage.runtime_hard_delete as rhd
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.entity import EntityNotSoftDeletedError, EntityReferencedError
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.storage.errors import NotFoundError


class _Column:
    """Stand-in for a psycopg column description entry."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]], columns: tuple[str, ...] = ()) -> None:
        self._rows = list(rows)
        self.description = tuple(_Column(name) for name in columns) or None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Records every statement; answers table-scoped SELECTs from a row map."""

    def __init__(self, rows_by_table: dict[str, list[tuple[Any, ...]]] | None = None) -> None:
        self.rows_by_table = rows_by_table or {}
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append((text, list(params) if params is not None else []))
        for table, rows in self.rows_by_table.items():
            if f'"{table}"' in text or f" {table} " in f" {text} ":
                return _FakeCursor(rows)
        return _FakeCursor([])

    @property
    def deletes(self) -> list[tuple[str, list[Any]]]:
        return [(text, params) for text, params in self.statements if text.strip().startswith("DELETE")]


def _identity_resolver(entity_types: dict[uuid.UUID, str]):
    """Fake resolve_entity_identities_batch keyed by a caller-supplied id->entity_type map."""

    def _resolve(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        return {
            entity_id: {
                "id": entity_id,
                "table_name": "irrelevant",
                "entity_type": entity_types[entity_id],
                "created_at": None,
            }
            for entity_id in ids
            if entity_id in entity_types
        }

    return _resolve


def _triple_referrer(triples: list[dict[str, Any]]):
    """Fake referrers_of: every stored triple whose target is in the probed set."""

    def _referrers_of(conn: Any, target_refs: Any) -> list[dict[str, Any]]:
        targets = set(target_refs)
        return [triple for triple in triples if triple["target_ref"] in targets]

    return _referrers_of


def _marked_get_by_id(marked_ids: set[uuid.UUID]):
    """crud_get replacement: reports SOFT_DELETE_COLUMN set iff the id is in marked_ids."""

    def _get(cls: type, conn: Any, entity_id: Any, **kwargs: Any) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc) if entity_id in marked_ids else None
        return {"uuid": entity_id, cls.SOFT_DELETE_COLUMN: stamp}

    return classmethod(_get)


def _hard_delete_recorder(calls: list[tuple[type, uuid.UUID, dict[str, Any]]]):
    def _crud_hard_delete(cls: type, conn: Any, entity_id: Any, **kwargs: Any) -> None:
        calls.append((cls, entity_id, kwargs))
        return None

    return classmethod(_crud_hard_delete)


# ---------------------------------------------------------------------------
# Fixed-point expansion.
# ---------------------------------------------------------------------------


def test_fixed_point_sweeps_in_a_marked_referrer_absent_from_the_explicit_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A marked referrer never named by the caller is still swept in and removed.

    This is the exact bug the frozen step reverses: the shipped purge's
    live-referrer-only lookup would let the explicit target (todo_uuid) go
    while leaving the marked-but-unlisted comment dangling. Here the comment
    is discovered through the relation index and folded into the set instead
    of being silently skipped or -- the other acceptable outcome the step
    names -- causing a refusal; nothing about "absent from the explicit list"
    exempts a marked referrer from being removed in the same pass as its
    target.
    """
    todo_uuid = uuid.uuid4()
    comment_uuid = uuid.uuid4()
    triples = [
        {"source_ref": comment_uuid, "target_ref": todo_uuid, "field_ref": uuid.uuid4()},
    ]

    monkeypatch.setattr(
        identity_module,
        "resolve_entity_identities_batch",
        _identity_resolver({todo_uuid: "todo", comment_uuid: "comment"}),
    )
    monkeypatch.setattr(relation_index_module, "referrers_of", _triple_referrer(triples))
    monkeypatch.setattr(TodoItem, "crud_get", _marked_get_by_id({todo_uuid, comment_uuid}))
    monkeypatch.setattr(RuntimeComment, "crud_get", _marked_get_by_id({todo_uuid, comment_uuid}))

    calls: list[tuple[type, uuid.UUID, dict[str, Any]]] = []
    monkeypatch.setattr(TodoItem, "crud_hard_delete", _hard_delete_recorder(calls))
    monkeypatch.setattr(RuntimeComment, "crud_hard_delete", _hard_delete_recorder(calls))

    conn = _FakeConn()
    result = rhd.hard_delete_marked_set(conn, [todo_uuid], changed_by="tester")

    # Both entities removed, the referrer (comment) strictly before its target
    # (todo), even though only the todo was named explicitly.
    assert result["removed"] == [comment_uuid, todo_uuid]
    assert [entity_id for _cls, entity_id, _kw in calls] == [comment_uuid, todo_uuid]
    assert all(kw["changed_by"] == "tester" for _cls, _eid, kw in calls)

    # Exactly one relation-index cleanup, covering both removed ids.
    assert len(conn.deletes) == 1
    delete_text, delete_params = conn.deletes[0]
    assert "relation_index" in delete_text
    assert set(delete_params[0]) == {todo_uuid, comment_uuid}
    assert set(delete_params[1]) == {todo_uuid, comment_uuid}


# ---------------------------------------------------------------------------
# Whole-operation refusal.
# ---------------------------------------------------------------------------


def test_external_unmarked_referrer_refuses_the_whole_set_and_removes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    todo_uuid = uuid.uuid4()
    live_bug_uuid = uuid.uuid4()
    triples = [
        {"source_ref": live_bug_uuid, "target_ref": todo_uuid, "field_ref": uuid.uuid4()},
    ]

    monkeypatch.setattr(
        identity_module,
        "resolve_entity_identities_batch",
        _identity_resolver({todo_uuid: "todo", live_bug_uuid: "bug"}),
    )
    monkeypatch.setattr(relation_index_module, "referrers_of", _triple_referrer(triples))
    monkeypatch.setattr(TodoItem, "crud_get", _marked_get_by_id({todo_uuid}))
    # live_bug_uuid is NOT marked: BugReport.crud_get reports no soft-delete stamp.
    monkeypatch.setattr(BugReport, "crud_get", _marked_get_by_id(set()))

    calls: list[tuple[type, uuid.UUID, dict[str, Any]]] = []
    monkeypatch.setattr(TodoItem, "crud_hard_delete", _hard_delete_recorder(calls))
    monkeypatch.setattr(BugReport, "crud_hard_delete", _hard_delete_recorder(calls))

    conn = _FakeConn()

    with pytest.raises(EntityReferencedError) as excinfo:
        rhd.hard_delete_marked_set(conn, [todo_uuid], changed_by="tester")

    assert [referrer["referrer_id"] for referrer in excinfo.value.referrers] == [live_bug_uuid]
    assert calls == [], "a refused whole-set operation must remove nothing"
    assert conn.deletes == [], "a refusal must never reach the relation-index cleanup"


def test_explicit_starting_entity_that_is_not_marked_refuses_before_any_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_todo_uuid = uuid.uuid4()
    lookups: list[Any] = []

    monkeypatch.setattr(
        identity_module,
        "resolve_entity_identities_batch",
        _identity_resolver({live_todo_uuid: "todo"}),
    )

    def _referrers_of_spy(conn: Any, target_refs: Any) -> list[dict[str, Any]]:
        lookups.append(set(target_refs))
        return []

    monkeypatch.setattr(relation_index_module, "referrers_of", _referrers_of_spy)
    # Not marked: crud_get reports no soft-delete stamp for this id.
    monkeypatch.setattr(TodoItem, "crud_get", _marked_get_by_id(set()))

    calls: list[tuple[type, uuid.UUID, dict[str, Any]]] = []
    monkeypatch.setattr(TodoItem, "crud_hard_delete", _hard_delete_recorder(calls))

    conn = _FakeConn()
    with pytest.raises(EntityNotSoftDeletedError):
        rhd.hard_delete_marked_set(conn, [live_todo_uuid], changed_by="tester")

    assert lookups == [], "an unmarked explicit start must refuse before any referrer lookup"
    assert calls == []
    assert conn.deletes == []


def test_explicit_starting_entity_not_in_the_identity_registry_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown_uuid = uuid.uuid4()
    monkeypatch.setattr(identity_module, "resolve_entity_identities_batch", _identity_resolver({}))

    with pytest.raises(NotFoundError):
        rhd.hard_delete_marked_set(_FakeConn(), [unknown_uuid], changed_by="tester")


# ---------------------------------------------------------------------------
# Default starting set (entity_ids=None).
# ---------------------------------------------------------------------------


def test_default_starting_set_is_every_currently_marked_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marked_uuid = uuid.uuid4()
    monkeypatch.setattr(rhd, "_all_marked_entities", lambda conn: {marked_uuid: TodoItem})
    monkeypatch.setattr(relation_index_module, "referrers_of", _triple_referrer([]))

    calls: list[tuple[type, uuid.UUID, dict[str, Any]]] = []
    monkeypatch.setattr(TodoItem, "crud_hard_delete", _hard_delete_recorder(calls))

    conn = _FakeConn()
    result = rhd.hard_delete_marked_set(conn, changed_by="sweeper")

    assert result["removed"] == [marked_uuid]
    assert calls == [(TodoItem, marked_uuid, {
        "returning": False, "require_soft_deleted": True, "changed_by": "sweeper",
    })]


def test_all_marked_entities_scans_only_purge_capable_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit coverage of the default-set query builder against a table-keyed fake conn."""
    marked_todo = uuid.uuid4()
    marked_bug = uuid.uuid4()
    monkeypatch.setattr(rhd, "_purge_capable_single_uuid_classes", lambda: [TodoItem, BugReport])
    conn = _FakeConn(rows_by_table={"todo_item": [(marked_todo,)], "bug_report": [(marked_bug,)]})

    marked = rhd._all_marked_entities(conn)

    assert marked == {marked_todo: TodoItem, marked_bug: BugReport}
    # Read-only: two SELECTs, never a write, so this helper is never in scope
    # for the cr7-no-out-of-mechanism-write scan (which watches INSERT/DELETE).
    assert all(text.strip().startswith("SELECT") for text, _ in conn.statements)


# ---------------------------------------------------------------------------
# Atomic row + relation-index removal.
# ---------------------------------------------------------------------------


def test_removal_is_one_atomic_pass_entities_then_relation_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity rows (via crud_hard_delete, which owns registry unregistration) are all
    removed before the single relation-index cleanup runs, on the SAME connection --
    i.e. inside whatever transaction the caller is holding open, never split across
    connections or committed separately.
    """
    todo_uuid = uuid.uuid4()
    comment_uuid = uuid.uuid4()
    triples = [
        {"source_ref": comment_uuid, "target_ref": todo_uuid, "field_ref": uuid.uuid4()},
    ]
    monkeypatch.setattr(
        identity_module,
        "resolve_entity_identities_batch",
        _identity_resolver({todo_uuid: "todo", comment_uuid: "comment"}),
    )
    monkeypatch.setattr(relation_index_module, "referrers_of", _triple_referrer(triples))
    monkeypatch.setattr(TodoItem, "crud_get", _marked_get_by_id({todo_uuid, comment_uuid}))
    monkeypatch.setattr(RuntimeComment, "crud_get", _marked_get_by_id({todo_uuid, comment_uuid}))

    sequence: list[str] = []

    def _record_todo(cls: type, conn: Any, entity_id: Any, **kwargs: Any) -> None:
        sequence.append(f"delete:{entity_id}")

    monkeypatch.setattr(TodoItem, "crud_hard_delete", classmethod(_record_todo))
    monkeypatch.setattr(RuntimeComment, "crud_hard_delete", classmethod(_record_todo))

    class _SequencingConn(_FakeConn):
        def execute(self, query: Any, params: Any = None) -> _FakeCursor:
            text = query if isinstance(query, str) else (
                query.as_string(None) if hasattr(query, "as_string") else str(query)
            )
            if text.strip().startswith("DELETE FROM relation_index"):
                sequence.append("relation_index_cleanup")
            return super().execute(query, params)

    conn = _SequencingConn()
    result = rhd.hard_delete_marked_set(conn, [todo_uuid], changed_by="tester")

    assert sequence == [f"delete:{comment_uuid}", f"delete:{todo_uuid}", "relation_index_cleanup"]
    assert set(result["removed"]) == {todo_uuid, comment_uuid}


# ---------------------------------------------------------------------------
# Topological removal order helper, isolated.
# ---------------------------------------------------------------------------


def test_topological_removal_order_puts_referrers_before_their_targets() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # c -> b -> a  (c refers to b, b refers to a): must delete c, then b, then a.
    edges = [
        {"source_ref": c, "target_ref": b},
        {"source_ref": b, "target_ref": a},
    ]
    order = rhd._topological_removal_order({a, b, c}, edges)
    assert order == [c, b, a]


def test_topological_removal_order_falls_back_deterministically_on_a_cycle() -> None:
    x, y = uuid.uuid4(), uuid.uuid4()
    edges = [
        {"source_ref": x, "target_ref": y},
        {"source_ref": y, "target_ref": x},
    ]
    order = rhd._topological_removal_order({x, y}, edges)
    assert set(order) == {x, y}
    assert len(order) == 2
    # Deterministic (sorted by string form), not incidental dict/set ordering.
    assert order == sorted([x, y], key=str)
