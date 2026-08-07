"""Regression tests for bug 1ddea076: with an open cascade, step_transition's
freeze gate (require_green=true) reported and reasoned about the plan HEAD
(the cascade's BASE revision, which never moves while a cascade is open)
instead of the cascade's live working TIP -- the exact state
plan_validate_command evaluates and reports as ``tip_revision_uuid``. Two
independent defects combined to produce the live symptom (a repaired,
green scope refused refreeze under require_green=true):

1. ``_run_transition_gate`` labeled its gate report with
   ``current_head_revision`` (the plan HEAD / cascade BASE) instead of the
   cascade's ref target (the working TIP), even though the mechanical gate
   itself (``run_gate``) always scans live table rows -- there is no
   separate "state at base" it could have read instead.
2. For every SCOPED (non-whole_plan) freeze, ``_run_transition_gate`` built
   its ``BranchScope`` with ``hrs_slice=[]`` hardcoded, instead of resolving
   it from the live paragraph table the way
   ``views.branch.resolve_branch_scope`` does for plan_validate_command.
   ``check_parse_sanity_counts`` (verify/gate_structure.py) then fired a
   spurious "branch hrs_slice is empty" finding on EVERY scoped freeze,
   independent of whether the plan's actual repaired material was green --
   this is what actually turned a plan_validate-green scope red under
   step_transition's freeze gate.

Layer 1 exercises ``_live_working_revision`` directly against a minimal
fake connection (bug requirement (a)/(b): tip named when a cascade is
open, head/base unchanged when it is not). Layer 2 exercises
``_hrs_slice_for`` together with the real ``check_parse_sanity_counts``
(no mocking) to prove the false-positive is gone. Layer 3 exercises
``_run_transition_gate`` end-to-end (module-level mocks, matching this
suite's established convention -- see test_step_transition_command.py and
test_bug_845b43a8_plan_status_freeze_sync.py) for the bug's own three
required scenarios: (a) tip-green scope succeeds and the report names the
tip, (b) no cascade leaves gate evaluation unchanged (base=head), (c)
red-at-tip still refuses.
"""
from __future__ import annotations

import uuid
from typing import Any

import plan_manager.commands.step_transition_command as mod
from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_structure import check_parse_sanity_counts
from plan_manager.views.branch import BranchScope

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
TIP_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000d3")
CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000d4")
CASCADE_NAME = "cascade/00000000-0000-0000-0000-0000000000d4"


# --------------------------------------------------------------------------- fakes


class _FakeCascadeRecord:
    def __init__(self, name: str) -> None:
        self.uuid = CASCADE_UUID
        self.name = name


class _FakeCursor:
    """Minimal fake psycopg cursor supporting the context-manager idiom used
    by get_open_cascade and list_paragraphs, dispatching by query prefix."""

    def __init__(self, cascade_row, paragraph_rows: list[tuple]):
        self._cascade_row = cascade_row
        self._paragraph_rows = paragraph_rows
        self._pending: list[tuple] = []
        self._one: tuple | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_FakeCursor":
        if query.startswith("SELECT uuid, plan_uuid, name, base_revision_uuid"):
            self._one = self._cascade_row
        elif query.startswith("SELECT uuid, plan_uuid, label, text, position"):
            self._pending = list(self._paragraph_rows)
        else:
            raise AssertionError(f"unexpected query in _FakeCursor: {query!r}")
        return self

    def fetchone(self) -> tuple | None:
        return self._one

    def fetchall(self) -> list[tuple]:
        return self._pending


class _FakeConn:
    """Minimal fake connection: .cursor() for get_open_cascade/
    list_paragraphs, .execute() directly for get_ref -- exactly the two
    idioms those store functions use."""

    def __init__(
        self,
        cascade_row: tuple | None = None,
        ref_revision: uuid.UUID | None = None,
        paragraph_rows: list[tuple] = (),
    ) -> None:
        self._cascade_row = cascade_row
        self._ref_revision = ref_revision
        self._paragraph_rows = list(paragraph_rows)

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._cascade_row, self._paragraph_rows)

    def execute(self, query: str, params: tuple = ()):
        if query.startswith("SELECT revision_uuid FROM ref"):
            value = self._ref_revision
            return _Rows([(value,)] if value is not None else [])
        raise AssertionError(f"unexpected query in _FakeConn.execute: {query!r}")


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


def _cascade_row() -> tuple:
    return (CASCADE_UUID, PLAN_UUID, CASCADE_NAME, HEAD_REVISION, "open", None)


def _step(step_uuid: uuid.UUID, level: int, step_id: str, parent, fields=None) -> Step:
    return Step(
        uuid=step_uuid,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields or {},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


# --------------------------------------------------------------------------- Layer 1: _live_working_revision


def test_live_working_revision_is_head_when_no_cascade_open() -> None:
    """Requirement (b): without a cascade, gate evaluation is unchanged
    (base == head)."""
    conn = _FakeConn(cascade_row=None)

    result = mod._live_working_revision(conn, PLAN_UUID, HEAD_REVISION)

    assert result == HEAD_REVISION


def test_live_working_revision_is_cascade_tip_when_cascade_open() -> None:
    """Requirement (a): with an open cascade, the resolved revision is the
    cascade ref's current target (the working tip), not the plan head."""
    conn = _FakeConn(cascade_row=_cascade_row(), ref_revision=TIP_REVISION)

    result = mod._live_working_revision(conn, PLAN_UUID, HEAD_REVISION)

    assert result == TIP_REVISION
    assert result != HEAD_REVISION


# --------------------------------------------------------------------------- Layer 2: _hrs_slice_for + real check_parse_sanity_counts


def test_hrs_slice_for_resolves_bound_paragraphs_like_resolve_branch_scope() -> None:
    gs = _step(uuid.uuid4(), 3, "G-001", None, fields={"source_labels": ["{aaaa}"]})
    conn = _FakeConn(paragraph_rows=[
        (uuid.uuid4(), PLAN_UUID, "aaaa", "text", 0),
    ])

    hrs_slice = mod._hrs_slice_for(conn, PLAN_UUID, gs)

    assert [p.label for p in hrs_slice] == ["aaaa"]


def test_scoped_freeze_gate_no_longer_false_positives_on_empty_hrs_slice() -> None:
    """The actual root-cause finding: a hardcoded hrs_slice=[] made
    check_parse_sanity_counts fire on every scoped freeze, regardless of
    the plan's real repaired state. With hrs_slice resolved from the live
    paragraph table (mirroring resolve_branch_scope), a branch that
    genuinely has bound paragraphs no longer produces this finding."""
    gs = _step(uuid.uuid4(), 3, "G-001", None, fields={"source_labels": ["{aaaa}"]})
    ts = _step(uuid.uuid4(), 4, "T-001", gs.uuid)
    atomic = _step(
        uuid.uuid4(), 5, "A-001", ts.uuid,
        fields={"target_file": "x.py", "operation": "modify_file", "priority": 1},
    )
    tree = GateTree(
        steps={s.uuid: s for s in (gs, ts, atomic)},
        concept_ids=[], relations=[], labels=[], counts={},
    )
    conn = _FakeConn(paragraph_rows=[(uuid.uuid4(), PLAN_UUID, "aaaa", "text", 0)])
    resolved_hrs_slice = mod._hrs_slice_for(conn, PLAN_UUID, gs)

    # Pre-fix behavior: hardcoded empty hrs_slice -> spurious finding.
    stale_branch = BranchScope(
        plan_uuid=PLAN_UUID, depth="as", gs=gs, ts=ts, atomic=atomic, hrs_slice=[]
    )
    stale_findings = check_parse_sanity_counts(tree, [gs, ts, atomic], stale_branch)
    assert len(stale_findings) == 1
    assert stale_findings[0].message == "branch hrs_slice is empty"

    # Post-fix behavior: hrs_slice resolved from the live paragraph table.
    fixed_branch = BranchScope(
        plan_uuid=PLAN_UUID, depth="as", gs=gs, ts=ts, atomic=atomic,
        hrs_slice=resolved_hrs_slice,
    )
    fixed_findings = check_parse_sanity_counts(tree, [gs, ts, atomic], fixed_branch)
    assert fixed_findings == []


# --------------------------------------------------------------------------- Layer 3: _run_transition_gate end to end (mocked run_gate)


class _GreenReport:
    green = True
    checks: list = []


class _RedReport:
    class _Check:
        findings = [object()]

    green = False
    checks = [_Check()]


class _Verdict:
    revision_uuid = HEAD_REVISION  # pre-fix label; the fix must not surface this


def _tree_with_one_branch() -> tuple[dict[uuid.UUID, Step], Step]:
    gs = _step(uuid.uuid4(), 3, "G-001", None, fields={"source_labels": ["{aaaa}"]})
    ts = _step(uuid.uuid4(), 4, "T-001", gs.uuid)
    atomic = _step(
        uuid.uuid4(), 5, "A-001", ts.uuid,
        fields={"target_file": "x.py", "operation": "modify_file", "priority": 1},
    )
    nodes = {s.uuid: s for s in (gs, ts, atomic)}
    return nodes, atomic


def test_scoped_freeze_gate_succeeds_and_names_tip_when_cascade_open_and_tip_is_green(
    monkeypatch,
) -> None:
    """Requirement (a): with an open cascade and a green scope, freeze with
    require_green=true succeeds and the gate report names the tip
    revision, not the base/head."""
    nodes, atomic = _tree_with_one_branch()
    conn = _FakeConn(cascade_row=_cascade_row(), ref_revision=TIP_REVISION)

    monkeypatch.setattr(mod, "run_gate", lambda conn, plan_uuid, branch=None, fail_fast=False: (_GreenReport(), _Verdict()))

    result = mod._run_transition_gate(conn, PLAN_UUID, nodes, [atomic], "G-001", HEAD_REVISION)

    assert result["green"] is True
    assert result["revision_uuid"] == str(TIP_REVISION)
    assert result["revision_uuid"] != str(HEAD_REVISION)


def test_scoped_freeze_gate_unchanged_without_a_cascade() -> None:
    """Requirement (b): without a cascade, gate evaluation is unchanged --
    the reported revision is the plan head, exactly as before this fix."""
    nodes, atomic = _tree_with_one_branch()
    conn = _FakeConn(
        cascade_row=None,
        paragraph_rows=[(uuid.uuid4(), PLAN_UUID, "aaaa", "text", 0)],
    )

    def fake_run_gate(conn, plan_uuid, branch=None, fail_fast=False):
        assert branch.hrs_slice, "hrs_slice must be resolved, not hardcoded empty"
        return _GreenReport(), _Verdict()

    import plan_manager.commands.step_transition_command as _mod
    orig = _mod.run_gate
    _mod.run_gate = fake_run_gate
    try:
        result = mod._run_transition_gate(conn, PLAN_UUID, nodes, [atomic], "G-001", HEAD_REVISION)
    finally:
        _mod.run_gate = orig

    assert result["green"] is True
    assert result["revision_uuid"] == str(HEAD_REVISION)


def test_scoped_freeze_gate_still_refuses_when_actually_red_at_tip(monkeypatch) -> None:
    """Requirement (c): a scope that is genuinely red (real findings, not
    the hrs_slice artifact) still refuses under an open cascade."""
    nodes, atomic = _tree_with_one_branch()
    conn = _FakeConn(cascade_row=_cascade_row(), ref_revision=TIP_REVISION)

    monkeypatch.setattr(mod, "run_gate", lambda conn, plan_uuid, branch=None, fail_fast=False: (_RedReport(), _Verdict()))

    result = mod._run_transition_gate(conn, PLAN_UUID, nodes, [atomic], "G-001", HEAD_REVISION)

    assert result["green"] is False
    assert result["revision_uuid"] == str(TIP_REVISION)
    assert result["finding_count"] == 1


def test_whole_plan_freeze_gate_names_tip_when_cascade_open(monkeypatch) -> None:
    """The whole_plan branch of _run_transition_gate must also report the
    tip, not the head, when a cascade is open (branch is None entirely, so
    the hrs_slice defect never applied here -- only the label did)."""
    nodes, atomic = _tree_with_one_branch()
    conn = _FakeConn(cascade_row=_cascade_row(), ref_revision=TIP_REVISION)

    monkeypatch.setattr(mod, "run_gate", lambda conn, plan_uuid, branch=None, fail_fast=False: (_GreenReport(), _Verdict()))

    result = mod._run_transition_gate(conn, PLAN_UUID, nodes, list(nodes.values()), "whole_plan", HEAD_REVISION)

    assert result["green"] is True
    assert result["revision_uuid"] == str(TIP_REVISION)
