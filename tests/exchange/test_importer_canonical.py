"""Regression suite for CR-7 G-005/T-001/A-002: importer.import_canonical_document.

Covers the four behaviours the frozen step names: an absent ref is created
through the engine's recovery/import admission with its original ref and
timestamps preserved; an existing ref of the same kind is cleared and
replaced from the imported record; an existing ref of another kind aborts
the whole import with no partial writes; and a checksum mismatch refuses
before any write at all.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.exchange import canonical_form as cf
from plan_manager.exchange import importer


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
    """Records every executed statement; replays scripted rows per predicate.

    Mirrors the fake connection used by tests/domain/test_entity.py: no live
    PostgreSQL instance is involved anywhere in this module.
    """

    def __init__(self, script=None):
        self._script = list(script or [])
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql_obj, params=()):
        rendered = sql_obj.as_string(None) if hasattr(sql_obj, "as_string") else str(sql_obj)
        flat = " ".join(rendered.split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


def _identity_lookup(flat: str) -> bool:
    return flat.startswith(
        "SELECT id, table_name, entity_type, kind, reserved_by, note, created_at "
        "FROM entity_identity WHERE id = %s"
    )


def _statement_params(executed, prefix: str) -> dict[str, object]:
    """Find the first recorded ``INSERT INTO "table" (...)`` statement starting
    with ``prefix`` and map its parenthesized column list to its bound params."""
    for flat, params in executed:
        if flat.startswith(prefix):
            columns_part = flat.split("(", 1)[1].split(")", 1)[0]
            columns = [c.strip().strip('"') for c in columns_part.split(",")]
            return dict(zip(columns, params))
    raise AssertionError(f"no statement starting with {prefix!r} was recorded")


_SET_COLUMN_RE = re.compile(r'"([^"]+)" = %s')


def _update_set_params(executed, prefix: str) -> dict[str, object]:
    """Find the first recorded ``UPDATE "table" SET ...`` statement starting
    with ``prefix`` and map its SET column list to its leading bound params
    (the WHERE-clause params trail the SET params and are not included)."""
    for flat, params in executed:
        if flat.startswith(prefix):
            set_clause = flat.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            columns = _SET_COLUMN_RE.findall(set_clause)
            return dict(zip(columns, params[: len(columns)]))
    raise AssertionError(f"no statement starting with {prefix!r} was recorded")


# --------------------------------------------------------------------------
# Fixture: one concrete, uuid-keyed, registry-tracked entity kind ("tool") is
# enough to exercise the four identity-preservation behaviours below; full
# per-entity-kind registry coverage is canonical_form.py's own test module's
# job (test_canonical_form.py), not this one's.
# --------------------------------------------------------------------------

_TOOL_CLS = cf.resolve_entity_class("tool")


def _tool_row(*, ref: uuid.UUID, created_at: datetime, updated_at: datetime, marked: bool = False) -> dict:
    return {
        "uuid": ref,
        "name": "probe-tool",
        "server_id": "srv-1",
        "command": "run",
        "pinned_options": {"limit": 1},
        "description": "probe",
        "created_by": "tester",
        "created_at": created_at,
        "updated_at": updated_at,
        "deleted_at": datetime(2026, 1, 3, tzinfo=timezone.utc) if marked else None,
    }


def _tool_document(row: dict) -> dict:
    return cf.build_document([(_TOOL_CLS, row)], [])


# --------------------------------------------------------------------------
# Absent ref: created through the recovery/import admission, ref and
# timestamps preserved exactly.
# --------------------------------------------------------------------------


def test_absent_ref_create_preserves_ref_and_timestamps() -> None:
    ref = uuid.uuid4()
    created_at = datetime(2020, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    updated_at = datetime(2021, 6, 2, 13, 30, 0, tzinfo=timezone.utc)
    document = _tool_document(_tool_row(ref=ref, created_at=created_at, updated_at=updated_at))

    conn = _FakeConn()  # every SELECT replays as "no rows": genuinely absent
    result = importer.import_canonical_document(conn, document)

    assert result == {"entities_created": 1, "entities_replaced": 0, "relations_written": 0}

    insert_params = _statement_params(conn.executed, 'INSERT INTO "tool" (')
    assert insert_params["uuid"] == ref
    assert insert_params["created_at"] == created_at
    assert insert_params["updated_at"] == updated_at
    assert insert_params["deleted_at"] is None

    # The identity registry gained an entry for this ref under the "tool" kind.
    registry_params = _statement_params(conn.executed, "INSERT INTO entity_identity (")
    assert registry_params["id"] == ref
    assert registry_params["entity_type"] == "tool"
    assert registry_params["table_name"] == "tool"


# --------------------------------------------------------------------------
# Same-kind existing ref: cleared and replaced, not (re)created.
# --------------------------------------------------------------------------


def test_same_kind_existing_ref_is_cleared_and_replaced() -> None:
    ref = uuid.uuid4()
    created_at = datetime(2020, 5, 1, tzinfo=timezone.utc)
    updated_at = datetime(2022, 7, 4, tzinfo=timezone.utc)
    document = _tool_document(_tool_row(ref=ref, created_at=created_at, updated_at=updated_at))

    registry_row = (ref, "tool", "tool", "entity", None, None, created_at)
    conn = _FakeConn(script=[(_identity_lookup, [registry_row])])

    result = importer.import_canonical_document(conn, document)

    assert result == {"entities_created": 0, "entities_replaced": 1, "relations_written": 0}
    assert not any(flat.startswith('INSERT INTO "tool"') for flat, _ in conn.executed)
    assert not any(flat.startswith("INSERT INTO entity_identity") for flat, _ in conn.executed)

    update_params = _update_set_params(conn.executed, 'UPDATE "tool" SET ')
    # Every non-ref column from the imported record overwrote the stored row.
    assert update_params["name"] == "probe-tool"
    assert update_params["server_id"] == "srv-1"
    assert update_params["created_at"] == created_at
    assert update_params["updated_at"] == updated_at
    assert "uuid" not in update_params  # ref itself never moves


# --------------------------------------------------------------------------
# Cross-kind conflict: aborts the whole import, no partial writes.
# --------------------------------------------------------------------------


def test_cross_kind_conflict_aborts_with_no_partial_writes() -> None:
    ref = uuid.uuid4()
    created_at = datetime(2020, 5, 1, tzinfo=timezone.utc)
    document = _tool_document(_tool_row(ref=ref, created_at=created_at, updated_at=created_at))

    # The ref is already registered, but under a DIFFERENT entity kind.
    registry_row = (ref, "concept", "concept", "entity", None, None, created_at)
    conn = _FakeConn(script=[(_identity_lookup, [registry_row])])

    with pytest.raises(ValueError, match="identity conflict"):
        importer.import_canonical_document(conn, document)

    # The identity lookup itself ran (conn.executed is non-empty), but nothing
    # ever touched the "tool" table or the identity registry with a write.
    assert conn.executed  # some statement was recorded (the lookup)
    assert not any(
        flat.startswith('INSERT INTO "tool"') or flat.startswith('UPDATE "tool"')
        for flat, _ in conn.executed
    )
    assert not any(flat.startswith("INSERT INTO entity_identity") for flat, _ in conn.executed)


# --------------------------------------------------------------------------
# Checksum mismatch: refuses before any write, zero statements executed.
# --------------------------------------------------------------------------


def test_checksum_mismatch_refuses_before_any_write() -> None:
    ref = uuid.uuid4()
    created_at = datetime(2020, 5, 1, tzinfo=timezone.utc)
    document = _tool_document(_tool_row(ref=ref, created_at=created_at, updated_at=created_at))
    tampered = copy.deepcopy(document)
    tampered["checksum"] = "0" * len(document["checksum"])

    conn = _FakeConn()
    with pytest.raises(ValueError, match="checksum"):
        importer.import_canonical_document(conn, tampered)

    assert conn.executed == []


# --------------------------------------------------------------------------
# Relation triples: written last, through relation_index_store's own
# whole-index-replace surface.
# --------------------------------------------------------------------------


def test_relations_are_written_through_replace_index() -> None:
    ref = uuid.uuid4()
    created_at = datetime(2020, 5, 1, tzinfo=timezone.utc)
    row = _tool_row(ref=ref, created_at=created_at, updated_at=created_at)
    source, target, field = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    document = cf.build_document([(_TOOL_CLS, row)], [(source, target, field)])

    conn = _FakeConn()
    result = importer.import_canonical_document(conn, document)

    assert result["relations_written"] == 1
    assert any(flat == "DELETE FROM relation_index" for flat, _ in conn.executed)
    insert_params = _statement_params(conn.executed, "INSERT INTO relation_index (")
    assert insert_params["source_ref"] == source
    assert insert_params["target_ref"] == target
    assert insert_params["field_ref"] == field
