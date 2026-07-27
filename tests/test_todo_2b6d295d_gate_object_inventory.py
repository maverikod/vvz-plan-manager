"""Regression tests for TODO 2b6d295d: name drift and duplicate object
definitions must be surfaced by the mechanical gate.

The repository already shipped `views.objects.object_inventory()` /
`object_findings()`, but the mechanical gate never called them, so a plan
could carry duplicated object ownership or the same object name drifting
across modules while `plan_validate` still returned green.

Acceptance:
1. duplicate owner-key findings are emitted as gate findings;
2. cross-module drift findings are emitted as gate findings;
3. `run_gate()` wires the object-axis checks into the coverage phase without
   changing the historical static `CHECK_IDS["coverage"]` baseline.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate import run_gate
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_objects import (
    check_object_multiple_modules,
    check_object_multiple_owner_keys,
)


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000002b6d")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _InventoryConn:
    def __init__(self, gs_rows, ts_rows, as_rows) -> None:
        self._gs_rows = gs_rows
        self._ts_rows = ts_rows
        self._as_rows = as_rows

    def execute(self, query: str, params=()):
        assert params == (PLAN_UUID,), params
        if "level = 3" in query:
            return _Rows(self._gs_rows)
        if "level = 4" in query:
            return _Rows(self._ts_rows)
        if "level = 5" in query:
            return _Rows(self._as_rows)
        raise AssertionError(query)


def _step(step_uuid, parent_uuid, level, step_id, target_file) -> Step:
    return Step(
        uuid=step_uuid,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={"target_file": target_file},
        depends_on=[],
        concepts=["C-001"],
        project_id=None,
        status="draft",
    )


def _tree(steps: list[Step]) -> GateTree:
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


def test_object_multiple_owner_keys_emits_findings_for_each_scoped_artifact_path():
    gs1 = uuid.uuid4()
    gs2 = uuid.uuid4()
    ts1 = uuid.uuid4()
    ts2 = uuid.uuid4()
    as1 = uuid.uuid4()
    as2 = uuid.uuid4()

    tree = _tree(
        [
            _step(gs1, None, 3, "G-001", "ignored.py"),
            _step(gs2, None, 3, "G-002", "ignored.py"),
            _step(ts1, gs1, 4, "T-001", "ignored.py"),
            _step(ts2, gs2, 4, "T-001", "ignored.py"),
            _step(as1, ts1, 5, "A-001", "pkg/shared.py"),
            _step(as2, ts2, 5, "A-001", "pkg/shared.py"),
        ]
    )
    conn = _InventoryConn(
        gs_rows=[(gs1, "G-001"), (gs2, "G-002")],
        ts_rows=[(ts1, gs1, "T-001"), (ts2, gs2, "T-001")],
        as_rows=[
            (ts1, "A-001", {"target_file": "pkg/shared.py", "objects": [{"name": "Widget", "concepts": ["C-001"]}]}, ["C-001"]),
            (ts2, "A-001", {"target_file": "pkg/shared.py", "objects": [{"name": "Widget", "concepts": ["C-001"]}]}, ["C-001"]),
        ],
    )

    findings = check_object_multiple_owner_keys(conn, PLAN_UUID, tree, [tree.steps[as1], tree.steps[as2]])

    assert [finding.check_id for finding in findings] == [
        "coverage.object_multiple_owner_keys",
        "coverage.object_multiple_owner_keys",
    ]
    assert [finding.artifact_path for finding in findings] == [
        "G-001/T-001/A-001",
        "G-002/T-001/A-001",
    ]
    assert all("Widget" in finding.message for finding in findings)


def test_object_multiple_modules_filters_to_the_scoped_branch_paths():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as1 = uuid.uuid4()
    as2 = uuid.uuid4()

    tree = _tree(
        [
            _step(gs, None, 3, "G-001", "ignored.py"),
            _step(ts, gs, 4, "T-001", "ignored.py"),
            _step(as1, ts, 5, "A-001", "pkg/alpha.py"),
            _step(as2, ts, 5, "A-002", "pkg/beta.py"),
        ]
    )
    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (ts, "A-001", {"target_file": "pkg/alpha.py", "objects": [{"name": "Widget", "concepts": ["C-001"]}]}, ["C-001"]),
            (ts, "A-002", {"target_file": "pkg/beta.py", "objects": [{"name": "Widget", "concepts": ["C-001"]}]}, ["C-001"]),
        ],
    )

    findings = check_object_multiple_modules(conn, PLAN_UUID, tree, [tree.steps[as1]])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "coverage.object_multiple_modules"
    assert finding.artifact_path == "G-001/T-001/A-001"
    assert "pkg.alpha" in finding.message
    assert "pkg.beta" in finding.message


class _RunGateConn:
    def cursor(self):
        raise AssertionError("current_head_revision is monkeypatched in this wiring test")


def test_run_gate_wires_object_inventory_checks_into_coverage_group(monkeypatch):
    step_uuid = uuid.uuid4()
    gs_uuid = uuid.uuid4()
    ts_uuid = uuid.uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", "ignored.py")
    ts = _step(ts_uuid, gs_uuid, 4, "T-001", "ignored.py")
    as_step = _step(step_uuid, ts_uuid, 5, "A-001", "pkg/a.py")
    tree = _tree([gs, ts, as_step])

    monkeypatch.setattr("plan_manager.verify.gate.load_tree", lambda _conn, _plan_uuid: tree)
    monkeypatch.setattr("plan_manager.verify.gate.scope_steps", lambda _tree, _branch: [as_step])
    monkeypatch.setattr("plan_manager.verify.gate.current_head_revision", lambda _conn, _plan_uuid: None)

    empty_checks = (
        "check_parse_required_fields",
        "check_parse_inputs_outputs",
        "check_parse_target_file",
        "check_parse_atomic_single_code_file",
        "check_parse_sanity_counts",
        "check_identity_step_id",
        "check_identity_slug",
        "check_identity_concept_id",
        "check_identity_label",
        "check_uniqueness_step_id",
        "check_uniqueness_concept_id",
        "check_uniqueness_label",
        "check_uniqueness_priority",
        "check_references_depends_on",
        "check_references_concepts",
        "check_references_relations",
        "check_references_source_labels",
        "check_dependencies_same_file_order",
        "check_coverage_concepts",
        "check_coverage_gs",
        "check_coverage_labels",
        "check_coverage_relations",
        "check_embedded_code_parses",
        "check_context_coverage_common_current",
        "check_context_coverage_specific_subset",
    )
    for name in empty_checks:
        monkeypatch.setattr(f"plan_manager.verify.gate.{name}", lambda *args, **kwargs: [])

    monkeypatch.setattr(
        "plan_manager.verify.gate.check_object_multiple_owner_keys",
        lambda _conn, _plan_uuid, _tree, _steps: [
            Finding(
                check_id="coverage.object_multiple_owner_keys",
                severity="error",
                artifact_path="G-001/T-001/A-001",
                message="duplicate owner keys",
            )
        ],
    )
    monkeypatch.setattr(
        "plan_manager.verify.gate.check_object_multiple_modules",
        lambda _conn, _plan_uuid, _tree, _steps: [
            Finding(
                check_id="coverage.object_multiple_modules",
                severity="error",
                artifact_path="G-001/T-001/A-001",
                message="module drift",
            )
        ],
    )
    monkeypatch.setattr(
        "plan_manager.verify.gate.check_object_concepts_not_covered",
        lambda _conn, _plan_uuid, _tree, _steps: [
            Finding(
                check_id="coverage.object_concepts_not_covered",
                severity="error",
                artifact_path="G-001/T-001/A-001",
                message="object concepts drift",
            )
        ],
    )

    report, verdict = run_gate(_RunGateConn(), PLAN_UUID)

    check_ids = [check.check_id for check in report.checks]
    assert "coverage.object_multiple_owner_keys" in check_ids
    assert "coverage.object_multiple_modules" in check_ids
    assert "coverage.object_concepts_not_covered" in check_ids
    assert report.green is False
    assert verdict.green is False
