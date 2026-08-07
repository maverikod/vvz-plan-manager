"""Regression tests for bug c315ff84 (major, confirmed).

guarded_hard_delete used to forward its raw entity_id verbatim into
lookup_referrers' catalog probes. Two failure shapes:

(1) A composite ID_COLUMNS identity (e.g. Concept's {plan_uuid, concept_id})
    cannot bind as a single SQL parameter -- a mapping reaches psycopg and it
    raises on live PG.
(2) A scoped catalog key (a blocking CatalogEntry whose target_column is not
    "uuid", e.g. relation.from_concept/to_concept and step.concepts, which key
    on concept_id) probed with a row uuid matches NOTHING, so the guard
    silently reports no referrers and a referenced entity is deleted without
    refusal.

The fix (plan_manager/storage/hard_delete_guard.py): lookup_referrers now
resolves, per catalog entry, the scalar to probe with via the entry's own
target_column -- a bare scalar identity is still forwarded unchanged (the
pre-fix, uuid-keyed behaviour, which must not regress: reference_catalog's
TARGET-COLUMN CAVEAT means a class's dataclass field name legitimately
differs from the catalog's declared target_column), while a mapping identity
picks the component named by target_column. guarded_hard_delete also grew an
explicit ``probe_id`` override, for a deletion seat whose own identity (e.g.
concept_store._ConceptRowByUuid's uuid) is not what the catalog keys its
blocking entries by at all.

Fake psycopg connections throughout -- no live database. SQL is rendered with
sql.as_string(None) (falling back to str) so probe-level assertions can
inspect exactly what the guard emitted, per the bug's test guidance: fakes
cannot enforce NOT NULL/FK, so the load-bearing checks are on the SQL/params
the guard composed, not on a live constraint firing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.concept import Concept
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


class _FakeConn:
    """Records every rendered statement and its params; answers by SOURCE table.

    ``rows_by_table`` is keyed on the referring (source) table name, exactly
    like test_hard_delete_guard.py's fake, so a test names only the probe
    that should come back non-empty.
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
    def all_params(self) -> list[Any]:
        return [param for _, params in self.statements for param in params]


@pytest.fixture()
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    def _record(conn: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(runtime_audit_store, "record_runtime_change", _record)
    return recorded


@pytest.fixture()
def unregistered(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    from plan_manager.domain import entity as entity_module

    recorded: list[uuid.UUID] = []
    monkeypatch.setattr(
        entity_module,
        "unregister_entity_identity",
        lambda conn, entity_id: recorded.append(entity_id),
    )
    return recorded


# ---------------------------------------------------------------------------
# (a) composite-identity delete probes the catalog with the scoped key and
#     refuses when a referrer exists.
# ---------------------------------------------------------------------------


def test_composite_identity_probes_relation_with_concept_id_not_the_mapping(
    audit_calls: list[dict[str, Any]],
) -> None:
    """Concept's own {plan_uuid, concept_id} identity, passed straight in.

    Before the fix this raised inside lookup_referrers' param list (a dict
    cannot bind); now each blocking entry is probed with the identity
    component its own target_column names -- here concept_id, since every
    catalog entry targeting "concept" declares target_column="concept_id".
    """
    plan_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    conn = _FakeConn({"relation": [(referrer_uuid,)]})

    with pytest.raises(EntityReferencedError) as excinfo:
        guarded_hard_delete(
            conn,
            Concept,
            {"plan_uuid": plan_uuid, "concept_id": "C-001"},
            require_soft_deleted=False,
        )

    assert excinfo.value.referrers, "a live relation row must block the deletion"
    assert all(ref["table"] == "relation" for ref in excinfo.value.referrers)
    # The load-bearing claim: no probe ever tried to bind the identity mapping
    # itself, or the plan_uuid component, as the SQL parameter for a
    # concept_id-scoped column -- only the string concept_id was bound.
    assert "C-001" in conn.all_params
    assert not any(isinstance(param, dict) for param in conn.all_params), (
        "a mapping identity must never reach a SQL parameter list"
    )
    assert plan_uuid not in conn.all_params
    assert conn.statements and not any(
        text.startswith("DELETE") for text, _ in conn.statements
    ), "a refusal must not execute a DELETE"
    assert len(audit_calls) == 1
    assert audit_calls[0]["changed_fields"]["refused"] is True


def test_lookup_referrers_composite_identity_direct() -> None:
    """The read surface alone: lookup_referrers accepts a mapping identity."""
    plan_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    conn = _FakeConn({"relation": [(referrer_uuid,)]})

    referrers = lookup_referrers(conn, "concept", {"plan_uuid": plan_uuid, "concept_id": "C-001"})

    assert referrers
    assert all(ref["referrer_id"] == referrer_uuid for ref in referrers)


def test_composite_identity_missing_target_column_component_is_skipped() -> None:
    """A composite identity that cannot name the entry's target_column at all.

    len > 1 and "concept_id" is absent: there is nothing to bind, so the entry
    is skipped rather than probed with the wrong component or crashing.
    """
    conn = _FakeConn({"relation": [(uuid.uuid4(),)]})

    referrers = lookup_referrers(
        conn, "concept", {"plan_uuid": uuid.uuid4(), "unrelated_column": "z"}
    )

    assert referrers == []
    # It still tried -- every blocking entry for "concept" was considered --
    # it just found nothing it could probe with, not "never looked".
    assert conn.selects == []


def test_unreferenced_composite_identity_deletes_cleanly(
    audit_calls: list[dict[str, Any]],
) -> None:
    """No referrer: the composite-key DELETE still fires normally (unaffected)."""
    plan_uuid = uuid.uuid4()
    conn = _FakeConn(delete_row=("row",), delete_columns=("concept_id",))

    deleted = guarded_hard_delete(
        conn,
        Concept,
        {"plan_uuid": plan_uuid, "concept_id": "C-002"},
        require_soft_deleted=False,
    )

    assert deleted == {"concept_id": "row"}
    delete_statements = [text for text, _ in conn.statements if text.startswith("DELETE")]
    assert len(delete_statements) == 1
    assert "plan_uuid" in delete_statements[0] and "concept_id" in delete_statements[0]
    assert len(audit_calls) == 1
    assert "refused" not in audit_calls[0]["changed_fields"]


# ---------------------------------------------------------------------------
# (b) uuid-keyed entities behave exactly as before.
# ---------------------------------------------------------------------------


def test_uuid_keyed_scalar_identity_still_forwarded_unchanged(
    audit_calls: list[dict[str, Any]],
) -> None:
    """TodoItem: a bare scalar identity, unaffected by the composite-key fix."""
    todo_uuid = uuid.uuid4()
    attempt_uuid = uuid.uuid4()
    conn = _FakeConn({"execution_attempt": [(attempt_uuid,)]})

    with pytest.raises(EntityReferencedError) as excinfo:
        guarded_hard_delete(conn, TodoItem, todo_uuid, require_soft_deleted=False)

    assert excinfo.value.entity_id == todo_uuid
    assert excinfo.value.entity_type == "todo"
    assert todo_uuid in conn.all_params
    assert len(audit_calls) == 1


def test_uuid_keyed_identity_survives_dataclass_field_name_mismatch() -> None:
    """BugReport: reference_catalog's TARGET-COLUMN CAVEAT class.

    bug_report's real DB column is "uuid" (every catalog entry targeting it
    says target_column="uuid"), independent of the dataclass field name
    (bug_uuid). A scalar identity is forwarded regardless of that name, so
    this must keep matching after the fix exactly as it did before it.
    """
    bug_uuid = uuid.uuid4()
    dup_uuid = uuid.uuid4()
    conn = _FakeConn({"bug_report": [(dup_uuid,)]})

    referrers = lookup_referrers(conn, "bug_report", bug_uuid)

    assert referrers
    assert bug_uuid in conn.all_params


def test_uuid_keyed_unreferenced_delete_and_audit_unchanged(
    audit_calls: list[dict[str, Any]], unregistered: list[uuid.UUID]
) -> None:
    todo_uuid = uuid.uuid4()
    conn = _FakeConn(delete_row=(todo_uuid,), delete_columns=("uuid",))

    deleted = guarded_hard_delete(conn, TodoItem, todo_uuid, require_soft_deleted=False)

    assert deleted == {"uuid": todo_uuid}
    assert unregistered == [todo_uuid]
    assert len(audit_calls) == 1
    assert "refused" not in audit_calls[0]["changed_fields"]


# ---------------------------------------------------------------------------
# (c) no silent pass: a referenced concept-like entity is refused through the
#     guard's own path (not a caller-side pre-check).
# ---------------------------------------------------------------------------


def test_uuid_seat_without_probe_override_binds_the_wrong_key() -> None:
    """Documents the failure mode probe_id exists to close.

    _ConceptRowByUuid's own identity is a bare row uuid; every catalog entry
    blocking "concept" keys on concept_id. Absent an explicit probe_id the
    guard has no way to learn the row's concept_id, so it has no choice but
    to probe with the uuid it does have -- which never equals a real
    concept_id on a live database, so the probe would silently match nothing
    there (bug c315ff84 shape 2). This fake connection answers a probe by
    which TABLE it names, not by the bound value, so it cannot reproduce that
    silent mismatch; the assertion instead is on what gets bound: the row
    uuid reaches the parameter list in place of the concept_id the entry
    actually needs, which is exactly why concept_store.remove_concept always
    supplies probe_id explicitly.
    """
    row_uuid = uuid.uuid4()
    conn = _FakeConn({"relation": [(uuid.uuid4(),)]})

    lookup_referrers(conn, "concept", row_uuid)

    assert row_uuid in conn.all_params


def test_guarded_hard_delete_probe_id_closes_the_scoped_key_gap(
    audit_calls: list[dict[str, Any]],
) -> None:
    """The seat class plus an explicit probe_id: the guard's own path refuses.

    This is the mechanism concept_store.remove_concept now uses instead of a
    caller-side lookup_referrers pre-check: entity_id (row_uuid) drives the
    DELETE identity and audit id column; probe_id (concept_id) drives the
    catalog probe and is what EntityReferencedError reports.
    """
    row_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    conn = _FakeConn({"relation": [(referrer_uuid,)]})

    with pytest.raises(EntityReferencedError) as excinfo:
        guarded_hard_delete(
            conn,
            _ConceptRowByUuid,
            row_uuid,
            require_soft_deleted=False,
            audit_entity_type="concept",
            probe_id="C-003",
        )

    assert excinfo.value.entity_type == "concept"
    assert excinfo.value.entity_id == "C-003"
    assert "C-003" in conn.all_params
    assert row_uuid not in conn.all_params, "the probe must use concept_id, never the row uuid"
    assert not any(text.startswith("DELETE") for text, _ in conn.statements)
    assert len(audit_calls) == 1
    assert audit_calls[0]["changed_fields"]["id"] == "C-003"


class _ConceptIntegrationConn:
    """Answers by predicate on the rendered SQL text, in script order.

    Distinct from ``_FakeConn`` above: remove_concept's own two reads
    (get_concept, the row-uuid lookup) are plain, unquoted-identifier SQL
    strings against table "concept", while the guard's catalog probes are
    psycopg.sql-composed and render with quoted identifiers (e.g.
    ``FROM "relation"``) -- distinct enough prefixes that one script can
    answer both without the source-table keying ``_FakeConn`` uses.
    """

    def __init__(self, script: list[tuple[Any, list[tuple[Any, ...]]]]) -> None:
        self._script = list(script)
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append((text, list(params or [])))
        if text.startswith("DELETE"):
            return _FakeCursor([])
        for predicate, rows in self._script:
            if predicate(text):
                return _FakeCursor(rows)
        return _FakeCursor([])

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

    @property
    def all_params(self) -> list[Any]:
        return [param for _, params in self.statements for param in params]


def test_remove_concept_refuses_referenced_concept_through_the_guards_native_path(
    audit_calls: list[dict[str, Any]],
) -> None:
    """End to end (bug da06315d's scenario), now via guarded_hard_delete itself.

    concept_store.remove_concept no longer pre-checks lookup_referrers and
    raises by hand; it hands probe_id=concept_id to crud_hard_delete and lets
    the guard's own refusal (and refusal audit) fire. A referenced concept
    must still be refused, and no DELETE may reach the fake connection.
    """
    plan_uuid = uuid.uuid4()
    row_uuid = uuid.uuid4()
    referrer_uuid = uuid.uuid4()
    concept_row = ("C-004", "name", "definition", None, None)
    conn = _ConceptIntegrationConn(
        [
            (lambda t: t.startswith("SELECT concept_id"), [concept_row]),
            (lambda t: t.startswith("SELECT uuid FROM concept"), [(row_uuid,)]),
            (lambda t: t.startswith("SELECT uuid FROM") and '"relation"' in t, [(referrer_uuid,)]),
        ]
    )

    with pytest.raises(EntityReferencedError) as excinfo:
        remove_concept(conn, plan_uuid, "C-004")

    assert excinfo.value.entity_type == "concept"
    assert excinfo.value.entity_id == "C-004"
    assert "C-004" in conn.all_params
    assert row_uuid not in conn.all_params, "the probe must use concept_id, never the row uuid"
    assert not any(text.startswith("DELETE") for text, _ in conn.statements)
    # Bug c315ff84's guard rework makes the guard the single audited path even
    # for concept: a refusal now leaves exactly one audit row, where the old
    # caller-side pre-check left none.
    assert len(audit_calls) == 1
    assert audit_calls[0]["changed_fields"]["refused"] is True
