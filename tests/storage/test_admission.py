"""Regression suite for CR-7 G-002/T-001/A-001: the admission collaborator.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.storage.admission import (
    ADMISSION_CYCLE,
    AdmissionCycleError,
    AdmissionOrderError,
    admit_write_batch,
    ensure_available,
    ensure_edges_acyclic,
    ensure_owner_acyclic,
    ensure_ref,
    missing_targets,
    order_batch,
    reference_closure,
)
from plan_manager.storage.errors import DuplicateNameError


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _ScriptedConn:
    def __init__(self, script=None):
        self._script = list(script or [])
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        flat = " ".join(str(sql).split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


def test_uuid_rule_generation_and_rejection() -> None:
    assert ensure_ref(None).version == 4
    good = uuid.uuid4()
    assert ensure_ref(str(good)) == good
    with pytest.raises(ValueError):
        ensure_ref("garbage")
    with pytest.raises(ValueError):
        ensure_ref(uuid.uuid1())


def test_cross_kind_duplicate_rejection_is_the_registry_guard() -> None:
    taken = uuid.uuid4()
    conn = _ScriptedConn([(lambda sql: sql.startswith("SELECT kind"), [("entity", "plan")])])
    with pytest.raises(DuplicateNameError):
        ensure_available(conn, taken)


def test_batch_existence_admits_intra_batch_references() -> None:
    known, in_batch, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn(
        [
            (
                lambda sql: sql.startswith("SELECT id, table_name, entity_type"),
                [(known, "plan", "plan", None)],
            )
        ]
    )
    report = missing_targets(conn, [known, in_batch, missing], in_batch=[in_batch])
    assert report == [missing] or report == sorted([missing], key=str)


def test_ownership_cycle_is_always_an_error_with_the_single_code() -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(AdmissionCycleError) as excinfo:
        ensure_owner_acyclic([(b, a)], entity_ref=a, new_owner_ref=b)
    assert excinfo.value.code == ADMISSION_CYCLE
    assert "cycle detected" in str(excinfo.value)
    # Detaching to root never cycles.
    ensure_owner_acyclic([(b, a)], entity_ref=a, new_owner_ref=None)


def test_generic_edge_check_carries_the_same_single_code() -> None:
    with pytest.raises(AdmissionCycleError) as excinfo:
        ensure_edges_acyclic([("x", "y"), ("y", "z"), ("z", "x")])
    assert excinfo.value.code == ADMISSION_CYCLE


def test_typed_reference_scc_is_admitted_as_one_group() -> None:
    # a <-> b cycle, c depends on the pair: the SCC writes as one unit first.
    groups = order_batch(["a", "b", "c"], [("a", "b"), ("b", "a"), ("c", "a")])
    assert groups == [["a", "b"], ["c"]]


def test_acyclic_batch_orders_prerequisites_first() -> None:
    groups = order_batch(["w", "r"], [("r", "w")])  # r references w
    assert groups == [["w"], ["r"]]


def test_edge_outside_the_batch_is_unorderable_work() -> None:
    with pytest.raises(AdmissionOrderError):
        order_batch(["a"], [("a", "stranger")])


def test_reference_closure_is_cycle_tolerant_and_single_query() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn(
        [(lambda sql: sql.startswith("WITH RECURSIVE"), [(a,), (b,)])]
    )
    assert reference_closure(conn, [a]) == {a, b}
    assert len(conn.executed) == 1  # one snapshot query, no per-hop lookups
    assert "UNION" in conn.executed[0][0]


def test_admit_write_batch_runs_one_validation_pass() -> None:
    target = uuid.uuid4()
    conn = _ScriptedConn(
        [
            (
                lambda sql: sql.startswith("SELECT id, table_name, entity_type"),
                [(target, "plan", "plan", None)],
            )
        ]
    )
    admit_write_batch(
        conn,
        referenced_refs=[target],
        batch_refs=[],
        owner_edges=[("child", "parent")],
    )
    missing = uuid.uuid4()
    conn = _ScriptedConn(
        [(lambda sql: sql.startswith("SELECT id, table_name, entity_type"), [])]
    )
    with pytest.raises(ValueError, match="missing reference targets"):
        admit_write_batch(conn, referenced_refs=[missing])
