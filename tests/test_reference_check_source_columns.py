"""Structural guard against the bug e52daeab / 113a7888 defect class.

Root cause (fixed for TodoItem under 113a7888, then for BugFix/BugImpact/
ExecutionAttempt/BugReport/ReviewResult under e52daeab): DataclassEntity
subclasses may pin ``ReferenceCheck.source_column`` on their
``HARD_DELETE_REFERENCE_CHECKS`` to the dataclass's ``ENTITY_ID_FIELD`` name
(e.g. ``"todo_uuid"``, ``"fix_uuid"``), but
``plan_manager.domain.entity.find_entity_reference_counts`` builds its
``id_values`` dict from ``DataclassEntity.get_by_id``'s row, whose keys are
the RAW DB column names of the entity's table (every table in this schema
names its primary key column literally ``"uuid"``) plus whatever columns
``_normalize_id`` contributes (``ID_COLUMNS`` / ``ID_COLUMN``). A
``source_column`` that is neither a real table column nor an ID column is a
guaranteed ``KeyError`` the first time physical deletion (or a reference-count
preview) reaches that check.

This test walks every ``DataclassEntity`` subclass, and for each one that
declares ``HARD_DELETE_REFERENCE_CHECKS``, statically reconstructs the set of
keys ``id_values`` would contain at runtime (table columns parsed from the
migration DDL, unioned with the entity's ID columns) and asserts every
explicit ``source_column`` (and every ``scope_columns`` id-column reference)
resolves against that set. It must fail on the pre-fix form of any of these
entities -- verified manually by reverting one entity's fix and re-running.
"""
from __future__ import annotations

import pathlib
import re
from typing import Iterator

import pytest

from plan_manager.domain.entity import DataclassEntity

# Import every module that defines a DataclassEntity subclass so that
# DataclassEntity.__subclasses__() actually finds them below -- a subclass is
# only registered once its defining module has executed.
import plan_manager.domain.bug_fix  # noqa: F401
import plan_manager.domain.bug_fix_propagation  # noqa: F401
import plan_manager.domain.bug_impact  # noqa: F401
import plan_manager.domain.bug_report  # noqa: F401
import plan_manager.domain.concept  # noqa: F401
import plan_manager.domain.escalation  # noqa: F401
import plan_manager.domain.execution_attempt  # noqa: F401
import plan_manager.domain.model_binding  # noqa: F401
import plan_manager.domain.paragraph  # noqa: F401
import plan_manager.domain.plan  # noqa: F401
import plan_manager.domain.project_dependency  # noqa: F401
import plan_manager.domain.relation  # noqa: F401
import plan_manager.domain.review_result  # noqa: F401
import plan_manager.domain.runtime_comment  # noqa: F401
import plan_manager.domain.runtime_link  # noqa: F401
import plan_manager.domain.step  # noqa: F401
import plan_manager.domain.todo  # noqa: F401
import plan_manager.domain.todo_link  # noqa: F401
import plan_manager.storage.cascade_request_store  # noqa: F401
import plan_manager.storage.runtime_audit_store  # noqa: F401
import plan_manager.storage.srt_snapshot_store  # noqa: F401


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "plan_manager_db" / "migrations"

_CONSTRAINT_KEYWORDS = frozenset({"UNIQUE", "PRIMARY", "FOREIGN", "CHECK", "CONSTRAINT"})


def _table_columns(table_name: str) -> set[str]:
    """Parse every ``CREATE TABLE <table_name> (...)`` block across all
    migrations and return the column names it declares -- i.e. what a live
    ``SELECT * FROM <table_name>`` would hand back as row keys via
    ``cursor.description``, which is exactly what ``DataclassEntity.get_by_id``
    contributes to ``find_entity_reference_counts``' ``id_values``.
    """
    columns: set[str] = set()
    pattern = re.compile(
        r"CREATE TABLE\s+" + re.escape(table_name) + r"\s*\((.*?)\n\);",
        re.DOTALL,
    )
    found = False
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = sql_file.read_text()
        for match in pattern.finditer(text):
            found = True
            for line in match.group(1).splitlines():
                line = line.strip().rstrip(",")
                if not line:
                    continue
                first_token = line.split()[0]
                if first_token.upper() in _CONSTRAINT_KEYWORDS:
                    continue
                columns.add(first_token)
    assert found, f"no CREATE TABLE {table_name!r} found under {MIGRATIONS_DIR}"
    return columns


def _id_value_keys(entity_cls: type[DataclassEntity]) -> set[str]:
    """Reconstruct the full set of keys ``id_values`` would contain at runtime
    for ``entity_cls``: the raw table columns (from ``get_by_id``'s row) plus
    the entity's own ID columns (from ``_normalize_id``, always present
    regardless of whether a row was found)."""
    assert entity_cls.TABLE_NAME is not None, f"{entity_cls.__name__} has no TABLE_NAME"
    keys = _table_columns(entity_cls.TABLE_NAME)
    if entity_cls.ID_COLUMNS:
        keys.update(entity_cls.ID_COLUMNS)
    elif entity_cls.ID_COLUMN is not None:
        keys.add(entity_cls.ID_COLUMN)
    return keys


def _all_entity_classes() -> Iterator[type[DataclassEntity]]:
    seen: set[type] = set()
    stack: list[type] = list(DataclassEntity.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        yield cls


def _entities_with_hard_delete_checks() -> list[type[DataclassEntity]]:
    return sorted(
        (cls for cls in _all_entity_classes() if cls.HARD_DELETE_REFERENCE_CHECKS),
        key=lambda cls: cls.__name__,
    )


_ENTITIES_WITH_CHECKS = _entities_with_hard_delete_checks()


def test_discovery_finds_the_known_entities() -> None:
    """Sanity check on the discovery mechanism itself: if imports above ever
    stop covering a module, ``_ENTITIES_WITH_CHECKS`` would silently shrink
    and the parametrized test below would vacuously stop covering entities --
    this pins the floor so that regression is visible."""
    names = {cls.__name__ for cls in _ENTITIES_WITH_CHECKS}
    assert {
        "TodoItem",
        "BugFix",
        "BugImpact",
        "ExecutionAttempt",
        "BugReport",
        "ReviewResult",
        "Plan",
        "Step",
        "Concept",
    } <= names, names


@pytest.mark.parametrize(
    "entity_cls",
    _ENTITIES_WITH_CHECKS,
    ids=[cls.__name__ for cls in _ENTITIES_WITH_CHECKS],
)
def test_hard_delete_reference_check_source_columns_resolve(entity_cls: type[DataclassEntity]) -> None:
    """Every ``ReferenceCheck`` on ``entity_cls.HARD_DELETE_REFERENCE_CHECKS``
    must reference columns ``find_entity_reference_counts`` can actually look
    up in its ``id_values`` dict at runtime, else physical deletion raises
    ``KeyError`` (bug e52daeab / 113a7888 defect class)."""
    id_value_keys = _id_value_keys(entity_cls)

    for check in entity_cls.HARD_DELETE_REFERENCE_CHECKS:
        if check.source_column is not None:
            assert check.source_column in id_value_keys, (
                f"{entity_cls.__name__}.HARD_DELETE_REFERENCE_CHECKS: "
                f"ReferenceCheck(table={check.table!r}, column={check.column!r})."
                f"source_column={check.source_column!r} is not a column "
                f"find_entity_reference_counts' id_values would contain for "
                f"{entity_cls.__name__} (table {entity_cls.TABLE_NAME!r} "
                f"resolves to: {sorted(id_value_keys)}); this raises KeyError "
                "at runtime."
            )
        for _reference_column, id_column in check.scope_columns:
            assert id_column in id_value_keys, (
                f"{entity_cls.__name__}.HARD_DELETE_REFERENCE_CHECKS: "
                f"ReferenceCheck(table={check.table!r}, column={check.column!r})."
                f"scope_columns references id_column={id_column!r}, which is "
                f"not a key find_entity_reference_counts' id_values would "
                f"contain for {entity_cls.__name__} "
                f"(resolves to: {sorted(id_value_keys)})."
            )
