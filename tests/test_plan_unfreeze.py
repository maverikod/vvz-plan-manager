"""Regression tests for defect d01b3bc6: a fully-frozen plan must be
un-unfreezable through the new plan_unfreeze command, without weakening the
public cascade_begin frozen-truth guard.

All tests are unit-style with the established monkeypatch _fake_db / fake-conn
pattern (no real database), matching test_step_transition_fast_fail.py and
test_hotfix_cascade_all_steps_frozen.py.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from plan_manager.cascade import begin as begin_mod
from plan_manager.cascade.record import CascadeError, CascadeRecord
from plan_manager.commands import plan_unfreeze_command, step_transition_command
from plan_manager.commands.plan_unfreeze_command import PlanUnfreezeCommand
from plan_manager.commands.step_transition_command import StepTransitionCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
from plan_manager.domain.step import Step
from plan_manager.storage import runtime_audit_store


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


# --------------------------------------------------------------------------- helpers


@contextmanager
def _fake_db():
    yield object()


def _plan(name: str = "throwaway") -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name=name,
        status="draft",
        context_budget=4000,
        head_revision_uuid=HEAD_REV,
        project_ids=[],
        primary_project_id=None,
    )


def _step(step_uuid: str, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=uuid.UUID(step_uuid), plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _frozen_tree() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "frozen")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "frozen")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "frozen")
    return {s.uuid: s for s in (gs, ts, atomic)}


class _AuditRecord:
    def __init__(self) -> None:
        self.audit_uuid = uuid.uuid4()


class _FakeCascade:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = f"cascade/{self.uuid}"


def _cascade_record() -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        name="cascade/x",
        base_revision_uuid=HEAD_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


# ------------------------------------------------------- begin.py: internal bypass


class _StepConn:
    """Fake connection answering the two EXISTS probes of _all_steps_frozen."""

    def __init__(self, has_steps: bool, has_non_frozen: bool) -> None:
        self._has_steps = has_steps
        self._has_non_frozen = has_non_frozen

    def execute(self, sql, params=()):
        value = self._has_non_frozen if "status != 'frozen'" in sql else self._has_steps

        class _Cur:
            def fetchone(self_inner):
                return (value,)

        return _Cur()


def _patch_begin(monkeypatch, plan: Plan) -> dict:
    calls: dict = {}
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: plan)
    monkeypatch.setattr(begin_mod, "create_ref", lambda conn, pu, name, rev: calls.setdefault("ref", name))
    monkeypatch.setattr(begin_mod, "insert_cascade", lambda conn, rec: calls.setdefault("rec", rec))
    return calls


def test_public_begin_cascade_still_refuses_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(conn, plan.uuid)


def test_internal_bypass_opens_cascade_on_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    rec = begin_mod.begin_cascade(conn, plan.uuid, allow_all_frozen=True)
    assert rec.status == "open"
    assert "rec" in calls


def test_internal_bypass_still_refuses_plan_status_frozen(monkeypatch) -> None:
    plan = _plan()
    object.__setattr__(plan, "status", "frozen")
    _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(conn, plan.uuid, allow_all_frozen=True)


# ------------------------------------------------------- audit store accepts action


def test_runtime_audit_store_accepts_plan_unfreeze_action() -> None:
    assert "plan_unfreeze" in runtime_audit_store.ALLOWED_ACTIONS

    captured: dict = {}

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        @contextmanager
        def transaction(self):
            """Minimal stand-in for psycopg's savepoint-aware transaction() context manager (bug 1e13649f: record_runtime_change wraps plan-anchored inserts in a nested transaction to recover from a dangling plan anchor)."""
            yield self

    rec = runtime_audit_store.record_runtime_change(
        _Conn(),
        plan_uuid=PLAN_UUID,
        entity_type="plan",
        entity_id=PLAN_UUID,
        action="plan_unfreeze",
        changed_by="orchestrator",
        change_reason="reopen",
        changed_fields={"head_revision_uuid": str(HEAD_REV)},
    )
    assert rec.action == "plan_unfreeze"
    # CR-7 G-004: the routed store binds through psycopg sql.Composed;
    # render it the way psycopg would before asserting on the statement.
    _sql = captured["sql"]
    _rendered = (_sql.as_string(None) if hasattr(_sql, "as_string") else str(_sql)).replace('"', "")
    assert "INSERT INTO runtime_audit_log" in _rendered


# ------------------------------------------------------- plan_unfreeze command


def _patch_unfreeze(monkeypatch, *, all_frozen: bool, open_cascade, plan: Plan) -> dict:
    calls: dict = {}
    monkeypatch.setattr(plan_unfreeze_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_unfreeze_command, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(plan_unfreeze_command, "_all_steps_frozen", lambda conn, pu: all_frozen)
    monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", lambda conn, pu: open_cascade)

    def _set_status(conn, plan_uuid, status):
        calls.setdefault("set_plan_status_calls", []).append((plan_uuid, status))

    monkeypatch.setattr(plan_unfreeze_command, "set_plan_status", _set_status)

    def _audit(conn, **kwargs):
        calls["audit"] = kwargs
        return _AuditRecord()

    monkeypatch.setattr(plan_unfreeze_command, "record_runtime_change", _audit)

    def _begin(conn, pu, allow_all_frozen=False):
        calls["begin_allow_all_frozen"] = allow_all_frozen
        rec = _cascade_record()
        calls["cascade"] = rec
        return rec

    monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _begin)
    # get_open_cascade is called twice: pre-check and post-open re-read verify.
    if open_cascade is None:
        state = {"opened": None}

        def _get_open(conn, pu):
            return state["opened"]

        def _begin2(conn, pu, allow_all_frozen=False):
            calls["begin_allow_all_frozen"] = allow_all_frozen
            rec = _cascade_record()
            calls["cascade"] = rec
            state["opened"] = rec
            return rec

        monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", _get_open)
        monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _begin2)
    return calls


def test_plan_unfreeze_opens_audited_cascade_on_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=None, plan=plan)

    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="orchestrator", reason="reopen for fix")
    )
    payload = result.to_dict()
    assert payload["success"] is True
    data = payload["data"]
    assert data["cascade_uuid"] == str(calls["cascade"].uuid)
    assert data["plan_uuid"] == str(PLAN_UUID)
    assert "audit_uuid" in data
    assert "step_transition" in data["next_steps"]
    # audited with the mandated fields, bypass flag set only for this door.
    assert calls["audit"]["action"] == "plan_unfreeze"
    assert calls["audit"]["changed_by"] == "orchestrator"
    assert calls["audit"]["change_reason"] == "reopen for fix"
    assert calls["audit"]["entity_type"] == "plan"
    # Bug 74ba4313: the record must name the opened cascade so the begin
    # side of the provenance chain is verifiable from audit_list.
    assert calls["audit"]["changed_fields"] == {
        "head_revision_uuid": str(HEAD_REV),
        "cascade_uuid": str(calls["cascade"].uuid),
    }
    assert calls["begin_allow_all_frozen"] is True
    # Bug 845b43a8: opening the cascade must reset plan.status to 'draft' in
    # the same operation, even though the step tree is still all-frozen.
    assert calls["set_plan_status_calls"] == [(PLAN_UUID, "draft")]


def test_plan_unfreeze_refuses_not_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=False, open_cascade=None, plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "PLAN_NOT_FULLY_FROZEN"
    assert "audit" not in calls  # no audit, no cascade opened on refusal
    assert "set_plan_status_calls" not in calls  # no status reset on refusal


def test_plan_unfreeze_refuses_open_cascade(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=_cascade_record(), plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"
    assert "audit" not in calls
    assert "set_plan_status_calls" not in calls


@pytest.mark.parametrize(
    "changed_by,reason",
    [("", "r"), ("   ", "r"), ("o", ""), ("o", "   ")],
)
def test_plan_unfreeze_refuses_empty_actor_or_reason(monkeypatch, changed_by, reason) -> None:
    plan = _plan()
    _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=None, plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by=changed_by, reason=reason)
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"


# --------------------------------------- bug ecced710: unfreeze on frozen status


def _plan_with_status(status: str) -> Plan:
    return Plan(
        uuid=PLAN_UUID, name="throwaway", status=status, context_budget=4000,
        head_revision_uuid=HEAD_REV, project_ids=[], primary_project_id=None,
    )


def test_plan_unfreeze_succeeds_end_to_end_against_real_begin_cascade_on_frozen_status(monkeypatch) -> None:
    """Regression for bug ecced710: fix bea106c (bug 845b43a8) added a
    plan.status == 'frozen' refusal to begin_cascade that is unconditional
    -- allow_all_frozen does NOT relax it (see test_internal_bypass_still_
    refuses_plan_status_frozen above). Once plan.status is truthfully kept
    in sync with the step tree, a fully frozen plan's status IS 'frozen'
    at the moment plan_unfreeze wants to open its cascade, so calling the
    real begin_cascade before resetting the aggregate would always hit
    that guard. Exercises the REAL begin_cascade (plan_unfreeze_command's
    begin_cascade is never stubbed here) with only its storage-layer
    collaborators faked, proving set_plan_status runs -- and is visible to
    begin_cascade's own get_plan() re-read -- strictly before begin_cascade
    is called.
    """
    plan = _plan_with_status("frozen")
    status_box = {"status": "frozen"}
    cascade_box: dict = {"open": None}

    monkeypatch.setattr(plan_unfreeze_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_unfreeze_command, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(plan_unfreeze_command, "_all_steps_frozen", lambda conn, pu: True)
    monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", lambda conn, pu: cascade_box["open"])

    def _set_status(conn, plan_uuid, status):
        status_box["status"] = status

    monkeypatch.setattr(plan_unfreeze_command, "set_plan_status", _set_status)

    def _audit(conn, **kwargs):
        return _AuditRecord()

    monkeypatch.setattr(plan_unfreeze_command, "record_runtime_change", _audit)

    # NOT stubbing plan_unfreeze_command.begin_cascade: it stays bound to
    # the real plan_manager.cascade.begin.begin_cascade. Fake only what
    # THAT function reaches into.
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: _plan_with_status(status_box["status"]))
    monkeypatch.setattr(begin_mod, "create_ref", lambda conn, pu, name, rev: None)

    def _insert_cascade(conn, rec):
        cascade_box["open"] = rec

    monkeypatch.setattr(begin_mod, "insert_cascade", _insert_cascade)

    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="orchestrator", reason="reopen for fix")
    )
    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert status_box["status"] == "draft"
    assert cascade_box["open"] is not None


def test_plan_unfreeze_resets_status_before_calling_begin_cascade(monkeypatch) -> None:
    """Order assertion: the set_plan_status(draft) write must happen before
    begin_cascade is invoked, not after -- that ordering (not just the
    fact both calls occur) is what lets begin_cascade's own status=='frozen'
    guard see 'draft' instead of 'frozen'."""
    plan = _plan()
    order: list[str] = []
    cascade_box: dict = {"open": None}

    monkeypatch.setattr(plan_unfreeze_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_unfreeze_command, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(plan_unfreeze_command, "_all_steps_frozen", lambda conn, pu: True)
    monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", lambda conn, pu: cascade_box["open"])

    def _set_status(conn, plan_uuid, status):
        order.append("set_plan_status")

    monkeypatch.setattr(plan_unfreeze_command, "set_plan_status", _set_status)

    def _begin(conn, pu, allow_all_frozen=False):
        order.append("begin_cascade")
        rec = _cascade_record()
        cascade_box["open"] = rec
        return rec

    monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _begin)

    def _audit(conn, **kwargs):
        return _AuditRecord()

    monkeypatch.setattr(plan_unfreeze_command, "record_runtime_change", _audit)

    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    assert result.to_dict()["success"] is True
    assert order == ["set_plan_status", "begin_cascade"]


class _TxConn:
    """Fake connection adding the commit/rollback bookkeeping plan_manager.
    runtime.context.db_connection performs around a real psycopg
    connection, so a test can prove the plan.status write is undone
    together with the failed begin_cascade attempt. Mirrors test_bug_
    845b43a8_plan_status_freeze_sync.py's _TxConn/_tx_scoped_db."""

    def __init__(self) -> None:
        self.log: list[tuple[str, tuple]] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, sql, params=()):
        self.log.append((sql, tuple(params) if params else ()))
        return None


@contextmanager
def _tx_scoped_db(conn: _TxConn):
    try:
        yield conn
        conn.committed = True
    except BaseException:
        conn.rolled_back = True
        raise


def test_plan_unfreeze_begin_cascade_failure_leaves_status_unchanged(monkeypatch) -> None:
    """Atomicity: if begin_cascade fails for any reason after plan_unfreeze
    has already issued the plan.status='draft' UPDATE (same conn), the
    whole `with db_connection()` block must exit by exception so the
    surrounding transaction rolls back -- including that status write --
    rather than leaving the aggregate stuck on 'draft' with no cascade
    opened to justify it. Uses the REAL set_plan_status (not stubbed), so
    the UPDATE is genuinely issued against the fake conn's execute(), and
    a real commit/rollback-tracking db_connection stand-in."""
    plan = _plan()
    conn = _TxConn()

    @contextmanager
    def _fake_tx_db():
        with _tx_scoped_db(conn) as c:
            yield c

    monkeypatch.setattr(plan_unfreeze_command, "db_connection", _fake_tx_db)
    monkeypatch.setattr(plan_unfreeze_command, "resolve_plan", lambda c, p: plan)
    monkeypatch.setattr(plan_unfreeze_command, "_all_steps_frozen", lambda c, pu: True)
    monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", lambda c, pu: None)

    def _boom(c, pu, allow_all_frozen=False):
        raise CascadeError("simulated begin_cascade failure")

    monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _boom)

    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"

    # The status UPDATE was issued (proving it ran, atomically, before the
    # failure) but the surrounding transaction rolled back, not committed --
    # so nothing partial was ever made durable.
    status_updates = [entry for entry in conn.log if entry[0].startswith("UPDATE plan SET status")]
    assert status_updates == [("UPDATE plan SET status = %s WHERE uuid = %s", ("draft", PLAN_UUID))]
    assert conn.rolled_back is True
    assert conn.committed is False


# --------------------------------- end-to-end former-deadlock, then reopen succeeds


def test_step_transition_frozen_to_draft_refused_without_cascade(monkeypatch) -> None:
    """The deadlock's first wall: reopening a frozen step needs a cascade."""
    nodes = _frozen_tree()
    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(plan="p", to_status="draft", step_id="A-001")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"


def test_scoped_frozen_to_draft_succeeds_under_cascade(monkeypatch) -> None:
    """After plan_unfreeze opens the cascade, the scoped reopen is admitted."""
    nodes = _frozen_tree()
    cascade = _FakeCascade()
    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_transition_command, "check_admission",
        lambda conn, plan_uuid, kind, step_uuid, cid: cascade,
    )

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="draft", step_id="A-001",
            cascade_uuid=str(cascade.uuid), dry_run=True,
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["transitioned"][0]["from"] == "frozen"
    assert payload["data"]["transitioned"][0]["to"] == "draft"
