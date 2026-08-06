"""Regression suite for CR-7 G-001/T-001/A-002: the DataclassEntity admission boundary.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.domain.entity import DataclassEntity


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def description(self):  # pragma: no cover - only touched by returning paths
        return []


class _FakeConn:
    """Records executed statements; replays scripted rows per SQL prefix."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        rendered = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        flat = " ".join(rendered.split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


class _Probe(DataclassEntity):
    ENTITY_TYPE = "cr7_probe"
    TABLE_NAME = "calendar_entry"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "title", "created_at", "updated_at", "deleted_at")
    INSERT_COLUMNS = ("uuid", "title", "created_at", "updated_at")
    UPDATE_COLUMNS = ("title",)
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"
    REGISTER_IDENTITY = False


class _StrictProbe(_Probe):
    ENTITY_TYPE = "cr7_probe_strict"
    ENGINE_MANAGED_TIMESTAMPS = True


def test_create_validates_a_supplied_ref_as_uuid4() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="must be version 4"):
        _Probe.crud_create(
            conn, {"uuid": uuid.uuid1(), "title": "x"}, returning=False
        )
    assert conn.executed == []  # refused before any write

    good = uuid.uuid4()
    _Probe.crud_create(conn, {"uuid": str(good), "title": "x"}, returning=False)
    insert_sql, params = conn.executed[-1]
    assert insert_sql.startswith('INSERT INTO "calendar_entry"')
    assert params[0] == good  # string candidate normalized to the UUID value


def test_update_never_changes_ref() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="identity columns are immutable"):
        _Probe.crud_update(
            conn, uuid.uuid4(), {"uuid": uuid.uuid4()}, returning=False
        )
    assert conn.executed == []


def test_engine_managed_create_refuses_caller_timestamps_and_stamps_its_own() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="caller-supplied"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x", "created_at": datetime.now(timezone.utc)},
            returning=False,
        )
    assert conn.executed == []

    _StrictProbe.crud_create(
        conn, {"uuid": uuid.uuid4(), "title": "x"}, returning=False
    )
    insert_sql, params = conn.executed[-1]
    assert '"created_at"' in insert_sql and '"updated_at"' in insert_sql
    stamped = [value for value in params if isinstance(value, datetime)]
    assert len(stamped) == 2 and stamped[0] == stamped[1]


def test_engine_managed_update_refuses_caller_timestamps_and_refreshes_updated_at() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="refused on update"):
        _StrictProbe.crud_update(
            conn,
            uuid.uuid4(),
            {"title": "x", "updated_at": datetime.now(timezone.utc)},
            returning=False,
        )
    assert conn.executed == []

    _StrictProbe.crud_update(conn, uuid.uuid4(), {"title": "x"}, returning=False)
    update_sql, params = conn.executed[-1]
    assert '"updated_at" = %s' in update_sql
    assert any(isinstance(value, datetime) for value in params)


def test_legacy_entities_keep_store_stamped_timestamps() -> None:
    """ENGINE_MANAGED_TIMESTAMPS=False preserves the compatibility behaviour."""
    conn = _FakeConn()
    supplied = datetime.now(timezone.utc)
    _Probe.crud_create(
        conn,
        {"uuid": uuid.uuid4(), "title": "x", "created_at": supplied},
        returning=False,
    )
    _, params = conn.executed[-1]
    assert supplied in params


def test_admit_original_timestamps_requires_recovery_mode() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="requires recovery_mode"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x"},
            returning=False,
            admit_original_timestamps=True,
        )
    assert conn.executed == []


def test_recovery_mode_restores_a_missing_row_with_original_timestamps() -> None:
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT 1 FROM"), [])])
    _StrictProbe.crud_create(
        conn,
        {"uuid": uuid.uuid4(), "title": "x", "created_at": original},
        returning=False,
        recovery_mode=True,
        admit_original_timestamps=True,
    )
    absence_check, insert = conn.executed[0], conn.executed[-1]
    assert absence_check[0].startswith('SELECT 1 FROM "calendar_entry"')
    assert insert[0].startswith('INSERT INTO "calendar_entry"')
    assert original in insert[1]


def test_recovery_mode_never_replaces_an_existing_row() -> None:
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT 1 FROM"), [(1,)])])
    with pytest.raises(ValueError, match="never replaces an existing row"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x"},
            returning=False,
            recovery_mode=True,
        )
    assert not any(sql.startswith("INSERT") for sql, _ in conn.executed)


def test_recovery_mode_requires_the_original_identifier() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="requires the original identifier"):
        _Probe.crud_create(
            conn, {"title": "x"}, returning=False, recovery_mode=True
        )


# --------------------------------------------------------------------------
# CR-7 G-003/T-001/A-001: ownership declaration surface.
# --------------------------------------------------------------------------


def test_ownership_states_are_mutually_exclusive() -> None:
    class _Bad(_Probe):
        ENTITY_TYPE = "cr7_probe_bad_owner"
        OWNER_COLUMN = "title"
        OWNER_ROOT = True

    with pytest.raises(ValueError, match="mutually exclusive"):
        _Bad.validate_ownership_declaration()


def test_owner_column_must_exist_in_columns() -> None:
    class _Bad(_Probe):
        ENTITY_TYPE = "cr7_probe_missing_owner_col"
        OWNER_COLUMN = "no_such_column"

    with pytest.raises(ValueError, match="absent from COLUMNS"):
        _Bad.validate_ownership_declaration()


def test_each_single_state_is_accepted() -> None:
    class _Col(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_col"
        OWNER_COLUMN = "title"

    class _Root(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_root"
        OWNER_ROOT = True

    class _Gap(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_gap"
        OWNER_GAP = "no usable owner column until the G-007 anchor collapse"

    for cls in (_Col, _Root, _Gap):
        cls.validate_ownership_declaration(require_ownership=True)


def test_completeness_is_enforced_only_on_request() -> None:
    class _Undeclared(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_undeclared"

    _Undeclared.validate_ownership_declaration()  # consistency only: passes
    with pytest.raises(ValueError, match="no ownership state declared"):
        _Undeclared.validate_ownership_declaration(require_ownership=True)


def test_gap_must_carry_a_statement() -> None:
    class _Blank(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_blank_gap"
        OWNER_GAP = "   "

    with pytest.raises(ValueError, match="non-empty statement"):
        _Blank.validate_ownership_declaration()


def test_all_shipped_entity_ownership_declarations_are_complete() -> None:
    """CR-7 G-003/T-001/A-002..A-031: every shipped entity declares its state."""
    import importlib
    import pkgutil

    import plan_manager.domain as domain_pkg

    for module in pkgutil.iter_modules(domain_pkg.__path__):
        importlib.import_module(f"{domain_pkg.__name__}.{module.name}")

    def _subclasses(root):
        found = []
        for sub in root.__subclasses__():
            found.append(sub)
            found.extend(_subclasses(sub))
        return found

    declared = 0
    for cls in _subclasses(DataclassEntity):
        if (cls.__module__ or "").startswith("tests"):
            continue
        if not (cls.__module__ or "").startswith("plan_manager.domain."):
            continue
        if cls.__name__ in {"EntityIdentifier"}:
            continue
        cls.validate_ownership_declaration(require_ownership=True)
        declared += 1
    assert declared >= 31  # 30 per-entity AS targets + ToolsetMembership
