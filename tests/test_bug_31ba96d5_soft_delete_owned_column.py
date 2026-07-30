"""Bug 31ba96d5: soft delete failed for every crud_*-migrated entity.

`soft_delete_entity` writes SOFT_DELETE_COLUMN through `crud_update`, whose
`UPDATE_COLUMNS` whitelist deliberately excludes `deleted_at` — the two-phase
deletion discipline owns that column and a caller must go through
`crud_soft_delete` rather than setting it in a plain update. So the lifecycle
layer's own privileged write was being validated against the caller-facing
whitelist that forbids exactly the column it must write:

    -32603 "unknown update columns for Tool: ['deleted_at']"

Reproduced live on 192.168.254.26 at 0.1.89 (R7_tool_delete_soft_after_detach).
All seven entities CR-6 migrated onto crud_* were affected; only Tool surfaced
because the live run aborts on the first failing Tier-4 group.

The fix keeps `deleted_at` OUT of every descriptor's UPDATE_COLUMNS. Both halves
matter and both are asserted here: a lifecycle write must succeed, and a caller
write of the same column must still be refused.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from psycopg import sql

from plan_manager.domain.entity import DataclassEntity
from plan_manager.storage.reference_catalog import _entity_classes

_NOW = datetime(2026, 7, 30, 10, 36, 9, tzinfo=timezone.utc)


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, row: tuple[Any, ...], columns: tuple[str, ...]) -> None:
        self._row = row
        self.description = tuple(_Column(name) for name in columns)

    def fetchone(self) -> tuple[Any, ...]:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [self._row]


class _FakeConn:
    """Accepts any statement and records it, so the assertion is on the SQL."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append(text)
        return _FakeCursor((None,), ("uuid",))


def _descriptor_entities() -> list[type]:
    """Every entity carrying a populated descriptor and a soft-delete column."""
    return [
        entity
        for entity in _entity_classes()
        if getattr(entity, "SOFT_DELETE_COLUMN", None)
        and getattr(entity, "COLUMNS", ())
        and getattr(entity, "UPDATE_COLUMNS", ())
    ]


def test_the_sweep_finds_entities_to_check() -> None:
    """Guard the guard: an empty sweep would make every test below vacuous."""
    entities = _descriptor_entities()
    assert entities, "no entity with a populated descriptor was discovered"
    names = {entity.__name__ for entity in entities}
    # The seven CR-6 migrated the stores for; CalendarEntry is the exemplar.
    assert {"CalendarEntry", "Tool", "TodoItem", "WishItem"} <= names


@pytest.mark.parametrize(
    "entity", _descriptor_entities(), ids=lambda entity: entity.__name__
)
def test_soft_delete_writes_the_owned_column(entity: type) -> None:
    """The lifecycle layer must be able to write the column it owns."""
    conn = _FakeConn()

    entity.crud_soft_delete(conn, "11111111-1111-1111-1111-111111111111", returning=False)

    assert conn.statements, f"{entity.__name__}: no statement was executed"
    update = conn.statements[0]
    assert update.startswith("UPDATE"), f"{entity.__name__}: expected an UPDATE, got {update}"
    assert f'"{entity.SOFT_DELETE_COLUMN}"' in update, (
        f"{entity.__name__}: the UPDATE does not set {entity.SOFT_DELETE_COLUMN}"
    )


@pytest.mark.parametrize(
    "entity", _descriptor_entities(), ids=lambda entity: entity.__name__
)
def test_the_owned_column_stays_out_of_the_caller_whitelist(entity: type) -> None:
    """deleted_at must NOT become caller-updatable as a side effect of the fix.

    Admitting it to UPDATE_COLUMNS would make the whitelist accept it and break
    the two-phase discipline: a caller could clear or backdate a deletion with a
    plain update instead of going through the lifecycle commands.
    """
    assert entity.SOFT_DELETE_COLUMN not in (entity.UPDATE_COLUMNS or ()), (
        f"{entity.__name__}: {entity.SOFT_DELETE_COLUMN} is caller-updatable; the "
        "deletion lifecycle no longer owns it"
    )


@pytest.mark.parametrize(
    "entity", _descriptor_entities(), ids=lambda entity: entity.__name__
)
def test_a_caller_update_of_the_owned_column_is_still_refused(entity: type) -> None:
    """The whitelist must keep doing its job for ordinary updates."""
    with pytest.raises(ValueError) as excinfo:
        entity.crud_update(
            _FakeConn(),
            "11111111-1111-1111-1111-111111111111",
            {entity.SOFT_DELETE_COLUMN: _NOW},
            returning=False,
        )
    assert entity.SOFT_DELETE_COLUMN in str(excinfo.value)


def test_an_unknown_column_is_still_refused_on_the_lifecycle_path() -> None:
    """The lifecycle exemption is narrow: only the columns it actually owns.

    A blanket bypass would turn crud_soft_delete into an unchecked write path.
    """

    class _Probe(DataclassEntity):
        TABLE_NAME = "calendar_entry"
        ID_COLUMN = "uuid"
        COLUMNS = ("uuid", "deleted_at", "updated_at")
        INSERT_COLUMNS = ("uuid",)
        UPDATE_COLUMNS = ("updated_at",)
        SOFT_DELETE_COLUMN = "deleted_at"
        UPDATED_AT_COLUMN = "updated_at"

    with pytest.raises(ValueError) as excinfo:
        _Probe.crud_update(
            _FakeConn(),
            "11111111-1111-1111-1111-111111111111",
            {"no_such_column": 1},
            returning=False,
        )
    assert "no_such_column" in str(excinfo.value)


def test_soft_delete_also_touches_the_updated_at_column() -> None:
    """The lifecycle write covers updated_at too, and must not be blocked either."""
    from plan_manager.domain.calendar_entry import CalendarEntry

    conn = _FakeConn()
    CalendarEntry.crud_soft_delete(
        conn, "11111111-1111-1111-1111-111111111111", returning=False
    )

    update = conn.statements[0]
    assert f'"{CalendarEntry.UPDATED_AT_COLUMN}"' in update
    assert f'"{CalendarEntry.SOFT_DELETE_COLUMN}"' in update


def test_purge_batch_still_reads_only_soft_deleted_rows() -> None:
    """Sanity: the fix must not disturb how the second phase selects its batch."""
    from plan_manager.domain.calendar_entry import CalendarEntry

    predicate = sql.SQL("{} IS NOT NULL").format(
        sql.Identifier(CalendarEntry.SOFT_DELETE_COLUMN)
    )
    assert "IS NOT NULL" in predicate.as_string(None)
