"""Reference catalog regression suite (CR-6 G-004/T-001). No live database."""

from __future__ import annotations

import pathlib
import re
import sys
from unittest.mock import MagicMock

import pytest

from plan_manager.domain.entity import CENTRAL_REFERENCE_CHECKS
from plan_manager.storage.reference_catalog import (
    BLOCKS_HARD_DELETE,
    CASCADES,
    REFERENCE_CATALOG,
    CatalogEntry,
    blocking_entries_targeting,
    entries_targeting,
    resolve_entity_class,
    table_name_for_entity_type,
    validate_catalog_against_schema,
)

_MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"

# Tables whose real primary-key column is literally 'uuid' while the dataclass
# field is named differently. Resolving the target column from the field name
# produced bug e52daeab and, for todo_item, bug 113a7888.
_LITERAL_UUID_TARGETS = frozenset(
    {"bug_report", "bug_impact", "bug_fix", "execution_attempt", "review_result", "todo_item"}
)

# Entity-type names that must never appear where a table name belongs.
_ENTITY_TYPE_NAMES = frozenset({"todo", "bug", "comment", "wish"})


def test_module_opens_no_connection_at_import_time() -> None:
    """The catalog is static data; importing it must not touch a database."""
    assert "plan_manager.storage.reference_catalog" in sys.modules
    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "plan_manager" / "storage" / "reference_catalog.py"
    ).read_text()
    # No module-level connect/execute: the only psycopg use is inside functions
    # that receive a connection from their caller.
    for line in source.split("\n"):
        if line and not line[0].isspace() and "connect(" in line:
            pytest.fail(f"module-level connection at import time: {line!r}")


def test_catalog_shape() -> None:
    assert isinstance(REFERENCE_CATALOG, dict)
    assert REFERENCE_CATALOG, "the catalog is empty"
    for key, entry in REFERENCE_CATALOG.items():
        assert isinstance(key, tuple) and len(key) == 2
        assert all(isinstance(part, str) for part in key)
        assert isinstance(entry, CatalogEntry)
        assert key == (entry.source_table, entry.source_column), (
            f"catalog key {key} disagrees with its entry"
        )


def test_every_central_reference_check_is_catalogued() -> None:
    """The catalog supersedes CENTRAL_REFERENCE_CHECKS, so it must cover it."""
    missing = [
        f"{kind}: {check.table}.{check.column}"
        for kind, checks in CENTRAL_REFERENCE_CHECKS.items()
        for check in checks
        if (check.table, check.column) not in REFERENCE_CATALOG
    ]
    assert missing == [], f"reference checks absent from the catalog: {missing}"


def test_every_per_entity_reference_check_is_catalogued() -> None:
    """The per-entity HARD_DELETE_REFERENCE_CHECKS attributes too."""
    import importlib
    import pkgutil

    import plan_manager.domain as domain_package
    from plan_manager.domain.entity import DataclassEntity

    for module in pkgutil.iter_modules(domain_package.__path__):
        importlib.import_module(f"{domain_package.__name__}.{module.name}")

    def walk(root):
        for subclass in root.__subclasses__():
            yield subclass
            yield from walk(subclass)

    missing = []
    for entity in walk(DataclassEntity):
        for check in getattr(entity, "HARD_DELETE_REFERENCE_CHECKS", ()):
            if (check.table, check.column) not in REFERENCE_CATALOG:
                missing.append(f"{entity.__name__}: {check.table}.{check.column}")
    assert missing == [], f"per-entity reference checks absent from the catalog: {missing}"


def test_blocking_classification_is_meaningful() -> None:
    """Every entry is classified, and both classes are actually used.

    A cascading foreign key must NOT be marked blocking: the database removes
    the referrer itself, so treating it as blocking would refuse deletions that
    succeed today, such as a plan hard delete cascading to its paragraphs.
    """
    for entry in REFERENCE_CATALOG.values():
        assert entry.blocking in {BLOCKS_HARD_DELETE, CASCADES}, (
            f"{entry.source_table}.{entry.source_column} has an unknown blocking class"
        )
    classes = {entry.blocking for entry in REFERENCE_CATALOG.values()}
    assert classes == {BLOCKS_HARD_DELETE, CASCADES}, (
        "both blocking classes must occur; a catalog where everything blocks would "
        "refuse cascading deletes that work today"
    )
    for entry in REFERENCE_CATALOG.values():
        if entry.on_delete == "CASCADE":
            assert entry.blocking == CASCADES, (
                f"{entry.source_table}.{entry.source_column} cascades in the database "
                "but is classified as blocking"
            )


def test_target_column_is_the_literal_db_column() -> None:
    """Bugs e52daeab and 113a7888: never the dataclass field name."""
    offenders = [
        f"{entry.source_table}.{entry.source_column} -> "
        f"{entry.target_table}.{entry.target_column}"
        for entry in REFERENCE_CATALOG.values()
        if entry.target_table in _LITERAL_UUID_TARGETS and entry.target_column != "uuid"
    ]
    assert offenders == [], (
        "target_column must be the literal DB column 'uuid' for these tables, not the "
        f"dataclass field name: {offenders}"
    )


def test_entity_type_never_appears_as_a_table_name() -> None:
    """target_table is always a real table; the type name lives elsewhere."""
    leaked = sorted(
        {entry.target_table for entry in REFERENCE_CATALOG.values()}
        & _ENTITY_TYPE_NAMES
    )
    assert leaked == [], f"entity-type names used as target_table: {leaked}"
    # And the divergent entities do carry their type explicitly.
    by_table = {entry.target_table: entry for entry in REFERENCE_CATALOG.values()
                if entry.target_entity_type}
    for table, expected in (("todo_item", "todo"), ("bug_report", "bug"),
                            ("runtime_comment", "comment"), ("wish_item", "wish")):
        assert table in by_table, f"no entry records the entity type for {table}"
        assert by_table[table].target_entity_type == expected


def test_catalog_matches_the_live_foreign_key_inventory() -> None:
    """Every real foreign key is catalogued, with the right ON DELETE."""
    schema: dict[tuple[str, str], tuple[str, str]] = {}
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        text = path.read_text()
        for match in re.finditer(
            r'CREATE TABLE (?:IF NOT EXISTS )?"?(\w+)"?\s*\((.*?)\n\);', text, re.S | re.I
        ):
            table = match.group(1)
            for line in match.group(2).split("\n"):
                line = line.strip().rstrip(",")
                inner = re.search(
                    r'^(\w+)\s+\w+.*?REFERENCES\s+"?(\w+)"?\s*\((\w+)\)\s*(?:ON DELETE (\w+))?',
                    line, re.I,
                )
                if inner:
                    schema[(table, inner.group(1))] = (
                        inner.group(2), (inner.group(4) or "NO ACTION").upper()
                    )
        for match in re.finditer(
            r'ALTER TABLE\s+"?(\w+)"?\s+ADD CONSTRAINT\s+\w+\s+FOREIGN KEY\s*\((\w+)\)\s*'
            r'REFERENCES\s+"?(\w+)"?\s*\((\w+)\)\s*([^;]*);',
            text, re.I,
        ):
            on_delete = re.search(r"ON DELETE (\w+)", match.group(5) or "", re.I)
            schema[(match.group(1), match.group(2))] = (
                match.group(3), (on_delete.group(1).upper() if on_delete else "NO ACTION")
            )

    assert schema, "no foreign keys parsed out of the migration chain"
    uncatalogued = sorted(key for key in schema if key not in REFERENCE_CATALOG)
    assert uncatalogued == [], f"foreign keys absent from the catalog: {uncatalogued}"

    declared_fk = {key for key, entry in REFERENCE_CATALOG.items() if entry.fk_backed}
    assert declared_fk == set(schema), (
        "fk_backed set disagrees with the schema; "
        f"claimed-not-real={sorted(declared_fk - set(schema))} "
        f"real-not-claimed={sorted(set(schema) - declared_fk)}"
    )
    mismatched = [
        (key, REFERENCE_CATALOG[key].on_delete, schema[key][1])
        for key in declared_fk
        if REFERENCE_CATALOG[key].on_delete != schema[key][1]
    ]
    assert mismatched == [], f"ON DELETE recorded incorrectly: {mismatched}"


def test_polymorphic_anchor_entries_carry_a_discriminator() -> None:
    """anchor_ref_id points at different tables; each entry must say which."""
    anchors = [
        entry for entry in REFERENCE_CATALOG.values() if entry.source_column == "anchor_ref_id"
    ]
    assert anchors, "no polymorphic anchor entries catalogued"
    for entry in anchors:
        assert entry.const_filters, (
            f"{entry.source_table}.anchor_ref_id has no const_filters, so a lookup "
            "would match rows anchored to a different entity kind"
        )


def test_lookup_helpers_split_blocking_from_cascading() -> None:
    all_plan_refs = entries_targeting("plan")
    blocking = blocking_entries_targeting("plan")
    assert all_plan_refs, "no references to plan catalogued"
    assert 0 < len(blocking) < len(all_plan_refs), (
        "plan has both blocking and cascading referrers; the helpers must separate them"
    )
    assert all(entry.blocking == BLOCKS_HARD_DELETE for entry in blocking)


@pytest.mark.parametrize(
    ("entity_type", "table"),
    [("todo", "todo_item"), ("bug", "bug_report"), ("comment", "runtime_comment"),
     ("wish", "wish_item"), ("plan", "plan"), ("step", "step")],
)
def test_table_name_for_entity_type(entity_type, table) -> None:
    assert table_name_for_entity_type(entity_type) == table


def test_resolve_entity_class_rejects_an_unknown_type() -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_entity_class("no_such_entity")
    message = str(excinfo.value)
    assert "no_such_entity" in message, "the error must name the offending value"
    assert "known types are" in message, "the error must list what is available"


def test_resolvers_need_no_connection() -> None:
    """Both resolvers are pure; they must not require a database."""
    assert resolve_entity_class("plan").TABLE_NAME == "plan"
    assert table_name_for_entity_type("plan") == "plan"


def test_validate_catalog_against_schema_flags_an_uncatalogued_key() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("hypothetical_table", "fake_column", "plan", "uuid"),
    ]
    conn = MagicMock()
    conn.execute.return_value = cursor

    with pytest.raises(ValueError) as excinfo:
        validate_catalog_against_schema(conn)
    assert "hypothetical_table.fake_column" in str(excinfo.value)


def test_validate_catalog_against_schema_reports_a_phantom_fk() -> None:
    """An entry claiming a foreign key the database lacks is also a defect.

    A guard would trust the database to cascade something it will not.
    """
    cursor = MagicMock()
    # Report only ONE of the real foreign keys, so every other fk_backed entry
    # becomes 'extra' rather than 'missing'.
    cursor.fetchall.return_value = [("paragraph", "plan_uuid", "plan", "uuid")]
    conn = MagicMock()
    conn.execute.return_value = cursor

    missing, extra = validate_catalog_against_schema(conn)
    assert missing == []
    assert extra, "phantom fk_backed entries must be reported"
    assert any("revision" in item for item in extra)


def test_catalog_entry_is_frozen_and_hashable() -> None:
    entry = CatalogEntry("a", "b", "c")
    assert hash(entry)
    assert entry.target_column == "uuid"
    assert entry.blocking == BLOCKS_HARD_DELETE
    assert entry.target_entity_type is None
    assert entry.fk_backed is False
    with pytest.raises(Exception):
        entry.source_table = "z"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Bug f7b9cebf: total classification of every uuid reference column.
#
# The FK inventory test above can only see columns the DATABASE enforces. A
# non-FK reference column has no schema-level oracle, so the suite was
# structurally unable to notice an omission in exactly the population that
# needs the catalog most — and 37 such columns were missing, including both
# polymorphic endpoints of runtime_link, which made the deletion guard admit
# deletions it had to refuse.
#
# This check closes that by requiring every uuid column of every registered
# table to be classified: catalogued as a reference, exempted as an external
# identifier, or listed as not-yet-classified. A column in none of the three
# is a gap, not a permission — the ALLOWED_TABLES / EXCLUDED_TABLES discipline
# applied one level down.
# --------------------------------------------------------------------------


def _uuid_columns_of_registered_tables() -> set[tuple[str, str]]:
    """Every uuid column of every ALLOWED_TABLES table, excluding its own PK."""
    from plan_manager.storage.identity import ALLOWED_TABLES

    columns: set[tuple[str, str]] = set()
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        text = path.read_text()
        for match in re.finditer(
            r'CREATE TABLE (?:IF NOT EXISTS )?"?(\w+)"?\s*\((.*?)\n\);', text, re.S | re.I
        ):
            table = match.group(1)
            if table not in ALLOWED_TABLES:
                continue
            for line in match.group(2).split("\n"):
                inner = re.match(r"^(\w+)\s+uuid\b", line.strip().rstrip(","), re.I)
                if inner and inner.group(1) != "uuid":
                    columns.add((table, inner.group(1)))
        for match in re.finditer(
            r'ALTER TABLE\s+"?(\w+)"?\s+ADD COLUMN\s+(?:IF NOT EXISTS\s+)?(\w+)\s+uuid\b',
            text,
            re.I,
        ):
            if match.group(1) in ALLOWED_TABLES and match.group(2) != "uuid":
                columns.add((match.group(1), match.group(2)))
    return columns


def test_every_uuid_column_of_a_registered_table_is_classified() -> None:
    from plan_manager.storage.reference_catalog import (
        EXTERNAL_IDENTIFIER_COLUMNS,
        UNCLASSIFIED_REFERENCE_COLUMNS,
    )

    columns = _uuid_columns_of_registered_tables()
    assert columns, "no uuid columns parsed out of the migration chain"

    classified = (
        set(REFERENCE_CATALOG) | set(EXTERNAL_IDENTIFIER_COLUMNS) | set(UNCLASSIFIED_REFERENCE_COLUMNS)
    )
    unclassified = sorted(columns - classified)
    assert unclassified == [], (
        "uuid columns in neither REFERENCE_CATALOG, EXTERNAL_IDENTIFIER_COLUMNS nor "
        f"UNCLASSIFIED_REFERENCE_COLUMNS: {unclassified}"
    )


def test_the_pending_classification_list_only_shrinks() -> None:
    """A column that got catalogued or exempted must leave the pending list."""
    from plan_manager.storage.reference_catalog import (
        EXTERNAL_IDENTIFIER_COLUMNS,
        UNCLASSIFIED_REFERENCE_COLUMNS,
    )

    resolved = sorted(
        set(UNCLASSIFIED_REFERENCE_COLUMNS)
        & (set(REFERENCE_CATALOG) | set(EXTERNAL_IDENTIFIER_COLUMNS))
    )
    assert resolved == [], (
        "these columns are now classified but still listed as pending; remove them "
        f"from UNCLASSIFIED_REFERENCE_COLUMNS: {resolved}"
    )

    stale = sorted(set(UNCLASSIFIED_REFERENCE_COLUMNS) - _uuid_columns_of_registered_tables())
    assert stale == [], f"pending columns that no longer exist in the schema: {stale}"
