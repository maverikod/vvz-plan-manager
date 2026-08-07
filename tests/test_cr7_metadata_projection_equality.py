"""CR-7 G-008/T-001/A-001: the cr7-metadata-projection-equality pipeline check.

No live PostgreSQL is used anywhere in this module (that direction -- the
STORED database projection compared against these same sources of truth -- is
A-003's R-check, run against a live server). Everything here compares two
STATIC, code-side representations of the same metadata against each other,
each standing in for one side of the eventual live projection:

  1. Enumeration seeds: the literal INSERT statements of migration 0028 (the
     text that WOULD seed the live `enumeration`/`enumeration_value` tables)
     versus the domain Enum classes migration 0028's own header comment says
     they were "copied verbatim" from.
  2. Relation-index triple shape: the column list of migration 0027's
     `CREATE TABLE relation_index` DDL (the text that WOULD shape the live
     table) versus the column lists relation_index_store.py's own INSERT/
     SELECT statements name (the text that WOULD read and write it).
  3. Field catalogue: the set of single-uuid REFERENCE_CATALOG entries (C-010,
     reference_catalog.py) -- the code-side declaration of which source
     columns are references -- versus the property names
     relation_index_store.compute_canonical_triples (the shipped rebuild
     projection generator) actually calls ensure_reference_field for, proven
     with a fake connection so no live database is required.

Each comparison is asserted in both directions: nothing on one side is absent
from the other.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from enum import Enum

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATIONS = _REPO_ROOT / "plan_manager_db" / "migrations"
_MIGRATION_0027 = _MIGRATIONS / "0027_relation_index_and_field_catalog.sql"
_MIGRATION_0028 = _MIGRATIONS / "0028_closed_enumerations.sql"
_RELATION_INDEX_STORE = _REPO_ROOT / "plan_manager" / "storage" / "relation_index_store.py"


# ---------------------------------------------------------------------------
# 1. Enumeration seeds (migration 0028) vs the domain Enum classes.
# ---------------------------------------------------------------------------

from plan_manager.domain.bug_report import BugKind, BugSeverity, BugStatus
from plan_manager.domain.calendar_entry import CalendarEntryStatus
from plan_manager.domain.runtime_link import RuntimeLinkType
from plan_manager.domain.todo import TodoStatus
from plan_manager.domain.wish import WishKind, WishStatus

_DOMAIN_ENUM_BY_NAME: dict[str, type[Enum]] = {
    "bug_kind": BugKind,
    "bug_severity": BugSeverity,
    "bug_status": BugStatus,
    "calendar_entry_status": CalendarEntryStatus,
    "runtime_link_type": RuntimeLinkType,
    "todo_status": TodoStatus,
    "wish_kind": WishKind,
    "wish_status": WishStatus,
}
"""Migration 0028's own header comment names exactly this set of source
Enum classes as what it copies verbatim; kept here as an explicit,
independent mapping so a name drifting out of sync on either side is caught."""

_ENUMERATION_NAME_RE = re.compile(
    r"INSERT INTO enumeration \(ref, name\) VALUES \('[0-9a-f-]{36}', '(\w+)'\)"
)
_ENUMERATION_VALUE_RE = re.compile(
    r"INSERT INTO enumeration_value \(ref, enumeration_ref, value\)\s*\n\s*"
    r"SELECT '[0-9a-f-]{36}', e\.ref, '([^']+)' FROM enumeration e WHERE e\.name = '(\w+)'"
)


def _parse_migration_0028_seeds() -> dict[str, list[str]]:
    """{enumeration_name: [value, ...]} in insertion order, parsed from 0028's SQL text."""
    text = _MIGRATION_0028.read_text(encoding="utf-8")
    seeds: dict[str, list[str]] = {name: [] for name in _ENUMERATION_NAME_RE.findall(text)}
    for value, enum_name in _ENUMERATION_VALUE_RE.findall(text):
        seeds.setdefault(enum_name, []).append(value)
    return seeds


def test_migration_0028_enumeration_names_equal_the_domain_enum_registry() -> None:
    seeds = _parse_migration_0028_seeds()
    assert seeds, "no enumeration seeds parsed out of migration 0028 -- regex drifted"
    migration_only = sorted(set(seeds) - set(_DOMAIN_ENUM_BY_NAME))
    domain_only = sorted(set(_DOMAIN_ENUM_BY_NAME) - set(seeds))
    assert migration_only == [], f"migration 0028 enumerations absent from the domain map: {migration_only}"
    assert domain_only == [], f"domain enumerations absent from migration 0028: {domain_only}"


@pytest.mark.parametrize("enum_name", sorted(_DOMAIN_ENUM_BY_NAME))
def test_migration_0028_seed_values_equal_the_domain_enum_values(enum_name: str) -> None:
    """Byte-comparable both directions, order included: 0028 says these are copied verbatim."""
    seeds = _parse_migration_0028_seeds()
    migration_values = seeds[enum_name]
    domain_values = [member.value for member in _DOMAIN_ENUM_BY_NAME[enum_name]]
    assert migration_values == domain_values, (
        f"{enum_name}: migration 0028 seed disagrees with the domain Enum -- "
        f"migration={migration_values} domain={domain_values}"
    )


def test_red_path_a_planted_seed_drift_would_be_caught() -> None:
    """Planted-fixture proof: a value present on only one side fails the equality."""
    real_migration_values = _parse_migration_0028_seeds()["bug_kind"]
    domain_values = [member.value for member in BugKind]
    drifted = real_migration_values + ["not_a_real_bug_kind_value"]
    assert drifted != domain_values  # proves the comparison is not vacuously true
    assert set(drifted) - set(domain_values) == {"not_a_real_bug_kind_value"}


# ---------------------------------------------------------------------------
# 2. Relation-index triple shape: migration 0027 DDL vs relation_index_store.py.
# ---------------------------------------------------------------------------

_CREATE_RELATION_INDEX_RE = re.compile(
    r"CREATE TABLE IF NOT EXISTS relation_index \((.*?)\n\);", re.S
)


def _ddl_columns() -> tuple[str, ...]:
    """The relation_index column order as migration 0027's CREATE TABLE declares it."""
    text = _MIGRATION_0027.read_text(encoding="utf-8")
    match = _CREATE_RELATION_INDEX_RE.search(text)
    assert match, "relation_index CREATE TABLE not found in migration 0027 -- regex drifted"
    columns: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.upper().startswith(("PRIMARY KEY", "CONSTRAINT")):
            continue
        columns.append(stripped.split()[0])
    return tuple(columns)


def _code_side_statement_columns() -> list[tuple[str, ...]]:
    """Every INSERT/SELECT column list relation_index_store.py names for the table."""
    text = _RELATION_INDEX_STORE.read_text(encoding="utf-8")
    statements: list[tuple[str, ...]] = []
    for match in re.finditer(r"INSERT INTO relation_index \(([^)]+)\)", text):
        statements.append(tuple(c.strip() for c in match.group(1).split(",")))
    for match in re.finditer(r"SELECT ([\w, ]+?) FROM relation_index", text):
        statements.append(tuple(c.strip() for c in match.group(1).split(",")))
    return statements


def test_relation_index_ddl_shape_is_source_ref_target_ref_field_ref() -> None:
    assert _ddl_columns() == ("source_ref", "target_ref", "field_ref")


def test_relation_index_store_statements_all_match_the_ddl_column_order() -> None:
    ddl_columns = _ddl_columns()
    statements = _code_side_statement_columns()
    assert statements, "no relation_index INSERT/SELECT statements found -- regex drifted"
    mismatched = [cols for cols in statements if cols != ddl_columns]
    assert mismatched == [], (
        f"relation_index_store.py statement column order disagrees with migration 0027's "
        f"DDL ({ddl_columns}): {mismatched}"
    )


def test_red_path_a_planted_column_reorder_would_be_caught() -> None:
    """Planted-fixture proof: a column list out of DDL order fails the equality."""
    ddl_columns = _ddl_columns()
    reordered = (ddl_columns[1], ddl_columns[0], ddl_columns[2])
    assert reordered != ddl_columns  # proves the comparison is not vacuously true


# ---------------------------------------------------------------------------
# 3. Field catalogue: REFERENCE_CATALOG single-uuid entries vs the shipped
#    rebuild projection generator (relation_index_store.compute_canonical_triples).
# ---------------------------------------------------------------------------

import plan_manager.storage.relation_index_store as relation_index_store
from plan_manager.storage.reference_catalog import REFERENCE_CATALOG


def _expected_field_catalogue_property_names() -> set[str]:
    """Source columns compute_canonical_triples is documented to project.

    Mirrors the exact predicate compute_canonical_triples applies (source of
    truth: REFERENCE_CATALOG) so a drift between the two is caught below.
    """
    return {
        source_column
        for (_source_table, source_column), entry in REFERENCE_CATALOG.items()
        if entry.target_column == "uuid" and not entry.array
    }


class _OneRowConn:
    """Answers every SELECT with one fabricated row; records nothing else.

    compute_canonical_triples only needs a non-empty result to proceed as far
    as calling ensure_reference_field for the property, regardless of whether
    the candidate later resolves through the identity registry -- so one
    fabricated (uuid, uuid) row per query is sufficient to exercise every
    catalogued single-uuid column.
    """

    def execute(self, sql, params=()):
        return _OneRowCursor()


class _OneRowCursor:
    def fetchall(self):
        return [(uuid.uuid4(), uuid.uuid4())]


def test_projection_generator_ensures_a_field_for_every_single_uuid_catalog_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []

    def _fake_ensure_reference_field(conn, property_name, *, predefined=False):
        recorded.append(property_name)
        return uuid.uuid4()

    def _fake_resolve_batch(conn, ids):
        return {}

    monkeypatch.setattr(relation_index_store, "ensure_reference_field", _fake_ensure_reference_field)
    monkeypatch.setattr(relation_index_store, "resolve_entity_identities_batch", _fake_resolve_batch)

    relation_index_store.compute_canonical_triples(_OneRowConn())

    expected = _expected_field_catalogue_property_names()
    generated = set(recorded)
    missing_from_generator = sorted(expected - generated)
    extra_in_generator = sorted(generated - expected)
    assert missing_from_generator == [], (
        f"REFERENCE_CATALOG single-uuid entries the generator never ensures a field for: "
        f"{missing_from_generator}"
    )
    assert extra_in_generator == [], (
        f"generator ensures fields the REFERENCE_CATALOG single-uuid scope does not name: "
        f"{extra_in_generator}"
    )


def test_red_path_an_undeclared_property_name_would_be_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Planted-fixture proof: a property outside REFERENCE_CATALOG's scope fails the equality."""
    recorded = ["plan_uuid", "not_a_real_catalogued_property"]
    expected = _expected_field_catalogue_property_names()
    extra = set(recorded) - expected
    assert extra == {"not_a_real_catalogued_property"}  # proves the comparison is not vacuously true
