"""Central hard-delete guard regression suite (CR-6 G-004/T-002/A-004).

Fake psycopg connections throughout — no live database. The audit writer and the
identity unregistration are monkeypatched to recorders so the guard's own SQL is
the only SQL the fake connection ever sees.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from psycopg import sql

from plan_manager.domain import entity as entity_module
from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.entity import EntityReferencedError, hard_delete_entity
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.storage import hard_delete_guard, runtime_audit_store
from plan_manager.storage.hard_delete_guard import guarded_hard_delete, lookup_referrers
from plan_manager.storage.runtime_hard_delete import (
    hard_delete_bug,
    hard_delete_bug_fix,
    hard_delete_bug_fix_propagation,
    hard_delete_bug_impact,
    hard_delete_comment,
    hard_delete_todo,
)


class _Column:
    """Stand-in for a psycopg column description entry (_row_to_dict reads .name)."""

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
    """Records every statement and answers SELECTs from a per-table row map.

    ``rows_by_table`` is keyed on the REFERRING table name, so a test names the
    one table whose probe should come back non-empty and every other blocking
    probe answers empty.
    """

    def __init__(
        self,
        rows_by_table: dict[str, list[tuple[Any, ...]]] | None = None,
        *,
        delete_row: tuple[Any, ...] | None = None,
        delete_columns: tuple[str, ...] = (),
    ) -> None:
        self.rows_by_table = rows_by_table or {}
        self.delete_row = delete_row
        self.delete_columns = delete_columns
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append((text, list(params or [])))
        if text.startswith("DELETE"):
            row = self.delete_row
            return _FakeCursor([row] if row is not None else [], self.delete_columns)
        for table, rows in self.rows_by_table.items():
            if f'"{table}"' in text:
                return _FakeCursor(rows)
        return _FakeCursor([])

    @property
    def selects(self) -> list[str]:
        return [text for text, _ in self.statements if text.startswith("SELECT")]

    @property
    def deletes(self) -> list[str]:
        return [text for text, _ in self.statements if text.startswith("DELETE")]


@pytest.fixture()
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the single audit writer with a recorder."""
    recorded: list[dict[str, Any]] = []

    def _record(conn: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(runtime_audit_store, "record_runtime_change", _record)
    return recorded


@pytest.fixture()
def unregistered(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Silence identity unregistration so only the guard's own SQL is observed."""
    recorded: list[uuid.UUID] = []
    monkeypatch.setattr(
        entity_module,
        "unregister_entity_identity",
        lambda conn, entity_id: recorded.append(entity_id),
    )
    return recorded


def test_lookup_referrers_returns_list_of_dicts() -> None:
    plan_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    conn = _FakeConn({"todo_item": [(referrer_uuid,)]})

    referrers = lookup_referrers(conn, "plan", plan_uuid)

    assert referrers == [
        {
            "table": "todo_item",
            "column": "anchor_plan_uuid",
            "referrer_id": referrer_uuid,
            "referrer_kind": "todo_item",
        }
    ]
    # referrer_kind is the SOURCE table name, which is what a caller needs to
    # find the row again; the target's own table would name nothing new.
    assert referrers[0]["referrer_kind"] == "todo_item"


def test_lookup_referrers_empty_on_no_references() -> None:
    conn = _FakeConn()

    assert lookup_referrers(conn, "plan", uuid.uuid4()) == []
    # It still probed: an empty result must mean "asked and found nothing",
    # not "never looked".
    assert conn.selects, "the lookup issued no SELECT at all"


def test_guarded_hard_delete_refuses_with_referrer_list_and_writes_refusal_audit(
    audit_calls: list[dict[str, Any]],
) -> None:
    todo_uuid = uuid.uuid4()
    attempt_uuid = uuid.uuid4()
    conn = _FakeConn({"execution_attempt": [(attempt_uuid,)]})

    with pytest.raises(EntityReferencedError) as excinfo:
        guarded_hard_delete(conn, TodoItem, todo_uuid, require_soft_deleted=False)

    assert excinfo.value.referrers == [
        {
            "table": "execution_attempt",
            "column": "todo_uuid",
            "referrer_id": attempt_uuid,
            "referrer_kind": "execution_attempt",
        }
    ]
    assert len(audit_calls) == 1, "a refused deletion must leave exactly one audit row"
    assert audit_calls[0]["action"] == "hard_delete"
    changed_fields = audit_calls[0]["changed_fields"]
    assert changed_fields["refused"] is True
    assert changed_fields["referrers"][0]["table"] == "execution_attempt"
    assert conn.deletes == [], "a refusal must not execute a DELETE"


def test_guarded_hard_delete_succeeds_unreferenced_and_writes_hard_delete_audit(
    audit_calls: list[dict[str, Any]], unregistered: list[uuid.UUID]
) -> None:
    todo_uuid = uuid.uuid4()
    conn = _FakeConn(
        delete_row=(todo_uuid, "left over"), delete_columns=("uuid", "title")
    )

    deleted = guarded_hard_delete(
        conn, TodoItem, todo_uuid, require_soft_deleted=False, changed_by="tester"
    )

    assert deleted == {"uuid": todo_uuid, "title": "left over"}
    assert len(conn.deletes) == 1, "exactly one DELETE per successful removal"
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == "hard_delete"
    assert audit_calls[0]["changed_by"] == "tester"
    assert "refused" not in audit_calls[0]["changed_fields"]
    assert unregistered == [todo_uuid], "the identity mapping must be released"

    audit_calls.clear()
    silent_conn = _FakeConn(delete_row=(todo_uuid,), delete_columns=("uuid",))
    assert (
        guarded_hard_delete(
            silent_conn, TodoItem, todo_uuid, require_soft_deleted=False, returning=False
        )
        is None
    )
    # returning=False changes the projection, never the audit obligation.
    assert len(silent_conn.deletes) == 1
    assert "RETURNING" not in silent_conn.deletes[0]
    assert len(audit_calls) == 1


def test_lookup_and_delete_sql_are_distinct_statements(
    audit_calls: list[dict[str, Any]], unregistered: list[uuid.UUID]
) -> None:
    todo_uuid = uuid.uuid4()
    conn = _FakeConn(delete_row=(todo_uuid,), delete_columns=("uuid",))

    lookup_referrers(conn, "todo_item", todo_uuid)
    guarded_hard_delete(conn, TodoItem, todo_uuid, require_soft_deleted=False)

    assert conn.selects, "no SELECT was executed for the admission check"
    assert conn.deletes, "no DELETE was executed for the removal"
    # C-011's structural claim: the read that decides admission and the write
    # that performs the removal are separately composed statements, so the read
    # is reusable on its own.
    assert set(conn.selects).isdisjoint(conn.deletes)


def test_audit_payload_is_json_serializable(audit_calls: list[dict[str, Any]]) -> None:
    todo_uuid = uuid.uuid4()
    conn = _FakeConn({"execution_attempt": [(uuid.uuid4(),)]})

    with pytest.raises(EntityReferencedError):
        guarded_hard_delete(conn, TodoItem, todo_uuid, require_soft_deleted=False)

    # Load-bearing: record_runtime_change wraps changed_fields in Jsonb, which
    # cannot encode a uuid. An unconverted identifier raises inside the audit
    # store and turns a correct refusal into a crash.
    payload = audit_calls[0]["changed_fields"]
    assert json.loads(json.dumps(payload)) == payload
    assert payload["id"] == str(todo_uuid), "the entity id must be stringified"
    assert isinstance(payload["referrers"][0]["referrer_id"], str)


def test_entity_base_delegates_with_table_name_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The base forwards to the guard without composing any SQL of its own.

    Deviation from the step text, recorded deliberately: the guard takes the
    entity CLASS rather than a bare table name, because the soft-delete
    precondition, the RETURNING projection, the composite-key predicate and
    identity unregistration are all class-dependent. The invariant the step
    protects is preserved and asserted here — what identifies the table on the
    way to the guard is the plain TABLE_NAME string, never a composed
    sql.Identifier, which is what the catalog lookup needs.
    """
    recorded: list[dict[str, Any]] = []
    sentinel = {"uuid": "deleted-payload"}

    def _recorder(conn: Any, entity_cls: type, entity_id: Any, **kwargs: Any) -> Any:
        recorded.append({"entity_cls": entity_cls, "entity_id": entity_id, **kwargs})
        return sentinel

    monkeypatch.setattr(hard_delete_guard, "guarded_hard_delete", _recorder)

    todo_uuid = uuid.uuid4()
    result = hard_delete_entity(
        TodoItem,
        _FakeConn(),
        todo_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by="tester",
    )

    assert result is sentinel, "the base returns the guard's result unchanged"
    assert len(recorded) == 1
    call = recorded[0]
    assert call["entity_cls"] is TodoItem
    table = call["entity_cls"].TABLE_NAME
    assert table == "todo_item"
    assert isinstance(table, str)
    assert not isinstance(table, sql.Composable), (
        "a composed SQL object cannot be matched against the reference catalog"
    )
    assert call["returning"] is False
    assert call["require_soft_deleted"] is False
    assert call["changed_by"] == "tester"


_WRAPPERS = [
    (hard_delete_todo, TodoItem, "todo_uuid", {"anchor_plan_uuid": None}, "todo"),
    (
        hard_delete_comment,
        RuntimeComment,
        "comment_uuid",
        {"anchor_plan_uuid": None},
        "runtime_comment",
    ),
    (hard_delete_bug, BugReport, "bug_uuid", {"source_plan_uuid": None}, "bug_report"),
    (
        hard_delete_bug_impact,
        BugImpact,
        "impact_uuid",
        {"target_plan_uuid": None},
        "bug_impact",
    ),
    (hard_delete_bug_fix, BugFix, "fix_uuid", {}, "bug_fix"),
    (
        hard_delete_bug_fix_propagation,
        BugFixPropagation,
        "propagation_uuid",
        {"linked_plan_uuid": None},
        "bug_fix_propagation",
    ),
]


@pytest.mark.parametrize(
    ("wrapper", "entity_cls", "kwarg", "row_extra", "audit_entity_type"),
    _WRAPPERS,
    ids=[wrapper.__name__ for wrapper, *_ in _WRAPPERS],
)
def test_runtime_wrappers_audit_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    audit_calls: list[dict[str, Any]],
    unregistered: list[uuid.UUID],
    wrapper: Any,
    entity_cls: type,
    kwarg: str,
    row_extra: dict[str, Any],
    audit_entity_type: str,
) -> None:
    entity_id = uuid.uuid4()
    monkeypatch.setattr(
        entity_cls,
        "crud_get",
        classmethod(
            lambda cls, conn, probe, **kw: {"uuid": probe, **row_extra}
        ),
    )
    conn = _FakeConn()

    wrapper(conn, **{kwarg: entity_id}, changed_by="tester")

    # Two records would mean the wrapper kept its own audit write alongside the
    # guard's, and every removal would be double-counted in the audit trail.
    assert len(audit_calls) == 1, (
        f"{wrapper.__name__} produced {len(audit_calls)} audit rows for one deletion"
    )
    assert audit_calls[0]["action"] == "hard_delete"
    assert audit_calls[0]["changed_by"] == "tester", (
        "the actor the wrapper was given must reach the single record"
    )
    assert audit_calls[0]["entity_type"] == audit_entity_type
    assert audit_calls[0]["entity_id"] == entity_id


def test_lookup_referrers_rejects_nothing_but_matches_nothing_for_an_entity_type() -> None:
    """Control for the table-name-versus-entity-type trap (bugs e52daeab, 113a7888).

    Passing an entity type where a table name belongs returns an empty list,
    which reads as "nothing blocks this deletion" while the truth is the
    opposite. The guard therefore must always be handed TABLE_NAME.
    """
    conn = _FakeConn({"execution_attempt": [(uuid.uuid4(),)]})

    assert lookup_referrers(conn, "todo", uuid.uuid4()) == []
    assert lookup_referrers(conn, "todo_item", uuid.uuid4()), (
        "the real table name must find the referrer the entity type missed"
    )
