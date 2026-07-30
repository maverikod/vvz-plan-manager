"""id_resolve command and identity-fragment search suite.

Fakes only — no live database.

Origin: todo 558cd81a was reported as a non-existent identifier after a
project-scoped search came back empty across every list surface tried. It existed,
anchored to a plan whose primary project binding is unset, so transitive project
scope never reached it. These tests pin the property that makes the command answer
regardless of anchoring: it queries the registry, which is anchor-agnostic.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest

from plan_manager.commands import id_resolve_command as module
from plan_manager.commands.id_resolve_command import IdResolveCommand
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.storage.identity_search import (
    MIN_FRAGMENT_LENGTH,
    search_entity_identities,
)

_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
_TODO_ID = uuid.UUID("558cd81a-1286-4acf-b01a-0f43d941578f")


@contextmanager
def _fake_db():
    yield object()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)


def _run(**params: Any) -> Any:
    return asyncio.run(IdResolveCommand().execute(**params))


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeConn:
    """Answers the COUNT and the SELECT of the fragment search, recording both."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: str, params: Any = None) -> _FakeCursor:
        self.statements.append((query, list(params or [])))
        if "COUNT(*)" in query:
            return _FakeCursor([(len(self.rows),)])
        return _FakeCursor(self.rows)


def _row(entity_id: uuid.UUID = _TODO_ID, entity_type: str = "todo") -> tuple[Any, ...]:
    return (entity_id, "todo_item", entity_type, "entity", None, None, _NOW)


# ---------------------------------------------------------------- store layer


def test_search_matches_a_substring_not_only_a_prefix() -> None:
    conn = _FakeConn([_row()])

    matches, total = search_entity_identities(conn, "1286")

    assert total == 1
    assert matches[0]["id"] == _TODO_ID
    assert matches[0]["table_name"] == "todo_item"
    assert matches[0]["entity_type"] == "todo"
    # A LIKE pattern wrapped on BOTH sides is what makes a middle slice work.
    select = next(sql for sql, _ in conn.statements if "COUNT(*)" not in sql)
    assert "LIKE" in select
    pattern = next(p for sql, p in conn.statements if "COUNT(*)" not in sql)[0]
    assert pattern == "%1286%"


def test_search_lowercases_the_fragment() -> None:
    """UUID text is lower-case in Postgres; an upper-case fragment must still hit."""
    conn = _FakeConn([_row()])

    search_entity_identities(conn, "558CD81A")

    pattern = next(p for sql, p in conn.statements if "COUNT(*)" not in sql)[0]
    assert pattern == "%558cd81a%"


def test_search_filters_by_entity_type() -> None:
    conn = _FakeConn([_row()])

    search_entity_identities(conn, "558cd81a", entity_type="todo")

    select, params = next((s, p) for s, p in conn.statements if "COUNT(*)" not in s)
    assert "entity_type = %s" in select
    assert "todo" in params


def test_search_reports_the_total_separately_from_the_page() -> None:
    """total is what tells a caller a fragment is ambiguous."""
    conn = _FakeConn([_row(), _row(uuid.uuid4(), "bug")])

    matches, total = search_entity_identities(conn, "55", limit=1)

    assert total == 2
    assert len(matches) == 2  # the fake ignores LIMIT; the point is total is separate
    assert "LIMIT %s OFFSET %s" in next(
        sql for sql, _ in conn.statements if "COUNT(*)" not in sql
    )


@pytest.mark.parametrize("fragment", ["", "5", " "])
def test_search_refuses_a_fragment_that_is_too_short(fragment: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        search_entity_identities(_FakeConn([]), fragment)
    assert str(MIN_FRAGMENT_LENGTH) in str(excinfo.value)


@pytest.mark.parametrize("fragment", ["55%", "_558", "55'; DROP TABLE plan; --", "55 8c"])
def test_search_refuses_characters_no_uuid_contains(fragment: str) -> None:
    """Rejected, not escaped.

    A UUID has only hex digits and dashes, so anything else is a caller mistake
    worth reporting rather than a pattern worth running — and it keeps LIKE
    wildcards out of the pattern by construction.
    """
    with pytest.raises(ValueError) as excinfo:
        search_entity_identities(_FakeConn([]), fragment)
    assert "no UUID contains" in str(excinfo.value)


def test_search_accepts_a_dashed_fragment() -> None:
    conn = _FakeConn([_row()])
    matches, _ = search_entity_identities(conn, "558cd81a-1286")
    assert matches[0]["id"] == _TODO_ID


# ---------------------------------------------------------------- command layer


def _install(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], total: int) -> list[dict]:
    calls: list[dict] = []

    def _search(conn: Any, fragment: str, **kwargs: Any):
        calls.append({"fragment": fragment, **kwargs})
        return rows, total

    monkeypatch.setattr(module, "search_entity_identities", _search)
    monkeypatch.setattr(module, "_label_for", lambda conn, match: "a label")
    return calls


def _match(entity_id: uuid.UUID = _TODO_ID, entity_type: str = "todo") -> dict[str, Any]:
    return {
        "id": entity_id,
        "table_name": "todo_item",
        "entity_type": entity_type,
        "kind": "entity",
        "reserved_by": None,
        "note": None,
        "created_at": _NOW,
    }


def test_execute_resolves_a_prefix_to_the_full_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_match()], 1)

    result = _run(fragment="558cd81a")

    assert result.data["total"] == 1
    assert result.data["unique"] is True
    match = result.data["matches"][0]
    assert match["uuid"] == str(_TODO_ID)
    assert match["entity_type"] == "todo"
    assert match["table_name"] == "todo_item"
    assert match["label"] == "a label"
    assert match["created_at"] == _NOW.isoformat()


def test_execute_flags_an_ambiguous_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    """unique=False is the guard against feeding a wrong id to a destructive call."""
    _install(monkeypatch, [_match(), _match(uuid.uuid4(), "bug")], 2)

    result = _run(fragment="55")

    assert result.data["total"] == 2
    assert result.data["unique"] is False


def test_execute_reports_an_absent_identifier_as_an_empty_match_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty here is meaningful: the registry spans every entity, so nothing means absent."""
    _install(monkeypatch, [], 0)

    result = _run(fragment="deadbeef")

    assert result.data["matches"] == []
    assert result.data["total"] == 0
    assert result.data["unique"] is False


def test_execute_forwards_the_entity_type_and_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(monkeypatch, [_match()], 1)

    _run(fragment="558cd81a", entity_type="todo", limit=5, offset=10)

    assert calls == [{"fragment": "558cd81a", "entity_type": "todo", "limit": 5, "offset": 10}]


def test_execute_maps_a_bad_fragment_to_a_domain_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(conn: Any, fragment: str, **kwargs: Any):
        raise ValueError("identifier fragment carries characters no UUID contains: ['%']")

    monkeypatch.setattr(module, "search_entity_identities", _raise)

    result = _run(fragment="55%")

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_execute_rejects_bad_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [], 0)

    result = _run(fragment="558cd81a", limit=0)

    assert result.details["domain_code"] == "INVALID_PAGINATION"


def test_a_reservation_is_distinguishable_from_a_live_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserved = dict(_match(), kind="project_reservation", reserved_by="orchestrator",
                    entity_type=None, table_name=None)
    _install(monkeypatch, [reserved], 1)

    result = _run(fragment="558cd81a")

    match = result.data["matches"][0]
    assert match["kind"] == "project_reservation"
    assert match["reserved_by"] == "orchestrator"


# ---------------------------------------------------------------- label helper


def test_label_falls_back_to_none_rather_than_failing() -> None:
    """A label is a convenience; failing the whole lookup over one would be worse."""

    class _Exploding:
        COLUMNS = ("uuid", "title")

        @classmethod
        def get_by_id(cls, conn: Any, entity_id: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("unreadable")

    assert module._label_for(object(), {"entity_type": "no_such_entity", "id": _TODO_ID}) is None


def test_label_is_truncated() -> None:
    class _Long:
        COLUMNS = ("uuid", "title")

        @classmethod
        def get_by_id(cls, conn: Any, entity_id: Any, **kwargs: Any) -> dict[str, Any]:
            return {"title": "x" * 500}

    import plan_manager.commands.id_resolve_command as mod

    original = mod.resolve_entity_class
    try:
        mod.resolve_entity_class = lambda entity_type: _Long
        label = mod._label_for(object(), {"entity_type": "todo", "id": _TODO_ID})
    finally:
        mod.resolve_entity_class = original
    assert len(label) == module._LABEL_MAX
    assert label.endswith("…")


# ---------------------------------------------------------------- registration


def test_schema_and_registration() -> None:
    schema = IdResolveCommand.get_schema()
    assert schema["required"] == ["fragment"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["fragment"]["minLength"] == MIN_FRAGMENT_LENGTH
    assert "todo" in schema["properties"]["entity_type"]["enum"]
    assert "todo_item" not in schema["properties"]["entity_type"]["enum"]
    assert {"limit", "offset"} <= set(schema["properties"])

    assert "id_resolve" in INVENTORY
    assert "id_resolve" not in MUTATING, "id_resolve is a read; it must not mutate"


def test_metadata_shape() -> None:
    metadata = IdResolveCommand.metadata()
    assert metadata["name"] == "id_resolve"
    assert {"fragment", "entity_type", "limit", "offset"} <= set(metadata["parameters"])
    for code, case in metadata["error_cases"].items():
        assert "description" in case and "solution" in case, f"{code} breaks the shape"
    assert any("unique" in practice for practice in metadata["best_practices"]), (
        "the ambiguity guard must be documented"
    )
