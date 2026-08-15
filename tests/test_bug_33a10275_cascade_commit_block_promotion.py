"""Regression tests for bug 33a10275: context blocks compiled under a cascade
must survive cascade_commit.

commit_cascade publishes the cascade tip revision AS the new head (same
revision uuid, identical plan truth), but blocks compiled under the cascade
carry cascade_uuid=<cascade>. Post-commit currency filters require
cascade_uuid IS NULL, so pre-fix every common block read as stale on the very
revision the commit gate had just proven green ("a green cascade gate commits
to a red head"). The fix re-tags the tip's cascade blocks to head blocks
inside commit_cascade, after the head advances and before the cascade record
closes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import plan_manager.cascade.close as close_mod
import plan_manager.views.context_blocks as context_blocks_mod
from plan_manager.cascade.close import CommitRefusedError, commit_cascade
from plan_manager.cascade.record import CascadeRecord
from plan_manager.views.context_blocks import promote_cascade_blocks_to_head


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000a10")
BASE_REV = uuid.UUID("00000000-0000-0000-0000-000000000a11")
TIP_REV = uuid.UUID("00000000-0000-0000-0000-000000000a12")


def _open_cascade() -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        name="cascade/x",
        base_revision_uuid=BASE_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


class _Check:
    findings: list = []


class _Report:
    green = True
    checks = [_Check()]


class _RedReport(_Report):
    green = False


class _Verdict:
    revision_uuid = TIP_REV


def _wire(monkeypatch, rec: CascadeRecord, events: list, report=_Report):
    monkeypatch.setattr(close_mod, "acquire_plan_lock", lambda conn, p: None)
    monkeypatch.setattr(close_mod, "release_plan_lock", lambda conn, p: None)
    monkeypatch.setattr(close_mod, "get_open_cascade", lambda conn, p: rec)
    monkeypatch.setattr(close_mod, "run_gate", lambda conn, p, **_kw: (report(), _Verdict()))
    monkeypatch.setattr(close_mod, "get_ref", lambda conn, p, name: TIP_REV)
    monkeypatch.setattr(
        close_mod, "set_head_revision",
        lambda conn, p, tip: events.append(("set_head", tip)),
    )
    # commit_cascade imports the promotion helper lazily (import-cycle guard),
    # so the patch targets the owning views module, not close_mod.
    monkeypatch.setattr(
        context_blocks_mod, "promote_cascade_blocks_to_head",
        lambda conn, p, cascade_uuid, tip: events.append(("promote", p, cascade_uuid, tip)) or 3,
    )
    monkeypatch.setattr(
        close_mod, "close_cascade",
        lambda conn, cascade_uuid, status: events.append(("close", status)),
    )
    monkeypatch.setattr(
        close_mod, "delete_ref",
        lambda conn, p, name: events.append(("delete_ref", name)),
    )


def test_commit_promotes_tip_cascade_blocks_after_head_advance(monkeypatch) -> None:
    rec = _open_cascade()
    events: list = []
    _wire(monkeypatch, rec, events)

    commit_cascade(object(), PLAN_UUID)

    assert ("promote", PLAN_UUID, rec.uuid, TIP_REV) in events
    order = [name for name, *_ in events]
    assert order.index("promote") > order.index("set_head")
    assert order.index("promote") < order.index("close")


def test_red_gate_refuses_commit_without_promoting(monkeypatch) -> None:
    rec = _open_cascade()
    events: list = []
    _wire(monkeypatch, rec, events, report=_RedReport)

    with pytest.raises(CommitRefusedError):
        commit_cascade(object(), PLAN_UUID)

    assert events == []


def test_promote_retags_only_the_committed_cascade_tip_rows() -> None:
    captured: dict = {}

    class _Result:
        rowcount = 7

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = " ".join(sql.split())
            captured["params"] = params
            return _Result()

    cascade_uuid = uuid.uuid4()
    promoted = promote_cascade_blocks_to_head(_Conn(), PLAN_UUID, cascade_uuid, TIP_REV)

    assert promoted == 7
    assert captured["sql"] == (
        "UPDATE context_block SET cascade_uuid = NULL "
        "WHERE plan_uuid = %s AND cascade_uuid = %s AND revision_uuid = %s"
    )
    assert captured["params"] == (PLAN_UUID, cascade_uuid, TIP_REV)
