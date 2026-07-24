"""Runtime migration additivity and backward-compatibility test coverage (C-035, HRS {d118} bullets 25-26)."""

import glob
import pathlib
import re

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"

REQUIRED_MIGRATION_PREFIXES = ("0009", "0010", "0011", "0012", "0013", "0024")

FORBIDDEN_DDL_SUBSTRINGS = (
    "DROP TABLE",
    "DROP COLUMN",
    "DROP INDEX",
    "ALTER COLUMN",
    "TRUNCATE",
)


def _migration_files_for_prefix(prefix: str) -> list[pathlib.Path]:
    pattern = str(MIGRATIONS_DIR / f"{prefix}*.sql")
    return sorted(pathlib.Path(p) for p in glob.glob(pattern))


def test_each_runtime_migration_prefix_has_exactly_one_file() -> None:
    for prefix in REQUIRED_MIGRATION_PREFIXES:
        matched = _migration_files_for_prefix(prefix)
        assert len(matched) == 1, (
            f"expected exactly one migration file matching {prefix}*.sql in "
            f"{MIGRATIONS_DIR}, found {matched}"
        )


def test_migration_0012_is_named_exactly() -> None:
    matched = _migration_files_for_prefix("0012")
    assert len(matched) == 1
    assert matched[0].name == "0012_runtime_annotations_execution_review.sql"


def test_migration_0024_is_named_exactly() -> None:
    matched = _migration_files_for_prefix("0024")
    assert len(matched) == 1
    assert matched[0].name == "0024_bug_fix_scope_indexes.sql"


def test_migration_0024_adds_the_three_missing_scope_indexes() -> None:
    """todo 070d7b13: bug_fix.source_project_id and bug_fix_propagation's
    linked_plan_uuid / linked_todo_uuid were the two real scope-index gaps
    left after 0009-0023; this pins the exact index names 0024 must add and
    the exact columns each one covers."""
    matched = _migration_files_for_prefix("0024")
    assert len(matched) == 1
    content = matched[0].read_text(encoding="utf-8")
    expected_indexes = {
        "bug_fix_source_project": "CREATE INDEX bug_fix_source_project ON bug_fix (source_project_id);",
        "bug_fix_propagation_plan": (
            "CREATE INDEX bug_fix_propagation_plan ON bug_fix_propagation (linked_plan_uuid);"
        ),
        "bug_fix_propagation_todo": (
            "CREATE INDEX bug_fix_propagation_todo ON bug_fix_propagation (linked_todo_uuid);"
        ),
    }
    for index_name, statement in expected_indexes.items():
        assert statement in content, (
            f"migration 0024 must contain the exact statement {statement!r} "
            f"(index {index_name!r} missing or reworded)"
        )


def test_migration_0024_index_names_do_not_collide_with_existing_indexes() -> None:
    """Guard against accidental name collisions across the whole migration set
    (todo 070d7b13 double-check requirement)."""
    new_index_names = {
        "bug_fix_source_project",
        "bug_fix_propagation_plan",
        "bug_fix_propagation_todo",
    }
    index_pattern = re.compile(r"CREATE(?:\s+UNIQUE)?\s+INDEX\s+(\S+)\s+ON", re.IGNORECASE)
    seen: dict[str, list[str]] = {}
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        content = sql_file.read_text(encoding="utf-8")
        for match in index_pattern.finditer(content):
            seen.setdefault(match.group(1), []).append(sql_file.name)
    for index_name in new_index_names:
        files = seen.get(index_name, [])
        assert files == ["0024_bug_fix_scope_indexes.sql"], (
            f"index name {index_name!r} must appear exactly once, in migration "
            f"0024, but was found in {files!r}"
        )


def test_runtime_migrations_contain_no_destructive_ddl() -> None:
    for prefix in REQUIRED_MIGRATION_PREFIXES:
        matched = _migration_files_for_prefix(prefix)
        assert len(matched) == 1
        migration_path = matched[0]
        content = migration_path.read_text(encoding="utf-8")
        upper_content = content.upper()
        for forbidden in FORBIDDEN_DDL_SUBSTRINGS:
            assert forbidden not in upper_content, (
                f"migration {migration_path} contains forbidden destructive statement "
                f"{forbidden!r}; runtime migrations must be additive-only so existing "
                f"plans keep working"
            )


def test_runtime_migrations_contain_additive_ddl() -> None:
    additive_markers = ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE INDEX", "ADD COLUMN")
    for prefix in REQUIRED_MIGRATION_PREFIXES:
        matched = _migration_files_for_prefix(prefix)
        assert len(matched) == 1
        migration_path = matched[0]
        content = migration_path.read_text(encoding="utf-8")
        upper_content = content.upper()
        assert any(marker in upper_content for marker in additive_markers), (
            f"migration {migration_path} contains no additive DDL statement "
            f"(expected at least one of {additive_markers})"
        )
