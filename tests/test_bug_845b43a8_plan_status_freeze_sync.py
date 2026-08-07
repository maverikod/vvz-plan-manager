"""Regression tests for bug 845b43a8: plan.status stayed 'draft' forever and
never synced with the authoritative step lifecycle tree, so a fully frozen
plan (step_transition scope='whole_plan', to_status='frozen', gate green)
still reported 'draft' from plan_status and plan_list.

Covers: plan_manager.domain.plan_status_sync (the pure derivation and the
raw-SQL setter), step_transition_command's atomic sync on every mutating
transition (whole_plan, a partial scope that completes or breaks a full
freeze, and a scoped unfreeze), plan_status_command's derived_status /
status_consistent fields, and the content of migration 0030 (the one-time
data repair for rows written before this fix existed).

plan_unfreeze_command's reset-to-'draft' behavior is covered separately in
tests/test_plan_unfreeze.py (it already carries the established fake-conn
pattern for that command).

Unit-style throughout: no real database, matching the established
monkeypatch _fake_db / fake-conn pattern used by test_plan_unfreeze.py and
test_subtree_unfreeze_audit.py.
"""
from __future__ import annotations

import asyncio
import pathlib
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands import step_transition_command
from plan_manager.commands.plan_status_command import PlanStatusCommand
from plan_manager.commands.step_transition_command import StepTransitionCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.plan_status_sync import (
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_FROZEN,
    derive_plan_status,
    set_plan_status,
)
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "plan_manager_db" / "migrations"


# --------------------------------------------------------------------------- helpers


def _uuid(tag: str) -> uuid.UUID:
    """Deterministic uuid from a short digit tag, zero-padded to 12 hex chars."""
    return uuid.UUID(f"00000000-0000-0000-0000-{tag:0>12}")


def _step(step_uuid: uuid.UUID, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=step_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _branch(branch_tag: str, group_num: str, status: str) -> dict[uuid.UUID, Step]:
    """One G/T/A branch, all three levels at `status`. `branch_tag` keeps the
    uuids of different branches distinct; `group_num` is the 3-digit G-NNN
    suffix (canonical_step_path/scope matching requires exactly 3 digits)."""
    gs = _step(_uuid(f"{branch_tag}1"), 3, f"G-{group_num}", None, status)
    ts = _step(_uuid(f"{branch_tag}2"), 4, "T-001", gs.uuid, status)
    atomic = _step(_uuid(f"{branch_tag}3"), 5, "A-001", ts.uuid, status)
    return {s.uuid: s for s in (gs, ts, atomic)}


def _plan(status: str = "draft") -> Plan:
    return Plan(
        uuid=PLAN_UUID, name="p", status=status, context_budget=4000,
        head_revision_uuid=HEAD_REV, project_ids=[], primary_project_id=None,
    )


class _RecordingConn:
    """Fake connection that just logs every execute() call, in order."""

    def __init__(self) -> None:
        self.log: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.log.append((sql, tuple(params) if params else ()))
        return None


def _make_fake_db(conn):
    @contextmanager
    def _fake_db():
        yield conn

    return _fake_db


def _patch_common(monkeypatch, nodes, conn, plan=None) -> dict:
    calls: dict = {}
    monkeypatch.setattr(step_transition_command, "db_connection", _make_fake_db(conn))
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda c, p: plan or _plan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda c, plan_uuid: nodes)
    monkeypatch.setattr(
        step_transition_command, "check_admission",
        lambda c, plan_uuid, kind, target_uuid, cascade_uuid: _FakeCascadeRec(),
    )
    monkeypatch.setattr(step_transition_command, "get_ref", lambda c, plan_uuid, name: HEAD_REV)

    def _rev(c, plan_uuid, actor, message, changes, parent, ref_name=None):
        calls["revision"] = {"changes": changes, "parent": parent, "ref_name": ref_name}
        return uuid.uuid4()

    monkeypatch.setattr(step_transition_command, "record_revision", _rev)

    def _audit(c, **kwargs):
        calls.setdefault("audit_calls", []).append(kwargs)
        return _AuditRecord()

    monkeypatch.setattr(step_transition_command, "record_runtime_change", _audit)
    return calls


class _FakeCascadeRec:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = "cascade/x"


class _AuditRecord:
    def __init__(self) -> None:
        self.audit_uuid = uuid.uuid4()


def _plan_status_updates(conn: _RecordingConn) -> list[tuple[str, ...]]:
    return [entry for entry in conn.log if entry[0].startswith("UPDATE plan SET status")]


# --------------------------------------------------------------------------- derive_plan_status (pure)


def test_derive_plan_status_empty_tree_is_draft() -> None:
    assert derive_plan_status([]) == PLAN_STATUS_DRAFT


def test_derive_plan_status_all_frozen_is_frozen() -> None:
    assert derive_plan_status(["frozen", "frozen", "frozen"]) == PLAN_STATUS_FROZEN


def test_derive_plan_status_any_non_frozen_is_draft() -> None:
    assert derive_plan_status(["frozen", "frozen", "draft"]) == PLAN_STATUS_DRAFT
    assert derive_plan_status(["frozen", "ready_for_review"]) == PLAN_STATUS_DRAFT
    assert derive_plan_status(["frozen", "needs_review"]) == PLAN_STATUS_DRAFT


# --------------------------------------------------------------------------- set_plan_status (raw SQL)


def test_set_plan_status_issues_a_plain_update_no_g004_marker_needed() -> None:
    conn = _RecordingConn()
    set_plan_status(conn, PLAN_UUID, PLAN_STATUS_FROZEN)
    assert conn.log == [("UPDATE plan SET status = %s WHERE uuid = %s", (PLAN_STATUS_FROZEN, PLAN_UUID))]


# --------------------------------------------------------------------------- step_transition: sync on every mutation


def test_whole_plan_freeze_syncs_plan_status_to_frozen(monkeypatch) -> None:
    nodes = _branch("1", "001", "draft")
    conn = _RecordingConn()
    _patch_common(monkeypatch, nodes, conn)

    result = asyncio.run(
        StepTransitionCommand().execute(plan="p", to_status="frozen", require_green=False)
    )
    payload = result.to_dict()
    assert payload["success"] is True

    updates = _plan_status_updates(conn)
    assert updates == [("UPDATE plan SET status = %s WHERE uuid = %s", (PLAN_STATUS_FROZEN, PLAN_UUID))]


def test_partial_scope_freeze_completing_the_tree_syncs_to_frozen(monkeypatch) -> None:
    """G-001 already frozen, G-002 still draft: freezing ONLY G-002 completes
    the whole tree, so the aggregate must flip to 'frozen' even though the
    scope of this call was never 'whole_plan'."""
    nodes = {**_branch("1", "001", "frozen"), **_branch("2", "002", "draft")}
    conn = _RecordingConn()
    _patch_common(monkeypatch, nodes, conn)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="frozen", scope="G-002", require_green=False
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True

    updates = _plan_status_updates(conn)
    assert updates == [("UPDATE plan SET status = %s WHERE uuid = %s", (PLAN_STATUS_FROZEN, PLAN_UUID))]


def test_partial_scope_freeze_not_completing_the_tree_stays_draft(monkeypatch) -> None:
    """Both groups start draft; freezing only G-001 leaves G-002 draft, so the
    aggregate must NOT flip to 'frozen' just because one scope froze."""
    nodes = {**_branch("1", "001", "draft"), **_branch("2", "002", "draft")}
    conn = _RecordingConn()
    _patch_common(monkeypatch, nodes, conn)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="frozen", scope="G-001", require_green=False
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True

    updates = _plan_status_updates(conn)
    assert updates == [("UPDATE plan SET status = %s WHERE uuid = %s", (PLAN_STATUS_DRAFT, PLAN_UUID))]


def test_scoped_unfreeze_under_cascade_syncs_plan_status_to_draft(monkeypatch) -> None:
    nodes = _branch("1", "001", "frozen")
    conn = _RecordingConn()
    calls = _patch_common(monkeypatch, nodes, conn)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="draft", scope="G-001",
            cascade_uuid=str(uuid.uuid4()), changed_by="o", reason="reopen",
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert calls["audit_calls"][0]["action"] == "subtree_unfreeze"

    updates = _plan_status_updates(conn)
    assert updates == [("UPDATE plan SET status = %s WHERE uuid = %s", (PLAN_STATUS_DRAFT, PLAN_UUID))]


def test_dry_run_never_writes_plan_status_or_step_status(monkeypatch) -> None:
    nodes = _branch("1", "001", "draft")
    conn = _RecordingConn()
    _patch_common(monkeypatch, nodes, conn)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="frozen", require_green=False, dry_run=True
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["dry_run"] is True
    assert conn.log == []


def test_status_write_shares_the_same_connection_and_follows_step_updates(monkeypatch) -> None:
    """Atomicity precondition: the plan.status UPDATE must run on the exact
    same conn/transaction as the step UPDATEs (not a second connection that
    could commit or fail independently), and after them so it reflects the
    post-transition tree."""
    nodes = _branch("1", "001", "draft")
    conn = _RecordingConn()
    _patch_common(monkeypatch, nodes, conn)

    asyncio.run(StepTransitionCommand().execute(plan="p", to_status="frozen", require_green=False))

    step_update_count = sum(1 for entry in conn.log if entry[0].startswith("UPDATE step SET status"))
    assert step_update_count == 3  # one per step in the branch
    assert conn.log[-1][0].startswith("UPDATE plan SET status")  # status sync is last
    assert conn.log[-1][1] == (PLAN_STATUS_FROZEN, PLAN_UUID)


# --------------------------------------------------------------------------- rollback / atomicity with a real transaction shape


class _TxConn(_RecordingConn):
    """Adds the commit/rollback bookkeeping plan_manager.runtime.context.
    db_connection performs around the real psycopg connection, so a test can
    prove the plan.status write is undone together with everything else in
    the same operation when a later step raises."""

    def __init__(self) -> None:
        super().__init__()
        self.committed = False
        self.rolled_back = False


@contextmanager
def _tx_scoped_db(conn: _TxConn):
    """Local stand-in mirroring plan_manager.runtime.context.db_connection's
    commit-on-success / rollback-on-exception contract, without requiring a
    real psycopg connection or init_runtime."""
    try:
        yield conn
        conn.committed = True
    except BaseException:
        conn.rolled_back = True
        raise


def test_status_update_rolls_back_together_with_the_freeze_transition(monkeypatch) -> None:
    """If anything after the plan.status write fails before the operation's
    transaction exits, the whole thing -- step updates AND the plan.status
    sync -- must roll back together, because they share one connection.
    """
    nodes = _branch("1", "001", "draft")
    conn = _TxConn()
    _patch_common(monkeypatch, nodes, conn)

    @contextmanager
    def _fake_db():
        with _tx_scoped_db(conn) as c:
            yield c

    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure after the status sync")

    monkeypatch.setattr(step_transition_command, "record_revision", _boom)

    with pytest.raises(RuntimeError):
        asyncio.run(
            StepTransitionCommand().execute(plan="p", to_status="frozen", require_green=False)
        )

    # The plan.status UPDATE was issued (proving it ran, atomically, before
    # the failure) but the surrounding transaction rolled back, not
    # committed -- so nothing partial was ever made durable.
    assert _plan_status_updates(conn)
    assert conn.rolled_back is True
    assert conn.committed is False


# --------------------------------------------------------------------------- plan_status: derived_status / consistency


@contextmanager
def _fake_status_db(conn):
    yield conn


def _patch_plan_status(monkeypatch, nodes, plan) -> None:
    import plan_manager.commands.plan_status_command as mod

    monkeypatch.setattr(mod, "db_connection", lambda: _fake_status_db(object()))
    monkeypatch.setattr(mod, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(mod, "load_steps", lambda conn, plan_uuid: nodes)

    class _Check:
        findings: list = []

    class _Report:
        green = True
        checks = [_Check()]

    class _Verdict:
        revision_uuid = None
        scope = "plan"

    monkeypatch.setattr(mod, "run_gate", lambda conn, plan_uuid: (_Report(), _Verdict()))


def test_plan_status_reports_consistent_when_stored_status_matches_tree(monkeypatch) -> None:
    nodes = _branch("1", "001", "frozen")
    plan = _plan(status="frozen")
    _patch_plan_status(monkeypatch, nodes, plan)

    result = asyncio.run(PlanStatusCommand().execute(plan="p"))
    data = result.to_dict()["data"]
    assert data["plan"]["status"] == "frozen"
    assert data["plan"]["derived_status"] == "frozen"
    assert data["plan"]["status_consistent"] is True


def test_plan_status_flags_historical_divergence(monkeypatch) -> None:
    """The exact bug 845b43a8 shape: every step frozen, but the stored
    plan.status row never got the memo (pre-repair / pre-fix data)."""
    nodes = _branch("1", "001", "frozen")
    plan = _plan(status="draft")
    _patch_plan_status(monkeypatch, nodes, plan)

    result = asyncio.run(PlanStatusCommand().execute(plan="p"))
    data = result.to_dict()["data"]
    assert data["plan"]["status"] == "draft"
    assert data["plan"]["derived_status"] == "frozen"
    assert data["plan"]["status_consistent"] is False


# --------------------------------------------------------------------------- migration 0030 content


def _migration_0030() -> pathlib.Path:
    matched = sorted(MIGRATIONS_DIR.glob("0030*.sql"))
    assert len(matched) == 1, f"expected exactly one 0030*.sql migration, found {matched}"
    return matched[0]


def test_migration_0030_exists_exactly_once() -> None:
    _migration_0030()


def test_migration_0030_repairs_both_directions_idempotently() -> None:
    content = _migration_0030().read_text(encoding="utf-8")
    assert "UPDATE plan SET status = 'frozen'" in content
    assert "UPDATE plan SET status = 'draft'" in content
    # Idempotency guards so a re-run over an already-repaired table is a no-op.
    assert "status != 'frozen'" in content
    assert "status != 'draft'" in content
    # Repair keys off the step tree, matching plan_status_sync.derive_plan_status.
    assert "FROM step s WHERE s.plan_uuid = plan.uuid" in content


def _sql_body(path: pathlib.Path) -> str:
    """The file with comment lines stripped, so rollback-notes prose (which
    documents the manual, by-hand inverse commands) never matches a scan for
    live statements. Mirrors tests/test_cr6_migration_discipline_and_cascade_
    compat.py's `_body()`."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").split("\n")
        if not line.strip().startswith("--")
    )


def test_migration_0030_contains_no_destructive_ddl() -> None:
    content = _sql_body(_migration_0030()).upper()
    for forbidden in ("DROP TABLE", "DROP COLUMN", "DROP INDEX", "ALTER COLUMN", "TRUNCATE"):
        assert forbidden not in content


def test_migration_0030_never_touches_completed_column() -> None:
    """bug c3950b83's completion lock is a separate mechanism; the repair's
    actual SQL statements must not read or write plan.completed (the file's
    prose is allowed to mention it, to document why it stays untouched)."""
    assert "completed" not in _sql_body(_migration_0030()).lower()
