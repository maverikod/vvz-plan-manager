"""Regression suite for bug 5c0ddc16 (CR-7 G-007/T-001/A-004).

A wish previously had no re-anchor route at all: moving it meant delete and
recreate, losing its uuid/created_at and orphaning inbound references. This
closes the bug by construction: plan_manager.domain.reanchor_guard.
guard_owner_update is the ONE generic owner-update entry, and the wish path
now uses it (no new wish_reanchor command surface -- that is G-008's).

Covers, per the frozen G-007/T-001/A-004 acceptance letter:
  * a wish re-anchors in place -- an UPDATE only, uuid/created_at/inbound
    references untouched, never a DELETE+INSERT of the wish row;
  * guard_reanchor_target_not_frozen (the function todo_reanchor_store.py
    and bug_reanchor_store.py still import UNCHANGED) keeps its exact
    pre-existing behaviour;
  * a cycle-closing owner update is refused by the REAL admission
    collaborator (storage.admission.ensure_owner_acyclic), not a private
    copy;
  * a frozen-truth target (a frozen plan) is refused exactly as the
    existing reanchor commands document.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.reanchor_guard import (
    guard_owner_update,
    guard_reanchor_target_not_frozen,
)
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
from plan_manager.storage.admission import AdmissionCycleError


class _Cur:
    def __init__(self, row) -> None:
        self._row = row

    def fetchone(self):
        return self._row


class _GuardConn:
    """Fake psycopg-shaped conn serving every collaborator query
    guard_owner_update's call chain issues (owner_form_to_columns's internal
    validate_anchor + resolve_entity_identity, guard_reanchor_target_not_frozen,
    and the ancestry walk's per-row anchor-column SELECT), from caller-supplied
    canned tables. Every statement is recorded so a test can assert exactly
    what ran (in particular: no DELETE/INSERT of the moved row -- an UPDATE
    only). Anything unrecognized raises loudly rather than answering wrong.
    """

    def __init__(
        self,
        *,
        table_by_id: dict[uuid.UUID, str] | None = None,
        frozen_plans: frozenset[uuid.UUID] = frozenset(),
        frozen_steps: frozenset[uuid.UUID] = frozenset(),
        completed_plans: frozenset[uuid.UUID] = frozenset(),
        anchor_rows: dict[tuple[str, uuid.UUID], tuple] | None = None,
    ) -> None:
        self._table_by_id = table_by_id or {}
        self._frozen_plans = frozen_plans
        self._frozen_steps = frozen_steps
        self._completed_plans = completed_plans
        self._anchor_rows = anchor_rows or {}
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()):
        self.statements.append((sql, params))

        if "FROM entity_identity WHERE id = %s" in sql:
            entity_id = params[0]
            table_name = self._table_by_id.get(entity_id)
            if table_name is None:
                return _Cur(None)
            return _Cur((entity_id, table_name, "entity", "entity", None, None, None))

        if sql.startswith("SELECT completed FROM plan"):
            return _Cur((params[0] in self._completed_plans,))

        if sql.startswith("SELECT status FROM plan"):
            return _Cur(("frozen" if params[0] in self._frozen_plans else "draft",))

        if sql.startswith("SELECT status FROM step"):
            return _Cur(("frozen" if params[0] in self._frozen_steps else "draft",))

        if sql.startswith("SELECT 1 FROM"):
            return _Cur((1,))

        if sql.startswith("SELECT uuid FROM step"):
            return _Cur((params[0],))

        if sql.startswith("SELECT primary_anchor_type, "):
            table = sql.split(" FROM ", 1)[1].split(" WHERE", 1)[0].strip()
            return _Cur(self._anchor_rows.get((table, params[0])))

        if sql.startswith("UPDATE "):
            return _Cur(None)

        raise AssertionError(f"unexpected query in this fixture: {sql!r} params={params!r}")


_NONE_ANCHOR_ROW = ("none", None, None, None, None, None, None, None)


def _todo_anchor_row(ref_id: uuid.UUID) -> tuple:
    return ("todo", None, None, None, None, None, None, ref_id)


# ---------------------------------------------------------------------------
# A wish re-anchors in place: UPDATE only, never delete-and-recreate.
# ---------------------------------------------------------------------------


def test_wish_reanchors_in_place_update_only_no_delete_or_insert_of_wish_row() -> None:
    wish_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    conn = _GuardConn(table_by_id={wish_uuid: "wish_item", plan_uuid: "plan"})

    result = guard_owner_update(conn, wish_uuid, plan_uuid)

    assert result["table_name"] == "wish_item"
    assert result["entity_ref"] == wish_uuid
    assert result["primary_anchor_type"] == "plan"
    assert result["anchor_plan_uuid"] == plan_uuid

    update_statements = [s for s in conn.statements if s[0].startswith("UPDATE")]
    assert len(update_statements) == 1
    sql, params = update_statements[0]
    assert sql.startswith("UPDATE wish_item SET ")
    set_clause = sql.split(" SET ", 1)[1].split(" WHERE", 1)[0]
    set_columns = [assignment.strip() for assignment in set_clause.split(",")]
    assert "uuid = %s" not in set_columns  # the primary key itself is never assigned
    assert "created_at" not in sql  # created_at is never touched
    assert params[-1] == wish_uuid  # the WHERE uuid = %s binds the SAME row

    # The wish row itself is never deleted or (re)inserted -- the whole
    # point of closing bug 5c0ddc16 by construction.
    for sql, _params in conn.statements:
        assert "DELETE FROM wish_item" not in sql
        assert "INSERT INTO wish_item" not in sql


def test_wish_reanchor_preserves_ref_by_updating_the_same_uuid_only() -> None:
    wish_uuid = uuid.uuid4()
    other_wish_uuid = uuid.uuid4()
    todo_uuid = uuid.uuid4()
    conn = _GuardConn(table_by_id={wish_uuid: "wish_item", todo_uuid: "todo_item"})

    guard_owner_update(conn, wish_uuid, todo_uuid)

    sql, params = [s for s in conn.statements if s[0].startswith("UPDATE")][0]
    assert params[-1] == wish_uuid
    assert other_wish_uuid not in params  # only the targeted wish row is touched


# ---------------------------------------------------------------------------
# todo_reanchor / bug_reanchor behaviour: UNCHANGED (smoke-level, exercising
# the SAME function object those two stores still import untouched).
# ---------------------------------------------------------------------------


class _FrozenTruthConn:
    def __init__(self, *, frozen_plans: frozenset[uuid.UUID] = frozenset(),
                 frozen_steps: frozenset[uuid.UUID] = frozenset()) -> None:
        self._frozen_plans = frozen_plans
        self._frozen_steps = frozen_steps

    def execute(self, sql: str, params: tuple):
        if sql.startswith("SELECT status FROM plan"):
            return _Cur(("frozen" if params[0] in self._frozen_plans else "draft",))
        if sql.startswith("SELECT status FROM step"):
            return _Cur(("frozen" if params[0] in self._frozen_steps else "draft",))
        raise AssertionError(f"unexpected query: {sql!r}")


def test_guard_reanchor_target_not_frozen_refuses_frozen_plan() -> None:
    plan_uuid = uuid.uuid4()
    conn = _FrozenTruthConn(frozen_plans=frozenset({plan_uuid}))
    with pytest.raises(FrozenTruthMutationError):
        guard_reanchor_target_not_frozen(conn, "plan", plan_uuid, None)


def test_guard_reanchor_target_not_frozen_refuses_frozen_step() -> None:
    step_uuid = uuid.uuid4()
    conn = _FrozenTruthConn(frozen_steps=frozenset({step_uuid}))
    with pytest.raises(FrozenTruthMutationError):
        guard_reanchor_target_not_frozen(conn, "step", None, step_uuid)


def test_guard_reanchor_target_not_frozen_admits_non_frozen_plan_and_step() -> None:
    plan_uuid, step_uuid = uuid.uuid4(), uuid.uuid4()
    conn = _FrozenTruthConn()
    guard_reanchor_target_not_frozen(conn, "plan", plan_uuid, None)  # must not raise
    guard_reanchor_target_not_frozen(conn, "step", None, step_uuid)  # must not raise


def test_guard_reanchor_target_not_frozen_is_a_noop_for_every_other_anchor_type() -> None:
    # todo_reanchor's own vocabulary (none/project/file/revision/execution_
    # attempt/review_result/bug/bug_fix/todo) and bug_reanchor's own
    # (command/runtime_service/unidentified) never touch a frozen-truth
    # table at all -- a conn that raises on ANY query proves the no-op.
    class _ExplodingConn:
        def execute(self, sql, params=()):
            raise AssertionError(f"must not query for this anchor type: {sql!r}")

    for anchor_type in ("none", "project", "file", "revision", "execution_attempt",
                         "review_result", "bug", "bug_fix", "todo",
                         "command", "runtime_service", "unidentified"):
        guard_reanchor_target_not_frozen(_ExplodingConn(), anchor_type, None, None)


# ---------------------------------------------------------------------------
# A cycle-closing owner update is refused by the REAL admission collaborator.
# ---------------------------------------------------------------------------


def test_cycle_closing_owner_update_is_refused_by_the_admission_collaborator() -> None:
    # Todo B is currently owned by todo A (B.anchor = todo/A). Moving A's
    # owner onto B would close the cycle A -> B -> A.
    todo_a = uuid.uuid4()
    todo_b = uuid.uuid4()
    conn = _GuardConn(
        table_by_id={todo_a: "todo_item", todo_b: "todo_item"},
        anchor_rows={
            ("todo_item", todo_b): _todo_anchor_row(todo_a),
            ("todo_item", todo_a): _NONE_ANCHOR_ROW,
        },
    )

    with pytest.raises(AdmissionCycleError):
        guard_owner_update(conn, todo_a, todo_b)

    # The cycle is caught before any write -- no UPDATE ever ran.
    assert not any(s[0].startswith("UPDATE") for s in conn.statements)


def test_owner_update_detaching_to_root_never_cycles() -> None:
    wish_uuid = uuid.uuid4()
    conn = _GuardConn(table_by_id={wish_uuid: "wish_item"})
    result = guard_owner_update(conn, wish_uuid, None)
    assert result["primary_anchor_type"] == "none"


# ---------------------------------------------------------------------------
# A frozen-truth target is refused exactly as the existing commands document.
# ---------------------------------------------------------------------------


def test_owner_update_refuses_a_frozen_plan_target() -> None:
    wish_uuid = uuid.uuid4()
    frozen_plan = uuid.uuid4()
    conn = _GuardConn(
        table_by_id={wish_uuid: "wish_item", frozen_plan: "plan"},
        frozen_plans=frozenset({frozen_plan}),
    )
    with pytest.raises(FrozenTruthMutationError):
        guard_owner_update(conn, wish_uuid, frozen_plan)

    # Refused before any write.
    assert not any(s[0].startswith("UPDATE") for s in conn.statements)


def test_owner_update_refuses_a_frozen_step_target() -> None:
    wish_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    frozen_step = uuid.uuid4()
    conn = _GuardConn(
        table_by_id={wish_uuid: "wish_item", frozen_step: "step"},
        frozen_steps=frozenset({frozen_step}),
    )
    with pytest.raises(FrozenTruthMutationError):
        guard_owner_update(conn, wish_uuid, frozen_step, plan_uuid=plan_uuid)
