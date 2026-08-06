"""Regression suite for the full-scope entity identity registry (CR-6 G-002).

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest

from plan_manager.storage.errors import DuplicateNameError, NotFoundError
from plan_manager.storage.identity import (
    ALLOWED_TABLES,
    ENTITY_KIND,
    EXCLUDED_TABLES,
    RESERVED_KIND,
    SCOPED_NAME_TABLES,
    ensure_identity_available,
    register_entity_identity,
    release_project_reservation,
    reserve_project_uuid,
    resolve_entity_identity,
)

_PLAN_TRUTH_TABLES = frozenset(
    {"plan", "paragraph", "concept", "relation", "step", "node_version", "revision", "ref"}
)

_MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"
_MIGRATION_0026 = _MIGRATIONS / "0026_identity_registry_full_scope.sql"


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Records every executed statement and replays scripted rows."""

    def __init__(self, rows=None):
        self.executed: list[tuple[str, tuple]] = []
        self._rows = list(rows or [])

    def execute(self, sql, params=()):
        self.executed.append((" ".join(str(sql).split()), tuple(params)))
        row = self._rows.pop(0) if self._rows else None
        return _FakeCursor(row)


def test_full_scope_table_partition_is_consistent() -> None:
    """ALLOWED_TABLES is the full scope; EXCLUDED_TABLES documents the rest."""
    assert isinstance(ALLOWED_TABLES, frozenset)
    assert ALLOWED_TABLES, "ALLOWED_TABLES must not be empty"
    # The historical eight stay in scope, but the set is now strictly wider.
    assert _PLAN_TRUTH_TABLES < ALLOWED_TABLES

    assert isinstance(EXCLUDED_TABLES, dict)
    for table, reason in EXCLUDED_TABLES.items():
        assert isinstance(reason, str) and reason.strip(), f"{table} carries no exclusion reason"

    assert not (ALLOWED_TABLES & set(EXCLUDED_TABLES)), "a table is both in scope and excluded"

    # Every table the migration chain creates lands in exactly one of the two
    # sets: a table in neither is an unclassified gap, not an exemption.
    created: set[str] = set()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        created |= set(re.findall(r'CREATE TABLE (?:IF NOT EXISTS )?"?(\w+)"?\s*\(', path.read_text()))
    created.discard("statement")  # prose in a comment, not a real table
    unclassified = created - ALLOWED_TABLES - set(EXCLUDED_TABLES)
    assert unclassified == set(), f"tables classified in neither set: {sorted(unclassified)}"


def test_scoped_name_allowlist_stays_narrow() -> None:
    """resolve_scoped_name's allowlist must not widen with the registry.

    Its query filters on plan_uuid, which the runtime-overlay and
    agent-configuration tables do not have.
    """
    assert SCOPED_NAME_TABLES == _PLAN_TRUTH_TABLES
    assert SCOPED_NAME_TABLES < ALLOWED_TABLES


def test_collision_raises_deterministic_error_and_writes_nothing() -> None:
    """A cross-kind collision is refused with an exact, actionable message."""
    entity_id = uuid.uuid4()
    conn = _FakeConn(rows=[(ENTITY_KIND, "plan")])

    with pytest.raises(DuplicateNameError) as excinfo:
        ensure_identity_available(conn, entity_id)

    assert str(excinfo.value) == (
        f"entity id already registered: {entity_id} (kind={ENTITY_KIND}, table=plan)"
    )
    # The guard only reads; it never writes a row of its own.
    assert len(conn.executed) == 1
    assert conn.executed[0][0].upper().startswith("SELECT")


def test_available_identifier_passes_the_guard() -> None:
    """A free identifier returns None rather than raising."""
    conn = _FakeConn(rows=[None])
    assert ensure_identity_available(conn, uuid.uuid4()) is None


def test_registration_is_idempotent_but_never_the_collision_guard() -> None:
    """register_entity_identity keeps ON CONFLICT DO NOTHING by design.

    That clause makes re-registration harmless; it is deliberately silent,
    which is exactly why ensure_identity_available exists separately.
    """
    conn = _FakeConn()
    register_entity_identity(
        conn, entity_id=uuid.uuid4(), table_name="plan", entity_type="plan"
    )
    statement = conn.executed[0][0]
    assert "INSERT INTO entity_identity" in statement
    assert "ON CONFLICT (id) DO NOTHING" in statement


def test_reservation_round_trip() -> None:
    """reserve -> collision -> release -> reserve again."""
    project_uuid = uuid.uuid4()

    # Free identifier: the guard's SELECT returns no row, then the INSERT runs.
    conn = _FakeConn(rows=[None, None])
    payload = reserve_project_uuid(conn, project_uuid, "agent-1", "new project")
    assert payload["kind"] == RESERVED_KIND
    assert payload["project_uuid"] == project_uuid
    assert payload["reserved_by"] == "agent-1"
    assert payload["note"] == "new project"
    assert any("INSERT INTO entity_identity" in stmt for stmt, _ in conn.executed)

    # Second reserve of the same identifier: the guard finds the reservation.
    conn = _FakeConn(rows=[(RESERVED_KIND, "")])
    with pytest.raises(DuplicateNameError) as excinfo:
        reserve_project_uuid(conn, project_uuid, "agent-2", None)
    assert f"kind={RESERVED_KIND}" in str(excinfo.value)
    assert not any("INSERT" in stmt for stmt, _ in conn.executed), "a refused reserve must not write"

    # Release frees it; the DELETE is scoped to the reservation kind.
    conn = _FakeConn(rows=[(project_uuid,)])
    release_project_reservation(conn, project_uuid)
    statement, params = conn.executed[0]
    assert statement.startswith("DELETE FROM entity_identity")
    assert RESERVED_KIND in params, "release must not be able to remove a live entity's identity"

    # Reserving again now succeeds.
    conn = _FakeConn(rows=[None, None])
    assert reserve_project_uuid(conn, project_uuid, "agent-1", None)["kind"] == RESERVED_KIND


def test_release_of_absent_reservation_raises_not_found() -> None:
    conn = _FakeConn(rows=[None])
    with pytest.raises(NotFoundError):
        release_project_reservation(conn, uuid.uuid4())


def test_resolve_reports_kind_and_reservation_fields() -> None:
    entity_id = uuid.uuid4()
    # Column order: id, table_name, entity_type, kind, reserved_by, note, created_at.
    conn = _FakeConn(
        rows=[(entity_id, "", RESERVED_KIND, RESERVED_KIND, "agent-1", "why", "2026-07-29")]
    )
    record = resolve_entity_identity(conn, entity_id)
    assert record["kind"] == RESERVED_KIND
    assert record["reserved_by"] == "agent-1"
    assert record["note"] == "why"

    conn = _FakeConn(rows=[None])
    with pytest.raises(NotFoundError):
        resolve_entity_identity(conn, uuid.uuid4())


def test_migration_0026_is_idempotent_and_additive() -> None:
    """The full-scope migration exists and follows the migration discipline."""
    assert _MIGRATION_0026.exists(), (
        f"expected the full-scope registry migration at {_MIGRATION_0026}"
    )
    text = _MIGRATION_0026.read_text()
    body = "\n".join(line for line in text.split("\n") if not line.strip().startswith("--"))

    sqlglot = pytest.importorskip("sqlglot")
    statements = [s for s in sqlglot.parse(body, dialect="postgres") if s]
    assert statements, "migration parsed to no statements"

    inserts = re.findall(r"^INSERT INTO entity_identity", body, re.M)
    assert inserts, "migration performs no backfill"
    assert len(inserts) == body.count("ON CONFLICT (id) DO NOTHING"), (
        "every backfill INSERT must carry ON CONFLICT (id) DO NOTHING"
    )

    backfilled = set(re.findall(r"SELECT uuid, '(\w+)',", body))
    # Tables introduced AFTER 0026 are backfilled by their own migrations
    # (CR-7 0028 seeds and wires enumeration/enumeration_value), so 0026's
    # backfill is compared against the in-scope set of its own era.
    post_0026_tables = frozenset({"enumeration", "enumeration_value"})
    expected_0026_scope = ALLOWED_TABLES - post_0026_tables
    assert backfilled == expected_0026_scope, (
        "backfill does not match the in-scope set; "
        f"missing={sorted(expected_0026_scope - backfilled)} "
        f"extra={sorted(backfilled - expected_0026_scope)}"
    )

    for alter in re.findall(r"^ALTER TABLE [^\n;]+;", body, re.M):
        assert "ADD COLUMN IF NOT EXISTS" in alter, f"non-additive ALTER: {alter}"
    for forbidden in ("DROP TABLE", "DROP COLUMN", "DROP INDEX", "TRUNCATE", "ALTER COLUMN"):
        assert forbidden not in body, f"destructive DDL in migration body: {forbidden}"

    created = re.findall(r"CREATE TRIGGER (entity_identity_\w+)", body)
    dropped = re.findall(r"DROP TRIGGER IF EXISTS (entity_identity_\w+)", body)
    assert sorted(created) == sorted(dropped), "trigger creation must be conditional (idempotent re-run)"

    assert f"RESERVED_KIND = '{RESERVED_KIND}'" in text
    assert "ROLLBACK NOTES" in text
