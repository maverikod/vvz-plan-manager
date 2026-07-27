"""Regression tests for TODO 299c1037: object declarations whose concept
set is not covered by their atomic-step concept sets must surface in the
mechanical gate.

`views.objects.object_findings()` already emits the source finding
`concepts_not_covered`, but before this fix the mechanical gate ignored it,
leaving a documented object-axis integrity rule disconnected from
`plan_validate`.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate import run_gate
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_objects import check_object_concepts_not_covered


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000299103")


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


def _step(step_uuid, parent_uuid, level, step_id) -> Step:
    return Step(
        uuid=step_uuid,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={"target_file": "pkg/widget.py"},
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


def test_object_concepts_not_covered_emits_scoped_gate_findings():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as1 = uuid.uuid4()
    tree = _tree(
        [
            _step(gs, None, 3, "G-001"),
            _step(ts, gs, 4, "T-001"),
            _step(as1, ts, 5, "A-001"),
        ]
    )
    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                {"target_file": "pkg/widget.py", "objects": [{"name": "Widget", "concepts": ["C-001", "C-999"]}]},
                ["C-001"],
            ),
        ],
    )

    findings = check_object_concepts_not_covered(conn, PLAN_UUID, tree, [tree.steps[as1]])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "coverage.object_concepts_not_covered"
    assert finding.artifact_path == "G-001/T-001/A-001"
    assert "Widget" in finding.message
    assert "C-999" in finding.message


class _RunGateConn:
    def cursor(self):
        raise AssertionError("current_head_revision is monkeypatched in this wiring test")


def test_run_gate_wires_object_concepts_not_covered(monkeypatch):
    gs_uuid = uuid.uuid4()
    ts_uuid = uuid.uuid4()
    as_uuid = uuid.uuid4()
    gs = _step(gs_uuid, None, 3, "G-001")
    ts = _step(ts_uuid, gs_uuid, 4, "T-001")
    as_step = _step(as_uuid, ts_uuid, 5, "A-001")
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
        "check_object_multiple_owner_keys",
        "check_object_multiple_modules",
        "check_embedded_code_parses",
        "check_context_coverage_common_current",
        "check_context_coverage_specific_subset",
    )
    for name in empty_checks:
        monkeypatch.setattr(f"plan_manager.verify.gate.{name}", lambda *args, **kwargs: [])

    monkeypatch.setattr(
        "plan_manager.verify.gate.check_object_concepts_not_covered",
        lambda _conn, _plan_uuid, _tree, _steps: [
            Finding(
                check_id="coverage.object_concepts_not_covered",
                severity="error",
                artifact_path="G-001/T-001/A-001",
                message="object concepts not covered",
            )
        ],
    )

    report, verdict = run_gate(_RunGateConn(), PLAN_UUID)

    check_ids = [check.check_id for check in report.checks]
    assert "coverage.object_concepts_not_covered" in check_ids
    assert report.green is False
    assert verdict.green is False
