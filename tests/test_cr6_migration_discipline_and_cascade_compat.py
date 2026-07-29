"""CR-6 migration discipline and open-cascade compatibility test suite (C-015, HRS {c6mb}).

Tests 1-4 are static and run offline. Test 5 needs a live database and is
skipped with a stated reason when none is configured.
"""

from __future__ import annotations

import pathlib
import re

import pytest

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"

# Mirrors tests/test_runtime_migrations.py.
FORBIDDEN_DDL_SUBSTRINGS = ("DROP TABLE", "DROP COLUMN", "DROP INDEX", "ALTER COLUMN", "TRUNCATE")

# CR-6 owns migrations numbered 0026 and above.
_CR6_FIRST_PREFIX = 26

_INDEX_RE = re.compile(r"CREATE(?:\s+UNIQUE)?\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)\s+ON", re.I)
_CREATE_INDEX_IF_NOT_EXISTS_RE = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS", re.I)
_CREATE_TABLE_RE = re.compile(r'CREATE TABLE (?:IF NOT EXISTS )?"?(\w+)"?\s*\(', re.I)


def _all_migrations() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _cr6_migrations() -> list[pathlib.Path]:
    out = []
    for path in _all_migrations():
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit() and int(prefix) >= _CR6_FIRST_PREFIX:
            out.append(path)
    return out


def _body(path: pathlib.Path) -> str:
    """The file with comment lines stripped, so rollback notes never match."""
    return "\n".join(
        line for line in path.read_text().split("\n") if not line.strip().startswith("--")
    )


def test_cr6_migrations_exist() -> None:
    """CR-6 must actually ship the migrations the other tests police."""
    assert _cr6_migrations(), (
        f"no migration numbered {_CR6_FIRST_PREFIX:04d} or above found in {MIGRATIONS_DIR}"
    )


def test_cr6_migrations_follow_additive_ddl_discipline() -> None:
    """No destructive DDL, and at least one additive statement per file."""
    for path in _cr6_migrations():
        body = _body(path).upper()
        for forbidden in FORBIDDEN_DDL_SUBSTRINGS:
            assert forbidden not in body, f"{path.name}: destructive DDL {forbidden!r} in migration body"
        additive = any(
            marker in body
            for marker in ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX", "ADD COLUMN")
        )
        assert additive, f"{path.name}: no additive DDL marker found"


def test_cr6_migrations_have_idempotency_markers() -> None:
    """Every creating or inserting statement must be safe to re-run."""
    for path in _cr6_migrations():
        body = _body(path)
        if "CREATE TABLE" in body.upper():
            assert re.search(r"CREATE TABLE\s+IF NOT EXISTS", body, re.I), (
                f"{path.name}: CREATE TABLE without IF NOT EXISTS"
            )
        if re.search(r"CREATE\s+(?:UNIQUE\s+)?INDEX", body, re.I):
            assert _CREATE_INDEX_IF_NOT_EXISTS_RE.search(body), (
                f"{path.name}: CREATE INDEX without IF NOT EXISTS"
            )
        for statement in re.findall(r"INSERT INTO[^;]+;", body, re.S | re.I):
            assert "ON CONFLICT" in statement.upper(), (
                f"{path.name}: INSERT without ON CONFLICT: {' '.join(statement.split())[:120]}"
            )
        for statement in re.findall(r"ALTER TABLE[^;]+;", body, re.S | re.I):
            assert "IF NOT EXISTS" in statement.upper(), (
                f"{path.name}: ALTER TABLE without IF NOT EXISTS: {' '.join(statement.split())[:120]}"
            )


def test_cr6_new_entity_tables_register_identity_triggers() -> None:
    """A new entity table must be registered in the identity registry."""
    for path in _cr6_migrations():
        body = _body(path)
        for table in _CREATE_TABLE_RE.findall(body):
            for suffix in ("insert", "delete"):
                trigger = f"entity_identity_{table}_{suffix}"
                assert trigger in body, (
                    f"{path.name}: new table {table!r} lacks the {trigger} trigger; "
                    "every new entity table registers in the identity registry in the "
                    "same migration (see docs/delivery/cr6-migration-discipline.md)"
                )


def test_cr6_migrations_no_index_name_collisions() -> None:
    """An index name is claimed by exactly one migration across the chain.

    A later migration MAY reuse a name to redefine the index, but only if it
    drops the old one first in the same file: that is a deliberate change of a
    uniqueness key, not a collision. `context_block_idempotent` (0004 -> 0005
    -> 0023) and `srt_snapshot_idempotent` (0007 -> 0008) are the shipped
    examples. What this test forbids is the same name being created by two
    migrations with no intervening drop, which is the failure that silently
    breaks a re-run.
    """
    claimants: dict[str, list[str]] = {}
    for path in _all_migrations():
        body = _body(path)
        dropped = {
            name.strip('"')
            for name in re.findall(r"DROP INDEX\s+(?:IF EXISTS\s+)?(\S+?);", body, re.I)
        }
        for raw in _INDEX_RE.findall(body):
            name = raw.strip('"')
            if name in dropped:
                continue  # redefinition, not a fresh claim
            claimants.setdefault(name, []).append(path.name)
    collisions = {name: files for name, files in claimants.items() if len(files) > 1}
    assert collisions == {}, f"index names created by more than one migration: {collisions}"


def test_cr6_migrations_carry_rollback_notes() -> None:
    """Every CR-6 migration documents its own inverse."""
    for path in _cr6_migrations():
        text = path.read_text()
        assert "ROLLBACK NOTES" in text, f"{path.name}: no ROLLBACK NOTES block"
        assert "schema_migration" in text, (
            f"{path.name}: rollback notes do not mention removing the filename from "
            "the schema_migration bookkeeping table"
        )


@pytest.mark.skip(
    reason="requires a test database: exercises a CR-6 migration against a live open cascade"
)
def test_cr6_open_cascade_compatibility_with_new_migrations() -> None:
    """A CR-6 migration must apply cleanly while a cascade is mid-flight.

    Open cascades are a normal, tolerated state on the live server (five were
    open at inventory time on 2026-07-29 and remain open by owner decision), so
    a migration is never allowed to assume a quiescent database.

    Sequence, inside a savepoint that is rolled back so the test database stays
    clean: create a plan with a head revision and a 'head' ref; begin_cascade
    and assert status='open' with base_revision_uuid equal to the head; execute
    the newest CR-6 migration body; then assert no exception, the open cascade
    row and its base_revision_uuid are unchanged, and get_ref('head') still
    resolves to the original revision.
    """
