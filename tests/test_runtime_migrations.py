"""Runtime migration additivity and backward-compatibility test coverage (C-035, HRS {d118} bullets 25-26)."""

import glob
import pathlib

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"

REQUIRED_MIGRATION_PREFIXES = ("0009", "0010", "0011", "0012", "0013")

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
