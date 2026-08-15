"""Tests for EIG block E1 (todo 0f50b0df): the execution_integrity mechanical
gate group (plan_manager.verify.gate_execution), registered in
plan_manager.verify.gate.GROUP_ORDER/CHECK_IDS as the eighth check group.

Mirrors this suite's established convention (tests/test_eig_block_b_execution_
graph.py): pure check-function tests build Step objects in-memory and wrap
them in a GateTree (never a live Postgres), and the one end-to-end run_gate
test drives a minimal fake connection covering exactly the read-only queries
that pass -- load_tree, gs_coverage, object_inventory, gate_context, and
current_head_revision.

Four checks, all pure over an already-loaded GateTree (no DB access of their
own -- views.execution_graph.build_execution_graph takes only an in-memory
nodes dict):
    - object_producer_before_consumer (error)
    - execution_graph_acyclic (error)
    - parallelization_safe (error)
    - no_orphan_verification (error) -- ENFORCED since EIG block F (todo
      763ae29e), which is exactly what the E1 suppression note anticipated.
      It shipped suppressed because Report.green counts every finding
      regardless of severity and verification.target routinely names a
      legitimately pre-existing repo file that E1 could not confirm the
      existence of. Block F removes the cause instead of the check: the
      caller hands run_gate a live CA file-existence probe
      (runtime.ca_files_probe.ExternalFilesProbe), and both the public check
      and the raw detector stay silent unless that probe is present AND
      available -- so a probe-less caller sees byte-identically the
      suppressed behaviour. The tests below were rewritten from
      "suppression" pins to "probe-gated enforcement" pins accordingly;
      block F's own coverage lives in
      tests/test_eig_block_f_external_existence.py.

LEGACY SAFETY (hard requirement): all four checks only ever act on inferred-
edge or dict-shaped verification data, so a role-less plan with no such data
produces zero findings from every one of them -- pinned below by
test_legacy_role_less_plan_yields_zero_findings_from_all_four_checks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.verify.finding import build_report
from plan_manager.verify.gate import CHECK_IDS, GROUP_ORDER, run_gate
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_execution import (
    ORPHAN_VERIFICATION_ENFORCEMENT,
    _detect_orphan_verification,
    check_execution_graph_acyclic,
    check_no_orphan_verification,
    check_object_producer_before_consumer,
    check_parallelization_safe,
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
    """Copy of tests/test_eig_block_b_execution_graph.py's make_step helper."""
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
# object_producer_before_consumer: red without explicit order, green after.
# ---------------------------------------------------------------------------


def test_object_producer_before_consumer_red_without_explicit_order():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    tree = _tree(nodes)

    findings = check_object_producer_before_consumer(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    consumer_path = _path(nodes, consumer)
    producer_path = _path(nodes, producer)
    assert finding.check_id == "execution_integrity.object_producer_before_consumer"
    assert finding.severity == "error"
    assert finding.artifact_path == consumer_path
    assert "EXEC_PRODUCER_UNORDERED" in finding.message
    assert repr(producer_path) in finding.message
    assert "widget_schema" in finding.message


def test_object_producer_before_consumer_green_after_explicit_dep():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2, depends=["A-001"],
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    tree = _tree(nodes)

    findings = check_object_producer_before_consumer(tree, list(nodes.values()))

    assert findings == []


# ---------------------------------------------------------------------------
# execution_graph_acyclic: full ordered cycle path packed into the message.
# ---------------------------------------------------------------------------


def test_execution_graph_acyclic_reports_full_cycle_path():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    ts3 = make_step(4, "T-003", gs.uuid)
    # Purely inferred 3-node cycle (ts1 -> ts2 -> ts3 -> ts1), same shape as
    # tests/test_eig_block_b_execution_graph.py::test_cycle_reported_as_full_ordered_path.
    a1 = make_step(
        5, "A-001", ts1.uuid, target="src/one.py",
        objects=[
            {"name": "obj_a", "concepts": [], "role": "consume"},
            {"name": "obj_b", "concepts": [], "role": "create"},
        ],
    )
    a2 = make_step(
        5, "A-001", ts2.uuid, target="src/two.py",
        objects=[
            {"name": "obj_b", "concepts": [], "role": "consume"},
            {"name": "obj_c", "concepts": [], "role": "create"},
        ],
    )
    a3 = make_step(
        5, "A-001", ts3.uuid, target="src/three.py",
        objects=[
            {"name": "obj_c", "concepts": [], "role": "consume"},
            {"name": "obj_a", "concepts": [], "role": "create"},
        ],
    )
    nodes = {x.uuid: x for x in (gs, ts1, ts2, ts3, a1, a2, a3)}
    tree = _tree(nodes)

    findings = check_execution_graph_acyclic(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.execution_graph_acyclic"
    assert finding.severity == "error"
    expected_paths = {_path(nodes, a1), _path(nodes, a2), _path(nodes, a3)}
    assert finding.artifact_path in expected_paths
    assert "EXEC_GRAPH_CYCLE" in finding.message
    for path in expected_paths:
        assert repr(path) in finding.message


def test_execution_graph_acyclic_green_over_pure_dag():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)

    assert check_execution_graph_acyclic(tree, list(nodes.values())) == []


# ---------------------------------------------------------------------------
# parallelization_safe: inferred-edge endpoints must not share one wave.
# ---------------------------------------------------------------------------


def test_parallelization_safe_flags_same_wave_object_producer_edge():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py",
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    tree = _tree(nodes)

    findings = check_parallelization_safe(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.parallelization_safe"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, consumer)
    assert "EXEC_PARALLEL_UNSAFE" in finding.message
    assert "object_producer" in finding.message


def test_parallelization_safe_flags_same_wave_verification_target_edge():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    creator = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py",
        verification={"type": "tests", "target": "src/widget.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, creator, verifier)}
    tree = _tree(nodes)

    findings = check_parallelization_safe(tree, list(nodes.values()))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.artifact_path == _path(nodes, verifier)
    assert "verification_target" in finding.message


def test_parallelization_safe_green_after_explicit_dep():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2, depends=["A-001"],
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    tree = _tree(nodes)

    assert check_parallelization_safe(tree, list(nodes.values())) == []


# ---------------------------------------------------------------------------
# no_orphan_verification: ENFORCED since EIG block F (todo 763ae29e). E1
# shipped it suppressed because it had no way to tell "the file pre-exists in
# the repo" from "the file exists nowhere", and Report.green counts every
# finding regardless of severity. Block F supplies that knowledge as a live
# CA file probe passed down by the caller, so the check now speaks -- but ONLY
# when an available probe is present. With no probe (every run_gate caller
# except plan_validate, and every legacy fixture below) the behaviour is
# byte-identical to the suppressed era, which is what makes flipping
# ORPHAN_VERIFICATION_ENFORCEMENT safe.
# ---------------------------------------------------------------------------


class _Probe:
    """Minimal structural stand-in for runtime.ca_files_probe.ExternalFilesProbe.

    The gate only ever reads ``.available`` and ``.files``, and verify/ imports
    the real dataclass under TYPE_CHECKING only, so these pure check tests stay
    free of the CA transport import. The real dataclass is exercised in
    tests/test_eig_block_f_external_existence.py.
    """

    def __init__(self, *, available: bool, files: frozenset[str] = frozenset()):
        self.available = available
        self.reason = None if available else "ca_unreachable"
        self.files = files


def test_orphan_verification_enforcement_switch_is_enforced_since_block_f():
    assert ORPHAN_VERIFICATION_ENFORCEMENT == "enforced"


def test_detect_orphan_verification_red_when_target_exists_nowhere():
    """With an available probe, a target in neither the project nor the plan
    is a hard error (it was a warning while E1 could only guess)."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/does_not_exist.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    tree = _tree(nodes)

    findings = _detect_orphan_verification(
        tree, list(nodes.values()), _Probe(available=True, files=frozenset({"src/other.py"}))
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "execution_integrity.no_orphan_verification"
    assert finding.severity == "error"
    assert finding.artifact_path == _path(nodes, verifier)
    assert "EXEC_ORPHAN_VERIFICATION" in finding.message
    assert "src/does_not_exist.py" in finding.message


def test_detect_orphan_verification_green_when_target_matches_a_target_file():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/widget.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    tree = _tree(nodes)

    assert _detect_orphan_verification(
        tree, list(nodes.values()), _Probe(available=True)
    ) == []


def test_detect_orphan_verification_ignores_legacy_string_verification():
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    verifier = make_step(
        5, "A-001", ts.uuid, target="tests/test_widget.py",
        verification="pytest tests/test_widget.py",
    )
    nodes = {x.uuid: x for x in (gs, ts, verifier)}
    tree = _tree(nodes)

    assert _detect_orphan_verification(
        tree, list(nodes.values()), _Probe(available=True)
    ) == []


def test_check_no_orphan_verification_is_silent_without_a_probe():
    """The enforced check must still return [] for a probe-less caller, on a
    fixture where the same call WITH a probe finds a real mismatch -- proves
    the probe gate is actually masking something, not vacuously true."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/missing.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    # With an available probe the public check flags it.
    assert len(check_no_orphan_verification(tree, steps, _Probe(available=True))) == 1

    # Without a probe -- and with an unavailable one -- it must not.
    assert check_no_orphan_verification(tree, steps) == []
    assert check_no_orphan_verification(tree, steps, _Probe(available=False)) == []


def test_no_orphan_verification_stays_green_for_a_probe_less_run():
    """Pins what makes the block-F switch flip safe: a plan that trips the
    detector under a probe must still come back green through the public
    check/report path when no probe is wired, since Report.green counts every
    finding regardless of severity."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/missing.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    findings = check_no_orphan_verification(tree, steps)
    assert findings == []

    report = build_report(CHECK_IDS["execution_integrity"], findings)
    assert report.green is True
    orphan_check = next(
        c for c in report.checks
        if c.check_id == "execution_integrity.no_orphan_verification"
    )
    assert orphan_check.passed is True
    assert orphan_check.findings == []


# ---------------------------------------------------------------------------
# LEGACY SAFETY (hard requirement): zero findings from all four checks on a
# role-less plan with no dict-shaped verification data.
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

    assert check_object_producer_before_consumer(tree, steps) == []
    assert check_execution_graph_acyclic(tree, steps) == []
    assert check_parallelization_safe(tree, steps) == []
    assert check_no_orphan_verification(tree, steps) == []


# ---------------------------------------------------------------------------
# Ambiguous same-file writer order: the three graph-dependent checks must
# yield zero findings, never raise SameFileOrderAmbiguousError. Before this
# guard, run_gate would have crashed (uncaught exception, not a red report)
# for any plan gate_structure.check_dependencies_same_file_order already
# flags -- that check uses strict_same_file_order=False specifically so
# run_gate never raises for this condition; the new checks must honor the
# same invariant instead of calling build_edges/build_execution_graph strict.
# ---------------------------------------------------------------------------


def test_graph_checks_do_not_raise_on_ambiguous_same_file_order():
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    a1 = make_step(5, "A-001", ts1.uuid, target="src/shared.py", priority=1)
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py", priority=1)
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    tree = _tree(nodes)
    steps = list(nodes.values())

    assert check_object_producer_before_consumer(tree, steps) == []
    assert check_execution_graph_acyclic(tree, steps) == []
    assert check_parallelization_safe(tree, steps) == []


# ---------------------------------------------------------------------------
# Group wiring + end-to-end run_gate: the group appears in the report with
# all four check_ids listed, passing, on a green plan.
# ---------------------------------------------------------------------------


def test_execution_integrity_group_registered():
    # EIG block E2 (todo c6f541d0) appended four closure checks
    # (gate_execution_closure.py) and block F (todo 763ae29e) four existence
    # checks (gate_execution_existence.py) to this same group -- see
    # tests/test_eig_block_e2_gate_closure.py and
    # tests/test_eig_block_f_external_existence.py for their own coverage.
    assert "execution_integrity" in GROUP_ORDER
    assert CHECK_IDS["execution_integrity"] == [
        "execution_integrity.object_producer_before_consumer",
        "execution_integrity.execution_graph_acyclic",
        "execution_integrity.parallelization_safe",
        "execution_integrity.no_orphan_verification",
        "execution_integrity.test_coverage_present",
        "execution_integrity.release_artifact_closure",
        "execution_integrity.deployment_closure",
        "execution_integrity.no_unverified_production",
        "execution_integrity.artifact_producer_exists",
        "execution_integrity.verification_target_resolvable",
        "execution_integrity.modify_file_context_available",
        "execution_integrity.external_project_unverified",
    ]


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-00000f50b0df")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-00000f50b0e0")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-00000f50b0e1")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-00000f50b0e2")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-00000f50b0e3")

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

# Both G-001 and G-001/T-001 have a child, so context_coverage.common_current
# requires a current "common" context_block row for each (else it reports a
# finding that would break this fixture's green expectation -- unrelated to
# execution_integrity, but required for the whole-report green baseline).
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
    current_head_revision (mirrors tests/test_bug_e197b94a_branch_scope_
    selectors.py's _FullCursor)."""

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
    """Comprehensive fake connection for one full run_gate() branch-scope
    pass: load_tree's step/concept/relation/paragraph selects,
    coverage.gs_coverage's two level-scoped step selects, views.objects.
    object_inventory's three step selects, gate_context's context_block/
    cascade/ref/plan selects, and current_head_revision's plan select.
    """

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


def test_execution_integrity_group_appears_in_report_all_four_check_ids_when_passing():
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
    check_ids_present = {check.check_id for check in report.checks}
    expected = set(CHECK_IDS["execution_integrity"])
    assert expected <= check_ids_present
    for check in report.checks:
        if check.check_id in expected:
            assert check.passed is True
            assert check.findings == []
