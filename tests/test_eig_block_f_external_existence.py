"""Tests for EIG block F (todo 763ae29e): CA-backed existence checks with a
degraded policy.

Two layers, mirroring the split the block itself introduced:

- ``plan_manager.runtime.ca_files_probe.list_project_files_probe``: the
  transport primitive that reads one project's whole project-relative file
  inventory from the live CA. Never raises; every failure mode (unconfigured,
  unreachable, malformed, too large to read completely, partially read) folds
  into ``ExternalFilesProbe(available=False, reason="ca_unreachable")``. An
  EMPTY project is emphatically NOT a failure -- it is an available probe with
  an empty file set, and the checks must be able to red on it.
- ``plan_manager.verify.gate_execution_existence`` plus the re-enabled
  ``gate_execution._detect_orphan_verification``: pure checks over an
  in-memory GateTree and a probe, exactly the convention
  tests/test_eig_block_e1_gate_execution.py established (no live Postgres, no
  live CA).

The degraded matrix is the block's whole safety story and is pinned twice
below -- per check and through ``run_all``: probe None emits nothing at all;
an unavailable probe emits nothing unless
``require_project_verification`` is set, in which case it emits EXACTLY ONE
plan-level ``external_project_unverified`` finding and nothing else. Only an
AVAILABLE probe produces per-step verdicts.

The caller wiring (plan_validate) and the full 12-check_id report live in
tests/test_eig_block_f_plan_validate_wiring.py.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.runtime import ca_files_probe
from plan_manager.runtime.ca_files_probe import (
    ExternalFilesProbe,
    list_project_files_probe,
)
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_execution import (
    _detect_orphan_verification,
    check_no_orphan_verification,
)
from plan_manager.verify.gate_execution import run_all as run_execution_integrity_checks
from plan_manager.verify.gate_execution_existence import (
    check_artifact_producer_exists,
    check_external_project_unverified,
    check_modify_file_context_available,
    check_verification_target_resolvable,
)
from plan_manager.verify.gate_execution_existence import run_all as run_existence_checks
from plan_manager.views.step_paths import parent_path

PLAN = uuid.uuid4()


# ---------------------------------------------------------------------------
# Layer 1: the probe primitive, against a FAKED CA client.
# ---------------------------------------------------------------------------


def _immediate(data: dict) -> dict:
    """The real execute_command_unified "immediate" envelope shape."""
    return {"mode": "immediate", "command": "x", "result": {"success": True, "data": data}}


def _queued(data: dict) -> dict:
    """The real (double-wrapped) execute_command_unified "queued" envelope shape."""
    return {
        "mode": "queued",
        "command": "x",
        "job_id": "job-1",
        "status": "completed",
        "result": {"job_id": "job-1", "command": "x", "result": {"success": True, "data": data}},
    }


class _FakeRpc:
    def __init__(self, pages: list[dict] | None = None, exc: Exception | None = None):
        self._pages = pages or []
        self._exc = exc
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def execute_command_unified(self, command, params, *, auto_poll, timeout):
        self.calls.append((command, dict(params)))
        assert command == "list_project_files"
        assert auto_poll is True
        if self._exc is not None:
            raise self._exc
        index = params["block_position"] - 1
        if index >= len(self._pages):
            raise AssertionError(f"probe asked for page {index + 1}; only {len(self._pages)} faked")
        return self._pages[index]

    async def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self, rpc: _FakeRpc):
        self.rpc = rpc


def _patch_client(monkeypatch, rpc: _FakeRpc) -> None:
    monkeypatch.setattr(
        ca_files_probe,
        "_client_from_url",
        lambda base_url, *, timeout, cert, key, ca: _FakeClient(rpc),
    )


def _page(paths: list[str], total: int) -> dict:
    return _immediate(
        {"files": [{"relative_path": p} for p in paths], "count": len(paths), "total": total}
    )


def _probe(**overrides):
    params = dict(ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), timeout=1.0)
    params.update(overrides)
    return list_project_files_probe(**params)


def test_probe_unconfigured_ca_is_unavailable_without_contacting_the_transport(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("CA transport must not be contacted when ca_url is unconfigured")

    monkeypatch.setattr(ca_files_probe, "_client_from_url", _boom)
    result = _probe(ca_url=None)
    assert result == ExternalFilesProbe(available=False, reason="ca_unreachable", files=frozenset())


def test_probe_reads_a_single_page_project(monkeypatch):
    rpc = _FakeRpc(pages=[_page(["src/a.py", "src/b.py"], total=2)])
    _patch_client(monkeypatch, rpc)

    result = _probe()

    assert result.available is True
    assert result.reason is None
    assert result.files == frozenset({"src/a.py", "src/b.py"})
    assert [call[1]["block_position"] for call in rpc.calls] == [1]
    assert rpc.closed is True


def test_probe_of_an_empty_project_is_available_with_an_empty_file_set(monkeypatch):
    """An empty project is knowledge, not failure: available=True with no
    files, so a plan modifying a file there is legitimately redded."""
    _patch_client(monkeypatch, _FakeRpc(pages=[_page([], total=0)]))

    result = _probe()

    assert result.available is True
    assert result.reason is None
    assert result.files == frozenset()


def test_probe_pages_through_a_multi_page_listing(monkeypatch):
    first = [f"src/mod_{i:03d}.py" for i in range(ca_files_probe._PAGE_SIZE)]
    second = ["src/tail_one.py", "src/tail_two.py"]
    total = len(first) + len(second)
    rpc = _FakeRpc(pages=[_page(first, total=total), _page(second, total=total)])
    _patch_client(monkeypatch, rpc)

    result = _probe()

    assert result.available is True
    assert result.files == frozenset(first) | frozenset(second)
    assert [call[1]["block_position"] for call in rpc.calls] == [1, 2]
    assert {call[1]["page_size"] for call in rpc.calls} == {ca_files_probe._PAGE_SIZE}


def test_probe_accepts_the_items_key_through_a_queued_envelope(monkeypatch):
    page = _queued({"items": [{"relative_path": "src/a.py"}], "count": 1, "total": 1})
    _patch_client(monkeypatch, _FakeRpc(pages=[page]))

    assert _probe().files == frozenset({"src/a.py"})


def test_probe_transport_exception_is_unavailable(monkeypatch):
    _patch_client(monkeypatch, _FakeRpc(exc=RuntimeError("connection refused")))

    result = _probe()

    assert result.available is False
    assert result.reason == "ca_unreachable"
    assert result.files == frozenset()


def test_probe_malformed_payload_is_unavailable(monkeypatch):
    _patch_client(monkeypatch, _FakeRpc(pages=[_immediate({"not_files": []})]))

    assert _probe().available is False


def test_probe_refuses_a_listing_larger_than_the_page_cap(monkeypatch):
    """A truncated inventory would make existing files look missing and red an
    innocent plan, so an oversized project folds to unavailable after ONE call."""
    oversized = ca_files_probe._MAX_FILE_PAGES * ca_files_probe._PAGE_SIZE + 1
    rpc = _FakeRpc(pages=[_page([f"src/m{i}.py" for i in range(5)], total=oversized)])
    _patch_client(monkeypatch, rpc)

    result = _probe()

    assert result.available is False
    assert result.reason == "ca_unreachable"
    assert len(rpc.calls) == 1


def test_probe_refuses_an_incomplete_read(monkeypatch):
    """A short page against a larger 'total' means the server stopped feeding
    us rows; that partial view must never be treated as the whole project."""
    _patch_client(monkeypatch, _FakeRpc(pages=[_page(["src/a.py"], total=97)]))

    assert _probe().available is False


# ---------------------------------------------------------------------------
# Layer 2: the checks. Fixtures follow tests/test_eig_block_e1_gate_execution.py.
# ---------------------------------------------------------------------------


def make_step(
    level: int,
    step_id: str,
    parent: uuid.UUID | None,
    *,
    target: str | None = None,
    priority: int = 1,
    depends: list[str] | None = None,
    operation: str = "modify_file",
    verification: object = "pytest tests/test_x.py",
) -> Step:
    """Copy of tests/test_eig_block_e1_gate_execution.py's make_step helper."""
    fields: dict = {"name": step_id}
    if level == 3:
        fields.update({"description": "d.", "relations": [], "source_labels": []})
    if level == 4:
        fields.update({"description": "d.", "inputs": [], "outputs": []})
    if level == 5:
        fields.update(
            {
                "target_file": target,
                "priority": priority,
                "operation": operation,
                "prompt": "do work",
                "verification": verification,
            }
        )
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN,
        parent_step_uuid=parent,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=depends or [],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree(nodes: dict[uuid.UUID, Step]) -> GateTree:
    return GateTree(steps=nodes, concept_ids=[], relations=[], labels=[], counts={})


def _path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


def _available(*paths: str) -> ExternalFilesProbe:
    return ExternalFilesProbe(available=True, reason=None, files=frozenset(paths))


UNAVAILABLE = ExternalFilesProbe(available=False, reason="ca_unreachable")


def _orphan_modify_fixture():
    """A modify_file step whose target nothing in the plan ever creates."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    modifier = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="modify_file")
    nodes = {x.uuid: x for x in (gs, ts, modifier)}
    return _tree(nodes), nodes, modifier


def _unordered_creator_fixture():
    """A modify_file step ordered BEFORE the create_file owner of its target.

    Same parent and same target_file, so views.dependency_graph.build_edges
    serializes them by priority: the modifier (priority 1) precedes the
    creator (priority 2), which is precisely the ordering violation.
    """
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    modifier = make_step(
        5, "A-001", ts.uuid, target="src/widget.py", operation="modify_file", priority=1
    )
    creator = make_step(
        5, "A-002", ts.uuid, target="src/widget.py", operation="create_file", priority=2
    )
    nodes = {x.uuid: x for x in (gs, ts, modifier, creator)}
    return _tree(nodes), nodes, modifier, creator


def test_modify_file_context_available_red_when_target_exists_nowhere():
    tree, nodes, modifier = _orphan_modify_fixture()
    steps = list(nodes.values())

    findings = check_modify_file_context_available(tree, steps, _available("src/other.py"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.modify_file_context_available"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, modifier)
    assert "EXEC_MODIFY_TARGET_MISSING" in finding.message
    assert "src/widget.py" in finding.message
    # The two halves of the shared scan are mutually exclusive per (step, file).
    assert check_artifact_producer_exists(tree, steps, _available("src/other.py")) == []


def test_modify_file_context_available_green_when_the_file_exists_in_the_project():
    tree, nodes, _modifier = _orphan_modify_fixture()
    steps = list(nodes.values())
    probe = _available("src/widget.py")

    assert check_modify_file_context_available(tree, steps, probe) == []
    assert check_artifact_producer_exists(tree, steps, probe) == []


def test_artifact_producer_exists_red_when_the_in_plan_creator_runs_later():
    tree, nodes, modifier, creator = _unordered_creator_fixture()
    steps = list(nodes.values())

    findings = check_artifact_producer_exists(tree, steps, _available("src/elsewhere.py"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.artifact_producer_exists"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, modifier)
    assert "EXEC_ARTIFACT_PRODUCER_MISSING" in finding.message
    assert repr(_path(nodes, creator)) in finding.message
    # Ordering case, therefore NOT the total-absence code.
    assert check_modify_file_context_available(tree, steps, _available("src/elsewhere.py")) == []


def test_artifact_producer_exists_green_when_the_creator_is_ordered_first():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    creator = make_step(
        5, "A-001", ts.uuid, target="src/widget.py", operation="create_file", priority=1
    )
    modifier = make_step(
        5, "A-002", ts.uuid, target="src/widget.py", operation="modify_file", priority=2
    )
    nodes = {x.uuid: x for x in (gs, ts, creator, modifier)}
    tree = _tree(nodes)
    steps = list(nodes.values())
    probe = _available("src/elsewhere.py")

    assert check_artifact_producer_exists(tree, steps, probe) == []
    assert check_modify_file_context_available(tree, steps, probe) == []


def test_existence_checks_never_raise_on_ambiguous_same_file_order():
    """Same contract as E1/E2: an ambiguous writer order (already reported by
    dependencies.same_file_order) suppresses only the ORDERING half; total
    absence needs no graph and is still reported."""
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    a1 = make_step(5, "A-001", ts1.uuid, target="src/shared.py", priority=1)
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py", priority=1)
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)
    steps = list(nodes.values())
    probe = _available("src/elsewhere.py")

    assert check_artifact_producer_exists(tree, steps, probe) == []
    assert len(check_modify_file_context_available(tree, steps, probe)) == 2


# ---------------------------------------------------------------------------
# The degraded matrix, per check and through run_all.
# ---------------------------------------------------------------------------


def test_degraded_no_probe_emits_nothing_at_all():
    tree, nodes, _modifier = _orphan_modify_fixture()
    steps = list(nodes.values())

    assert check_artifact_producer_exists(tree, steps, None) == []
    assert check_modify_file_context_available(tree, steps, None) == []
    assert check_verification_target_resolvable(tree, steps, None) == []
    assert check_external_project_unverified(tree, steps, None, True) == []
    assert run_existence_checks(tree, steps, None, True) == []


def test_degraded_unavailable_probe_without_the_policy_emits_nothing():
    tree, nodes, _modifier = _orphan_modify_fixture()
    steps = list(nodes.values())

    assert check_artifact_producer_exists(tree, steps, UNAVAILABLE) == []
    assert check_modify_file_context_available(tree, steps, UNAVAILABLE) == []
    assert check_external_project_unverified(tree, steps, UNAVAILABLE, False) == []
    assert run_existence_checks(tree, steps, UNAVAILABLE, False) == []


def test_degraded_unavailable_probe_with_the_policy_emits_exactly_one_finding():
    tree, nodes, _modifier = _orphan_modify_fixture()
    steps = list(nodes.values())

    findings = run_existence_checks(tree, steps, UNAVAILABLE, True)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.external_project_unverified"
    assert finding.severity == "error"
    assert finding.artifact_path == "plan"
    assert "EXEC_EXTERNAL_PROJECT_UNVERIFIED" in finding.message
    assert "ca_unreachable" in finding.message


def test_external_project_unverified_is_silent_while_the_probe_is_available():
    tree, nodes, _modifier = _orphan_modify_fixture()
    steps = list(nodes.values())

    assert check_external_project_unverified(tree, steps, _available(), True) == []


# ---------------------------------------------------------------------------
# The orphan / resolvable merge: ONE detector, both check_ids registered.
# ---------------------------------------------------------------------------


def _orphan_verification_fixture():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    verifier = make_step(
        5, "A-001", ts.uuid, target="tests/test_widget.py",
        verification={"type": "tests", "target": "src/nowhere.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, verifier)}
    return _tree(nodes), nodes, verifier


def test_verification_target_resolvable_is_permanently_empty_and_merged():
    """The merge decision: no_orphan_verification reports, and
    verification_target_resolvable stays registered but always passes -- so
    one violation is never reported twice under two check_ids."""
    tree, nodes, verifier = _orphan_verification_fixture()
    steps = list(nodes.values())
    # The verifier's OWN target_file exists, so the only defect in this
    # fixture is its verification.target -- nothing else may fire.
    probe = _available("src/other.py", "tests/test_widget.py")

    reported = check_no_orphan_verification(tree, steps, probe)
    assert len(reported) == 1
    assert reported[0].check_id == "execution_integrity.no_orphan_verification"
    assert reported[0].artifact_path == _path(nodes, verifier)

    assert check_verification_target_resolvable(tree, steps, probe) == []
    assert run_existence_checks(tree, steps, probe, False) == []


def test_orphan_verification_resolves_against_the_live_project_listing():
    """A target that exists in the project but nowhere in the plan is fine --
    exactly the false-red that kept this check suppressed through E1/E2."""
    tree, nodes, _verifier = _orphan_verification_fixture()
    steps = list(nodes.values())

    assert _detect_orphan_verification(tree, steps, _available("src/nowhere.py")) == []


def test_orphan_verification_resolves_against_an_in_plan_target_file():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/nowhere.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/nowhere.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    tree = _tree(nodes)

    assert _detect_orphan_verification(tree, list(nodes.values()), _available()) == []


# ---------------------------------------------------------------------------
# LEGACY SAFETY: a role-less plan whose files all exist must stay clean even
# with an available probe -- block F must not red a plan that block E1/E2
# left green.
# ---------------------------------------------------------------------------


def test_legacy_role_less_plan_with_all_files_existing_yields_zero_findings():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)
    steps = list(nodes.values())
    probe = _available("src/one.py", "src/two.py")

    assert run_existence_checks(tree, steps, probe, True) == []
    assert (
        run_execution_integrity_checks(
            tree, steps, external_files=probe, require_project_verification=True
        )
        == []
    )
