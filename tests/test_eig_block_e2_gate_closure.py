"""Tests for EIG block E2 (todo c6f541d0): four closure checks appended to
the execution_integrity mechanical gate group
(plan_manager.verify.gate_execution_closure), dispatched alongside EIG
block E1's four checks (plan_manager.verify.gate_execution) through
gate_execution.run_all and registered in plan_manager.verify.gate.
CHECK_IDS["execution_integrity"] (now eight entries total).

Mirrors tests/test_eig_block_e1_gate_execution.py's convention: pure
check-function tests build Step objects in-memory and wrap them in a
GateTree (never a live Postgres); one end-to-end run_gate test drives a
minimal fake connection.

Four checks, all severity error, all keyed off explicit block-A object
roles (domain.step_objects.OBJECT_ROLES) and all a no-op the moment the
plan does not use the role they key off:
    - test_coverage_present -- OPT-IN: fires only once the plan has
      declared at least one verify-role object anywhere; a plan that never
      uses the verify role at all gets zero findings even though it has
      unverified create/modify objects.
    - release_artifact_closure -- a package-role object's verify-role
      declarations must be explicit-graph-reachable after every one of its
      package-role declarations.
    - deployment_closure -- same ordering rule for deploy-role objects,
      plus: a deploy-role object with no create/modify/package declaration
      anywhere is flagged on its deploying step.
    - no_unverified_production -- NOT opt-in: a package or deploy-role
      object with no verify-role declaration anywhere is flagged
      unconditionally (declaring package/deploy IS the opt-in signal).

LEGACY SAFETY (hard requirement, same as E1): a role-less plan yields zero
findings from all four -- pinned below by
test_legacy_role_less_plan_yields_zero_findings_from_all_four_checks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.verify.gate import CHECK_IDS, run_gate
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_execution_closure import (
    check_deployment_closure,
    check_no_unverified_production,
    check_release_artifact_closure,
    check_test_coverage_present,
)
from plan_manager.views.branch import BranchScope
from plan_manager.views.step_paths import parent_path

PLAN = uuid.uuid4()


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
    objects: list[dict] | None = None,
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
        if objects is not None:
            fields["objects"] = objects
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


# ---------------------------------------------------------------------------
# test_coverage_present: opt-in rule.
# ---------------------------------------------------------------------------


def test_test_coverage_present_red_when_opted_in_and_object_unverified():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    # Opts the plan in: some OTHER object carries a verify-role declaration.
    other_producer = make_step(
        5, "A-001", ts.uuid, target="src/other.py", operation="create_file",
        objects=[{"name": "other_obj", "concepts": [], "role": "create"}],
    )
    other_verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_other.py", priority=2,
        objects=[{"name": "other_obj", "concepts": [], "role": "verify"}],
    )
    # Unverified producer of a DIFFERENT object -- must be flagged now that
    # the plan has opted in.
    unverified_producer = make_step(
        5, "A-003", ts.uuid, target="src/unverified.py", priority=3, operation="create_file",
        objects=[{"name": "unverified_obj", "concepts": [], "role": "create"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, other_producer, other_verifier, unverified_producer)}
    tree = _tree(nodes)

    findings = check_test_coverage_present(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.test_coverage_present"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, unverified_producer)
    assert "EXEC_TEST_COVERAGE_MISSING" in finding.message
    assert "unverified_obj" in finding.message


def test_test_coverage_present_green_when_not_opted_in():
    """No verify-role declaration ANYWHERE in the plan -- opt-in never
    triggers, so an unverified create/modify object stays silent."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/unverified.py", operation="create_file",
        objects=[{"name": "unverified_obj", "concepts": [], "role": "create"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer)}
    tree = _tree(nodes)

    assert check_test_coverage_present(tree, list(nodes.values())) == []


def test_test_coverage_present_green_once_object_itself_gets_verified():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/widget.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, verifier)}
    tree = _tree(nodes)

    assert check_test_coverage_present(tree, list(nodes.values())) == []


# ---------------------------------------------------------------------------
# release_artifact_closure: verified-before-built red -> green after
# explicit dependency.
# ---------------------------------------------------------------------------


def test_release_artifact_closure_red_when_verifier_unordered():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    packager = make_step(
        5, "A-001", ts.uuid, target="build/x.tar", operation="create_file",
        objects=[{"name": "artifact_x", "concepts": [], "role": "package"}],
    )
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_x.py", priority=2,
        objects=[{"name": "artifact_x", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, packager, verifier)}
    tree = _tree(nodes)

    findings = check_release_artifact_closure(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.release_artifact_closure"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, verifier)
    assert "EXEC_RELEASE_BEFORE_BUILD" in finding.message
    assert "artifact_x" in finding.message
    assert repr(_path(nodes, packager)) in finding.message


def test_release_artifact_closure_green_after_explicit_dep():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    packager = make_step(
        5, "A-001", ts.uuid, target="build/x.tar", operation="create_file",
        objects=[{"name": "artifact_x", "concepts": [], "role": "package"}],
    )
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_x.py", priority=2, depends=["A-001"],
        objects=[{"name": "artifact_x", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, packager, verifier)}
    tree = _tree(nodes)

    assert check_release_artifact_closure(tree, list(nodes.values())) == []


def test_release_artifact_closure_green_when_no_package_roles():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    verifier = make_step(
        5, "A-001", ts.uuid, target="tests/test_x.py",
        objects=[{"name": "artifact_x", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, verifier)}
    tree = _tree(nodes)

    assert check_release_artifact_closure(tree, list(nodes.values())) == []


# ---------------------------------------------------------------------------
# deployment_closure: deploy without any producer is red; ordering follows
# the same reachable-after rule as release_artifact_closure.
# ---------------------------------------------------------------------------


def test_deployment_closure_red_when_no_producer_anywhere():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    deployer = make_step(
        5, "A-001", ts.uuid, target="deploy/svc.yaml", operation="create_file",
        objects=[{"name": "orphan_svc", "concepts": [], "role": "deploy"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, deployer)}
    tree = _tree(nodes)

    findings = check_deployment_closure(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.deployment_closure"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, deployer)
    assert "EXEC_DEPLOY_CLOSURE" in finding.message
    assert "orphan_svc" in finding.message
    assert "no create/modify/package-role declaration" in finding.message


def test_deployment_closure_green_when_deployer_also_declares_producer_role():
    """The 'unless the same step also declares it package/create' carve-out:
    a deployer that also packages the same object is its own producer."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    deployer = make_step(
        5, "A-001", ts.uuid, target="deploy/svc.yaml", operation="create_file",
        objects=[
            {"name": "self_packaged_svc", "concepts": [], "role": "package"},
            {"name": "self_packaged_svc", "concepts": [], "role": "deploy"},
        ],
    )
    nodes = {x.uuid: x for x in (gs, ts, deployer)}
    tree = _tree(nodes)

    assert check_deployment_closure(tree, list(nodes.values())) == []


def test_deployment_closure_red_when_verifier_unordered_after_deploy():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/svc.py", operation="create_file",
        objects=[{"name": "svc", "concepts": [], "role": "create"}],
    )
    deployer = make_step(
        5, "A-002", ts.uuid, target="deploy/svc.yaml", priority=2, depends=["A-001"],
        objects=[{"name": "svc", "concepts": [], "role": "deploy"}],
    )
    verifier = make_step(
        5, "A-003", ts.uuid, target="tests/test_svc.py", priority=3,
        objects=[{"name": "svc", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, deployer, verifier)}
    tree = _tree(nodes)

    findings = check_deployment_closure(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.artifact_path == _path(nodes, verifier)
    assert "EXEC_DEPLOY_CLOSURE" in finding.message
    assert repr(_path(nodes, deployer)) in finding.message


# ---------------------------------------------------------------------------
# no_unverified_production: NOT opt-in.
# ---------------------------------------------------------------------------


def test_no_unverified_production_red_for_package_and_deploy_without_verify():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    packager = make_step(
        5, "A-001", ts.uuid, target="build/x.tar", operation="create_file",
        objects=[{"name": "artifact_x", "concepts": [], "role": "package"}],
    )
    deployer = make_step(
        5, "A-002", ts.uuid, target="deploy/y.yaml", priority=2,
        objects=[{"name": "svc_y", "concepts": [], "role": "deploy"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, packager, deployer)}
    tree = _tree(nodes)

    findings = check_no_unverified_production(tree, list(nodes.values()))

    assert len(findings) == 2
    findings_by_path = {f.artifact_path: f for f in findings}
    assert set(findings_by_path) == {_path(nodes, packager), _path(nodes, deployer)}
    for finding in findings:
        assert finding.check_id == "execution_integrity.no_unverified_production"
        assert finding.severity == "error"
        assert "EXEC_UNVERIFIED_PRODUCTION" in finding.message


def test_no_unverified_production_green_once_verified():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    packager = make_step(
        5, "A-001", ts.uuid, target="build/x.tar", operation="create_file",
        objects=[{"name": "artifact_x", "concepts": [], "role": "package"}],
    )
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_x.py", priority=2,
        objects=[{"name": "artifact_x", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, packager, verifier)}
    tree = _tree(nodes)

    assert check_no_unverified_production(tree, list(nodes.values())) == []


# ---------------------------------------------------------------------------
# Full closure: create -> package -> deploy -> verify, all explicitly
# ordered -- zero findings from all four checks at once.
# ---------------------------------------------------------------------------


def test_deploy_package_verify_all_ordered_yields_zero_findings_from_all_four():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    creator = make_step(
        5, "A-001", ts.uuid, target="src/svc.py", operation="create_file",
        objects=[{"name": "svc_artifact", "concepts": [], "role": "create"}],
    )
    packager = make_step(
        5, "A-002", ts.uuid, target="build/svc.tar", priority=2, depends=["A-001"],
        objects=[{"name": "svc_artifact", "concepts": [], "role": "package"}],
    )
    deployer = make_step(
        5, "A-003", ts.uuid, target="deploy/svc.yaml", priority=3, depends=["A-002"],
        objects=[{"name": "svc_artifact", "concepts": [], "role": "deploy"}],
    )
    verifier = make_step(
        5, "A-004", ts.uuid, target="tests/test_svc.py", priority=4, depends=["A-003"],
        objects=[{"name": "svc_artifact", "concepts": [], "role": "verify"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, creator, packager, deployer, verifier)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    assert check_test_coverage_present(tree, steps) == []
    assert check_release_artifact_closure(tree, steps) == []
    assert check_deployment_closure(tree, steps) == []
    assert check_no_unverified_production(tree, steps) == []


# ---------------------------------------------------------------------------
# LEGACY SAFETY (hard requirement): zero findings from all four checks on a
# role-less plan.
# ---------------------------------------------------------------------------


def test_legacy_role_less_plan_yields_zero_findings_from_all_four_checks():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    assert check_test_coverage_present(tree, steps) == []
    assert check_release_artifact_closure(tree, steps) == []
    assert check_deployment_closure(tree, steps) == []
    assert check_no_unverified_production(tree, steps) == []


# ---------------------------------------------------------------------------
# Ambiguous same-file writer order: the two ordering-dependent checks
# (release_artifact_closure, deployment_closure) must yield zero findings,
# never raise SameFileOrderAmbiguousError.
# ---------------------------------------------------------------------------


def test_ordering_checks_do_not_raise_on_ambiguous_same_file_order():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    a1 = make_step(
        5, "A-001", ts1.uuid, target="src/shared.py", priority=1,
        objects=[
            {"name": "art", "concepts": [], "role": "package"},
            {"name": "art", "concepts": [], "role": "deploy"},
        ],
    )
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py", priority=1)
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    assert check_release_artifact_closure(tree, steps) == []
    assert check_deployment_closure(tree, steps) == []


# ---------------------------------------------------------------------------
# Group wiring + end-to-end run_gate: all eight execution_integrity
# check_ids appear in a run_gate report.
# ---------------------------------------------------------------------------


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000c6f541d0")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000c6f541d1")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-0000c6f541d2")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-0000c6f541d3")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000c6f541d4")

GS_FIELDS = {
    "name": "G one",
    "description": "GS description.",
    "relations": [{"from_concept": "C-001", "to_concept": "C-001", "type": "supports"}],
    "source_labels": ["{aaaa}"],
}
TS_FIELDS = {
    "name": "T one",
    "description": "TS description.",
    "inputs": [{"name": "in-one", "type": "input", "description": "one input."}],
    "outputs": [{"name": "out-one", "type": "output", "description": "one output."}],
}
AS_FIELDS = {
    "name": "A one",
    "target_file": "src/one.py",
    "operation": "create_file",
    "priority": 1,
    "prompt": "do work",
    "verification": "pytest tests/test_one.py",
}

STEP_ROWS = [
    (GS_UUID, PLAN_UUID, None, 3, "G-001", "g-one", GS_FIELDS, [], ["C-001"], None, "draft"),
    (TS_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-one", TS_FIELDS, [], ["C-001"], None, "draft"),
    (AS_UUID, PLAN_UUID, TS_UUID, 5, "A-001", "a-one", AS_FIELDS, [], [], None, "draft"),
]

CONTEXT_BLOCK_ROWS = [
    ("G-001", 4, HEAD_REVISION, None, ["C-001"], datetime(2026, 8, 1, tzinfo=timezone.utc)),
    ("G-001/T-001", 5, HEAD_REVISION, None, [], datetime(2026, 8, 1, tzinfo=timezone.utc)),
]


class _Rows:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FullCursor:
    """Fake cursor for the context-manager idiom used by load_tree and
    current_head_revision (copy of test_eig_block_e1_gate_execution.py's
    _FullCursor)."""

    def __init__(self, owner: "_FullFakeConn"):
        self._owner = owner
        self._pending: list[tuple] = []

    def __enter__(self) -> "_FullCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_FullCursor":
        self._pending = self._owner.dispatch(query, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending

    def fetchone(self) -> Optional[tuple]:
        return self._pending[0] if self._pending else None


class _FullFakeConn:
    """Copy of test_eig_block_e1_gate_execution.py's _FullFakeConn: covers
    load_tree, gs_coverage, object_inventory, gate_context, and
    current_head_revision -- exactly the read-only queries one full
    run_gate() branch-scope pass issues."""

    def cursor(self) -> _FullCursor:
        return _FullCursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Rows:
        return _Rows(self.dispatch(query, params))

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(STEP_ROWS)
        if query.startswith("SELECT concept_id FROM concept"):
            return [("C-001",)]
        if query.startswith("SELECT from_concept, to_concept, type FROM relation"):
            return []
        if query.startswith("SELECT label FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE ORDER BY position"):
            return [("aaaa",)]
        if query.startswith("SELECT count(*) FROM paragraph"):
            return [(1,)]
        if query.startswith("SELECT uuid, step_id, concepts FROM step WHERE plan_uuid = %s AND level = 3"):
            return [(GS_UUID, "G-001", ["C-001"])]
        if query.startswith("SELECT parent_step_uuid, concepts FROM step WHERE plan_uuid = %s AND level = 4"):
            return [(GS_UUID, ["C-001"])]
        if query.startswith("SELECT uuid, step_id FROM step WHERE plan_uuid = %s AND level = 3"):
            return [(GS_UUID, "G-001")]
        if query.startswith("SELECT uuid, parent_step_uuid, step_id FROM step "):
            return [(TS_UUID, GS_UUID, "T-001")]
        if query.startswith("SELECT parent_step_uuid, step_id, fields, concepts FROM step "):
            return [(TS_UUID, "A-001", AS_FIELDS, [])]
        if query.startswith("SELECT uuid, name FROM cascade"):
            return []
        if query.startswith("SELECT revision_uuid FROM ref"):
            return []
        if query.startswith("SELECT head_revision_uuid FROM plan"):
            return [(HEAD_REVISION,)]
        if query.startswith("SELECT node_path, child_level, revision_uuid, cascade_uuid"):
            return list(CONTEXT_BLOCK_ROWS)
        raise AssertionError(f"unexpected query in _FullFakeConn: {query!r}")


def test_execution_integrity_group_appears_in_report_all_eight_check_ids_when_passing():
    branch = BranchScope(
        plan_uuid=PLAN_UUID,
        depth="gs",
        gs=Step(
            uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3, step_id="G-001",
            slug="g-one", fields=GS_FIELDS, depends_on=[], concepts=["C-001"], project_id=None, status="draft",
        ),
        ts=None,
        atomic=None,
        hrs_slice=[Paragraph(label="aaaa", text="unused.", position=0)],
    )
    conn = _FullFakeConn()

    report, verdict = run_gate(conn, PLAN_UUID, branch=branch, fail_fast=False)

    assert report.green is True, report.checks
    assert len(CHECK_IDS["execution_integrity"]) == 8
    check_ids_present = {check.check_id for check in report.checks}
    expected = set(CHECK_IDS["execution_integrity"])
    assert expected <= check_ids_present
    for check in report.checks:
        if check.check_id in expected:
            assert check.passed is True
            assert check.findings == []
