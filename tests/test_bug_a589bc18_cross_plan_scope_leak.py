"""Regression tests for bug a589bc18 (regression of fix c21f078 / bug c315ff84).

Live evidence: /root/smoke-0.1.102.log R44. guarded_hard_delete's scoped catalog
probe (relation.from_concept, relation.to_concept, step.concepts -- every entry
that declares ``scope_columns`` in reference_catalog.py) used to bind only an
``IS NOT NULL`` clause on the scope column, never an equality against the plan
being deleted from. Concept ids are plan-scoped ({plan_uuid, concept_id}), so a
concept_id like "C-001" reused by unrelated plans made the probe match every
plan's rows, not just the deleted concept's own plan -- the refusal direction
(a real same-plan referrer blocks) kept working, but the release direction
(zero referrers in THIS plan) was broken: concept_remove refused even when the
concept's own plan had no referrers at all, because rows in OTHER plans still
matched the same bare concept_id.

The fix (plan_manager/storage/hard_delete_guard.py): lookup_referrers grew an
optional ``scope`` mapping (e.g. ``{"plan_uuid": plan_uuid}``), keyed by the
CatalogEntry's own scope_columns component name. When the caller supplies a
value for a scoped entry's key, the entry's scope clause becomes an equality
bind instead of IS NOT NULL. guarded_hard_delete builds this mapping from the
``plan_uuid`` keyword it already threads through for the audit trail -- no
caller (concept_store.remove_concept included) had to change its call shape.
When no scope is supplied (scope=None, or the entry's key absent from it), the
old IS NOT NULL clause is kept unchanged, so callers with no scope to give
(e.g. the read-only reference-inspection command) and every catalog entry with
no scope_columns at all are unaffected.

Fake psycopg connections throughout -- no live database. SQL is rendered with
sql.as_string(None) (falling back to str) so probe-level assertions can inspect
exactly what the guard emitted, matching this bug's sibling suite
(test_bug_c315ff84_composite_scoped_probe.py).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from plan_manager.domain.concept_store import _ConceptRowByUuid, remove_concept
from plan_manager.domain.entity import EntityReferencedError
from plan_manager.domain.todo import TodoItem
from plan_manager.storage import runtime_audit_store
from plan_manager.storage.hard_delete_guard import guarded_hard_delete, lookup_referrers


class _Column:
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


class _PlanScopedFakeConn:
    """Answers a scoped catalog probe by actually respecting the plan filter.

    ``rows_by_table`` holds full row dicts per REFERRING table (relation,
    step, execution_attempt, ...), each carrying whichever columns the test
    cares about plus a "plan_uuid" column standing in for the referring row's
    own plan anchor. The probe/array match is always the first bound param;
    when the rendered SQL carries an equality clause on plan_uuid (the fix),
    the row's own plan_uuid must equal the last bound param; when it carries
    only IS NOT NULL (the pre-fix / unscoped shape), any non-null plan_uuid
    passes regardless of value -- reproducing the exact over-match this bug
    is about.
    """

    def __init__(self, rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
        self.rows_by_table = rows_by_table
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        params = list(params or [])
        self.statements.append((text, params))
        if text.startswith("DELETE"):
            return _FakeCursor([])
        for table, rows in self.rows_by_table.items():
            if f'"{table}"' not in text:
                continue
            matched = [
                (row["uuid"],) for row in rows if self._row_matches(text, params, row)
            ]
            return _FakeCursor(matched)
        return _FakeCursor([])

    @staticmethod
    def _row_matches(text: str, params: list[Any], row: dict[str, Any]) -> bool:
        idx = 0
        if "@>" in text:
            probe = params[idx]
            idx += 1
            if probe not in row.get("concepts", []):
                return False
        else:
            probe = params[idx]
            idx += 1
            if row.get("concept_id") != probe:
                return False
        if '"plan_uuid" = %s' in text:
            scope_value = params[idx]
            idx += 1
            if row.get("plan_uuid") != scope_value:
                return False
        elif '"plan_uuid" IS NOT NULL' in text:
            if row.get("plan_uuid") is None:
                return False
        return True

    @property
    def all_params(self) -> list[Any]:
        return [param for _, params in self.statements for param in params]


class _ConceptIntegrationConn(_PlanScopedFakeConn):
    """Adds remove_concept's own two plain-SQL reads on top of the scoped fake."""

    def __init__(
        self,
        rows_by_table: dict[str, list[dict[str, Any]]],
        *,
        concept_row: tuple[Any, ...],
        concept_row_uuid: uuid.UUID,
    ) -> None:
        super().__init__(rows_by_table)
        self._concept_row = concept_row
        self._concept_row_uuid = concept_row_uuid

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:  # type: ignore[override]
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        if text.startswith("SELECT concept_id"):
            self.statements.append((text, list(params or [])))
            return _FakeCursor([self._concept_row])
        if text.startswith("SELECT uuid FROM concept"):
            self.statements.append((text, list(params or [])))
            return _FakeCursor([(self._concept_row_uuid,)])
        return super().execute(query, params)

    def cursor(self) -> Any:
        conn = self

        class _Ctx:
            def __enter__(self) -> "_Ctx":
                return self

            def __exit__(self, *exc: Any) -> bool:
                return False

            def execute(self, sql: Any, params: Any = None) -> _FakeCursor:
                self._cur = conn.execute(sql, params)
                return self._cur

            def fetchone(self) -> tuple[Any, ...] | None:
                return self._cur.fetchone()

            def fetchall(self) -> list[tuple[Any, ...]]:
                return self._cur.fetchall()

        return _Ctx()


@pytest.fixture()
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    def _record(conn: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(runtime_audit_store, "record_runtime_change", _record)
    return recorded


@pytest.fixture()
def unregistered(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Stub out identity unregistration so a real (unrelated) DELETE never reaches
    the fake connections below. _ConceptRowByUuid.REGISTER_IDENTITY is True
    (inherited default), so every successful deletion in this suite would
    otherwise issue a second, untracked DELETE against entity_identity.
    """
    from plan_manager.domain import entity as entity_module

    recorded: list[uuid.UUID] = []
    monkeypatch.setattr(
        entity_module,
        "unregister_entity_identity",
        lambda conn, entity_id: recorded.append(entity_id),
    )
    return recorded


# ---------------------------------------------------------------------------
# (a) probe SQL/params now carry the plan scope for scoped entries.
# ---------------------------------------------------------------------------


def test_scoped_entry_binds_plan_uuid_equality_when_scope_supplied() -> None:
    """lookup_referrers(..., scope=...) renders an equality clause, not NOT NULL."""
    plan_uuid = uuid.uuid4()
    conn = _PlanScopedFakeConn({"relation": []})

    lookup_referrers(conn, "concept", "C-001", scope={"plan_uuid": plan_uuid})

    relation_statements = [text for text, _ in conn.statements if '"relation"' in text]
    assert relation_statements, "the relation.from_concept / relation.to_concept probes must fire"
    for text in relation_statements:
        assert '"plan_uuid" = %s' in text, text
        assert '"plan_uuid" IS NOT NULL' not in text, text
    assert plan_uuid in conn.all_params
    assert "C-001" in conn.all_params


def test_scoped_entry_keeps_is_not_null_when_no_scope_supplied() -> None:
    """No scope argument at all: the pre-fix clause shape is preserved exactly."""
    conn = _PlanScopedFakeConn({"relation": []})

    lookup_referrers(conn, "concept", "C-001")

    relation_statements = [text for text, _ in conn.statements if '"relation"' in text]
    assert relation_statements
    for text in relation_statements:
        assert '"plan_uuid" IS NOT NULL' in text, text
        assert '"plan_uuid" = %s' not in text, text


# ---------------------------------------------------------------------------
# (b)/(c) same-plan referrer still refuses; a foreign-plan row with the same
#     concept_id does NOT block.
# ---------------------------------------------------------------------------


def test_same_plan_referrer_still_refuses(audit_calls: list[dict[str, Any]]) -> None:
    plan_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    conn = _PlanScopedFakeConn(
        {
            "relation": [
                {"uuid": referrer_uuid, "concept_id": "C-001", "plan_uuid": plan_uuid},
            ]
        }
    )

    with pytest.raises(EntityReferencedError) as excinfo:
        guarded_hard_delete(
            conn,
            _ConceptRowByUuid,  # the real deletion seat: TABLE_NAME="concept"
            uuid.uuid4(),
            require_soft_deleted=False,
            plan_uuid=plan_uuid,
            audit_entity_type="concept",
            probe_id="C-001",
        )

    assert excinfo.value.referrers
    assert excinfo.value.referrers[0]["referrer_id"] == referrer_uuid
    assert len(audit_calls) == 1
    assert audit_calls[0]["changed_fields"]["refused"] is True


def test_foreign_plan_row_with_same_concept_id_does_not_block(
    audit_calls: list[dict[str, Any]],
) -> None:
    """The exact live-evidence shape (R44): only a DIFFERENT plan's row shares 'C-001'."""
    own_plan = uuid.uuid4()
    foreign_plan = uuid.uuid4()
    conn = _PlanScopedFakeConn(
        {
            "relation": [
                {"uuid": uuid.uuid4(), "concept_id": "C-001", "plan_uuid": foreign_plan},
            ]
        }
    )

    referrers = lookup_referrers(conn, "concept", "C-001", scope={"plan_uuid": own_plan})

    assert referrers == [], "a same-named concept_id in a DIFFERENT plan must not block"


def test_remove_concept_deletes_cleanly_when_only_a_foreign_plan_shares_the_id(
    audit_calls: list[dict[str, Any]], unregistered: list[uuid.UUID]
) -> None:
    """End to end through concept_store.remove_concept -- the bug's exact call path.

    A relation row exists that references concept_id "C-004", but it belongs to
    a DIFFERENT plan than the concept being removed. Before the fix this refused
    (bug a589bc18); after the fix the deletion proceeds.
    """
    own_plan = uuid.uuid4()
    foreign_plan = uuid.uuid4()
    row_uuid = uuid.uuid4()
    concept_row = ("C-004", "name", "definition", None, None)
    conn = _ConceptIntegrationConn(
        {
            "relation": [
                {"uuid": uuid.uuid4(), "concept_id": "C-004", "plan_uuid": foreign_plan},
            ]
        },
        concept_row=concept_row,
        concept_row_uuid=row_uuid,
    )

    deleted = remove_concept(conn, own_plan, "C-004")

    assert deleted.concept_id == "C-004"
    delete_statements = [text for text, _ in conn.statements if text.startswith("DELETE")]
    assert len(delete_statements) == 1
    assert len(audit_calls) == 1
    assert "refused" not in audit_calls[0]["changed_fields"]


def test_remove_concept_still_refuses_a_same_plan_referrer(
    audit_calls: list[dict[str, Any]],
) -> None:
    """Companion to the release-direction test: the refusal direction still works."""
    own_plan = uuid.uuid4()
    row_uuid = uuid.uuid4()
    concept_row = ("C-005", "name", "definition", None, None)
    conn = _ConceptIntegrationConn(
        {
            "relation": [
                {"uuid": uuid.uuid4(), "concept_id": "C-005", "plan_uuid": own_plan},
            ]
        },
        concept_row=concept_row,
        concept_row_uuid=row_uuid,
    )

    with pytest.raises(EntityReferencedError) as excinfo:
        remove_concept(conn, own_plan, "C-005")

    assert excinfo.value.entity_type == "concept"
    assert excinfo.value.entity_id == "C-005"
    assert not any(text.startswith("DELETE") for text, _ in conn.statements)
    assert len(audit_calls) == 1
    assert audit_calls[0]["changed_fields"]["refused"] is True


# ---------------------------------------------------------------------------
# (d) uuid-keyed path unchanged: no scope_columns on these entries, so the
#     scope argument (and the plan_uuid guarded_hard_delete derives it from)
#     changes nothing about the SQL these probes render.
# ---------------------------------------------------------------------------


def test_uuid_keyed_probe_unaffected_by_plan_uuid_scope(
    audit_calls: list[dict[str, Any]],
) -> None:
    todo_uuid = uuid.uuid4()
    attempt_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()

    class _TodoFakeConn(_PlanScopedFakeConn):
        def execute(self, query: Any, params: Any = None) -> _FakeCursor:  # type: ignore[override]
            text = query.as_string(None) if hasattr(query, "as_string") else str(query)
            self.statements.append((text, list(params or [])))
            if text.startswith("DELETE"):
                return _FakeCursor([])
            if '"execution_attempt"' in text:
                return _FakeCursor([(attempt_uuid,)])
            return _FakeCursor([])

    conn = _TodoFakeConn({})

    with pytest.raises(EntityReferencedError):
        guarded_hard_delete(
            conn,
            TodoItem,
            todo_uuid,
            require_soft_deleted=False,
            plan_uuid=plan_uuid,
        )

    # TodoItem's blocking entries carry no scope_columns at all, so passing
    # plan_uuid through (which now always builds a scope mapping) must not
    # introduce a plan_uuid equality/NOT NULL clause anywhere in these probes.
    assert not any("plan_uuid" in text for text, _ in conn.statements)
    assert todo_uuid in conn.all_params
    assert plan_uuid not in conn.all_params
