"""Regression tests for bug 957c2f6a: a frozen plan must stay executable.

The status model has always declared frozen -> in_progress legal for an
atomic (level-5) step, and in_progress -> done legal for every atomic step.
The cascade admission regime, however, admits a direct step mutation only
when the target's status is draft or ready_for_review and nothing at, below,
or above it is frozen -- so step_set_status refused the very two transitions
the status model permits, and a frozen plan could not be executed at all
without opening an authoring cascade over frozen truth.

The fix exempts exactly those two transitions, in direct mode, on a level-5
step: executing an atomic step changes only its runtime lifecycle and never
its authored content, so the status model is the sole judge there. Nothing
else moves: cascade/regime.py's check_admission is untouched (18 call sites),
LEGAL_TRANSITIONS is untouched, and every other command still runs the full
regime.

Unit-style, no real database: constructed node maps plus command-level
monkeypatching, matching tests/test_frozen_subtree_membership_invariant.py.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.cascade import regime as regime_mod
from plan_manager.cascade.record import CascadeError, CascadeRecord
from plan_manager.commands import step_set_status_command, step_update_command
from plan_manager.commands.step_set_status_command import StepSetStatusCommand
from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.domain.status_model import validate_transition
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000957")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-000000000958")
NEW_REV = uuid.UUID("00000000-0000-0000-0000-000000000959")

GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000011")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000012")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000013")

_ATOMIC_FIELDS = {"target_file": "x.py", "operation": "modify_file", "priority": 1}


def _step(step_uuid, level, step_id, parent, status) -> Step:
    return Step(
        uuid=step_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=parent, level=level,
        step_id=step_id, slug=step_id.lower(),
        fields=dict(_ATOMIC_FIELDS) if level == 5 else {},
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _tree(gs_status: str, ts_status: str, as_status: str) -> dict[uuid.UUID, Step]:
    return {
        GS_UUID: _step(GS_UUID, 3, "G-001", None, gs_status),
        TS_UUID: _step(TS_UUID, 4, "T-001", GS_UUID, ts_status),
        AS_UUID: _step(AS_UUID, 5, "A-001", TS_UUID, as_status),
    }


def _frozen_tree(as_status: str = "frozen") -> dict[uuid.UUID, Step]:
    """The shape a fully frozen, ready-to-execute plan actually has."""
    return _tree("frozen", "frozen", as_status)


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REV
    completed = False


@contextmanager
def _fake_db():
    yield object()


def _open_cascade(name: str = "cascade/x") -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(), plan_uuid=PLAN_UUID, name=name,
        base_revision_uuid=HEAD_REV, status="open",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )


def _patch_set_status(monkeypatch, nodes, open_cascade=None) -> dict:
    """Wire step_set_status onto an in-memory tree, keeping the real judges.

    The status model stays real: the set_step_status double reproduces
    domain.step_ops.set_step_status exactly (validate then write), so an
    illegal transition still raises StatusTransitionError from the real
    matrix. The admission regime stays real too, reached through
    cascade.regime's own module-level names.

    `open_cascade` is installed on BOTH get_open_cascade bindings -- the
    regime's and the command's own, which the exemption probe uses -- since
    each module imported the collaborator into its own namespace.
    """
    calls: dict = {}
    monkeypatch.setattr(step_set_status_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_set_status_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_set_status_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_set_status_command, "get_open_cascade", lambda conn, plan_uuid: open_cascade
    )
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: open_cascade)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    def _set_step_status(conn, step_uuid, new_status, via_cascade=False):
        step = nodes[step_uuid]
        validate_transition(
            step.status, new_status, is_atomic_step=(step.level == 5), via_cascade=via_cascade
        )
        step.status = new_status

    monkeypatch.setattr(step_set_status_command, "set_step_status", _set_step_status)
    monkeypatch.setattr(step_set_status_command, "get_step", lambda conn, step_uuid: nodes[step_uuid])

    def _rev(conn, plan_uuid, actor, message, changes, parent, ref_name=None, **kwargs):
        calls["revision"] = {"message": message, "ref_name": ref_name}
        calls["carry_forward_paths"] = kwargs.get("carry_forward_paths")
        return NEW_REV

    monkeypatch.setattr(step_set_status_command, "record_revision", _rev)

    def _cascade_write(conn, plan_uuid, rec, node_uuid, snapshot, updates, actor, message, paths=None):
        calls["cascade_write"] = {"message": message, "carry_forward_paths": paths}
        return NEW_REV

    monkeypatch.setattr(step_set_status_command, "cascade_write", _cascade_write)
    monkeypatch.setattr(step_set_status_command, "step_invalidation", lambda nodes_, target: [])
    return calls


def _run(**kwargs):
    return asyncio.run(StepSetStatusCommand().execute(plan="p", **kwargs)).to_dict()


def _domain_code(payload) -> str:
    return payload["error"]["data"]["domain_code"]


# ------------------------------------------- (a) the two exempted transitions


def test_frozen_atomic_step_starts_execution_directly(monkeypatch) -> None:
    nodes = _frozen_tree()
    calls = _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status="in_progress")

    assert payload["success"] is True
    assert payload["data"]["status"] == "in_progress"
    assert nodes[AS_UUID].status == "in_progress"
    # Direct mode: the plan head advances, the cascade path is never taken.
    assert calls["revision"]["ref_name"] is None
    assert "cascade_write" not in calls


def test_in_progress_atomic_step_completes_directly(monkeypatch) -> None:
    nodes = _frozen_tree("in_progress")
    calls = _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status="done")

    assert payload["success"] is True
    assert payload["data"]["status"] == "done"
    assert calls["revision"]["ref_name"] is None


def test_execution_start_scopes_block_invalidation_to_the_executed_step(monkeypatch) -> None:
    """Bug fa15d288 must cover this call site: starting execution on one
    atomic step may not stale the whole plan's context blocks."""
    nodes = _frozen_tree()
    calls = _patch_set_status(monkeypatch, nodes)

    _run(step_id="A-001", status="in_progress")

    assert calls["carry_forward_paths"] == ["G-001/T-001/A-001"]


# ------------------------------------------------ (b)(c) the exemption's edges


@pytest.mark.parametrize("step_id", ["G-001", "T-001"])
def test_non_atomic_frozen_steps_still_require_a_cascade(monkeypatch, step_id) -> None:
    nodes = _frozen_tree()
    _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id=step_id, status="in_progress")

    assert payload["success"] is False
    assert _domain_code(payload) == "FROZEN_ARTIFACT"


@pytest.mark.parametrize("status", ["draft", "ready_for_review", "needs_review", "done"])
def test_other_targets_out_of_frozen_are_still_refused_on_an_atomic_step(monkeypatch, status) -> None:
    """The exemption is keyed on the exact transition, not on frozen-ness."""
    nodes = _frozen_tree()
    _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status=status)

    assert payload["success"] is False
    assert _domain_code(payload) == "FROZEN_ARTIFACT"
    assert nodes[AS_UUID].status == "frozen"


# ------------------------------------------------- (d) no new entry points


@pytest.mark.parametrize("current", ["draft", "ready_for_review"])
def test_in_progress_is_still_unreachable_from_the_authoring_statuses(monkeypatch, current) -> None:
    nodes = _tree("draft", "draft", current)
    _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status="in_progress")

    assert payload["success"] is False
    assert _domain_code(payload) == "INVALID_TRANSITION"
    assert nodes[AS_UUID].status == current


def test_completion_is_direct_on_an_unfrozen_tree_too(monkeypatch) -> None:
    """in_progress -> done never depended on freezing.

    in_progress is not a directly-mutable status either, so before the fix
    the regime refused completion on ANY atomic step, frozen tree or not.
    The exemption is keyed on the transition, so this path is now direct.
    """
    nodes = _tree("draft", "draft", "in_progress")
    calls = _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status="done")

    assert payload["success"] is True
    assert nodes[AS_UUID].status == "done"
    assert calls["revision"]["ref_name"] is None


# ---------------------------------- (e) the exemption is step_set_status only


def test_step_update_on_a_frozen_atomic_step_is_still_refused(monkeypatch) -> None:
    nodes = _frozen_tree()
    monkeypatch.setattr(step_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_update_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_update_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_update_command, "list_concept_ids", lambda conn, plan_uuid: [])
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="A-001", fields={"priority": 2})
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert _domain_code(payload) == "FROZEN_ARTIFACT"
    assert nodes[AS_UUID].fields["priority"] == 1


# --------------------------------------------------- (f) the cascade path


def test_supplying_a_cascade_uuid_still_goes_through_the_regime(monkeypatch) -> None:
    """The exemption is direct-mode only; a supplied cascade still admits."""
    nodes = _frozen_tree()
    rec = _open_cascade()
    calls = _patch_set_status(monkeypatch, nodes, open_cascade=rec)

    payload = _run(step_id="A-001", status="in_progress", cascade_uuid=str(rec.uuid))

    assert payload["success"] is True
    assert "cascade_write" in calls
    assert "revision" not in calls


def test_a_mismatched_cascade_uuid_is_still_a_conflict(monkeypatch) -> None:
    nodes = _frozen_tree()
    _patch_set_status(monkeypatch, nodes)

    payload = _run(step_id="A-001", status="in_progress", cascade_uuid=str(uuid.uuid4()))

    assert payload["success"] is False
    assert _domain_code(payload) == "CASCADE_CONFLICT"


# ----------------- the exemption never bypasses the open-cascade discipline


def test_an_open_cascade_refuses_a_direct_execution_transition(monkeypatch) -> None:
    """While a cascade is open it is the plan's single write channel.

    The exemption must narrow the regime's verdict, never widen its write
    channel: a direct (no cascade_uuid) execution transition during an open
    cascade must be refused, so the plan head cannot advance behind the
    cascade's back and no block is re-tagged.
    """
    nodes = _frozen_tree()
    calls = _patch_set_status(monkeypatch, nodes, open_cascade=_open_cascade())

    payload = _run(step_id="A-001", status="in_progress")

    assert payload["success"] is False
    assert _domain_code(payload) == "FROZEN_ARTIFACT"
    assert nodes[AS_UUID].status == "frozen"
    # No head advance and no carry-forward: the write never happened.
    assert "revision" not in calls
    assert "cascade_write" not in calls
    assert calls.get("carry_forward_paths") is None


def test_an_open_cascade_refuses_direct_completion_on_an_unfrozen_tree(monkeypatch) -> None:
    """Same rule with no frozen step anywhere: the refusal is the open
    cascade, reported as CASCADE_REQUIRED rather than FROZEN_ARTIFACT."""
    nodes = _tree("draft", "draft", "in_progress")
    calls = _patch_set_status(monkeypatch, nodes, open_cascade=_open_cascade())

    payload = _run(step_id="A-001", status="done")

    assert payload["success"] is False
    assert _domain_code(payload) == "CASCADE_REQUIRED"
    assert nodes[AS_UUID].status == "in_progress"
    assert "revision" not in calls


def test_an_open_cascade_admits_the_execution_transition_with_its_own_uuid(monkeypatch) -> None:
    """The cascade path is the way through during an open cascade."""
    nodes = _frozen_tree()
    rec = _open_cascade()
    calls = _patch_set_status(monkeypatch, nodes, open_cascade=rec)

    payload = _run(step_id="A-001", status="in_progress", cascade_uuid=str(rec.uuid))

    assert payload["success"] is True
    assert nodes[AS_UUID].status == "in_progress"
    assert calls["cascade_write"]["carry_forward_paths"] == ["G-001/T-001/A-001"]
    assert "revision" not in calls


# --------------------------- (g) pinning the regime's status disjunct itself


@pytest.mark.parametrize("status", ["frozen", "in_progress", "done", "needs_review"])
def test_check_admission_refuses_every_non_direct_status(monkeypatch, status) -> None:
    """cascade/regime.py's `status not in DIRECT_STATUSES` disjunct.

    Only draft and ready_for_review are directly mutable. For in_progress,
    done and needs_review no step in the tree is frozen, so neither
    frozen_at_or_below nor frozen_ancestor can fire and this disjunct is the
    sole reason for the refusal.
    """
    nodes = _tree("draft", "draft", status)
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    with pytest.raises(CascadeError):
        regime_mod.check_admission(object(), PLAN_UUID, "step", AS_UUID, None)


@pytest.mark.parametrize("status", ["draft", "ready_for_review"])
def test_check_admission_still_admits_the_two_direct_statuses(monkeypatch, status) -> None:
    nodes = _tree("draft", "draft", status)
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    assert regime_mod.check_admission(object(), PLAN_UUID, "step", AS_UUID, None) is None
