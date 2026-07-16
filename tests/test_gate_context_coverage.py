"""Regression tests for the context-coverage completeness net (C-004)."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from plan_manager.domain.step import Step
from plan_manager.verify.gate import CHECK_IDS, GROUP_ORDER
from plan_manager.verify.gate_context import (
    check_context_coverage_common_current,
    check_context_coverage_specific_subset,
)
from plan_manager.verify.gate_data import GateTree

_ORIGINAL_GROUP_ORDER = [
    "parse",
    "identity",
    "uniqueness",
    "references",
    "coverage",
    "embedded_code",
]

_ORIGINAL_CHECK_IDS = {
    "parse": [
        "parse.required_fields",
        "parse.inputs_outputs",
        "parse.target_file",
        "parse.sanity_counts",
    ],
    "identity": [
        "identity.step_id",
        "identity.slug",
        "identity.concept_id",
        "identity.label",
    ],
    "uniqueness": [
        "uniqueness.step_id",
        "uniqueness.concept_id",
        "uniqueness.label",
        "uniqueness.priority",
    ],
    "references": [
        "references.depends_on",
        "references.concepts",
        "references.relations",
        "references.source_labels",
    ],
    "coverage": [
        "coverage.concepts",
        "coverage.gs",
        "coverage.labels",
        "coverage.relations",
    ],
    "embedded_code": [
        "embedded_code.parses",
    ],
}

PLAN_UUID = UUID("00000000-0000-0000-0000-0000000000f1")
HEAD_REVISION = UUID("00000000-0000-0000-0000-0000000000f2")
OTHER_REVISION = UUID("00000000-0000-0000-0000-0000000000f3")
CASCADE_UUID = UUID("00000000-0000-0000-0000-0000000000f4")
CASCADE_NAME = "cascade/00000000-0000-0000-0000-0000000000f4"
CASCADE_REVISION = UUID("00000000-0000-0000-0000-0000000000f5")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal fake connection dispatching on SQL prefix."""

    def __init__(self, common_rows, cascade_row=None, ref_rows=None, head_revision=HEAD_REVISION):
        self._common_rows = common_rows
        self._cascade_row = cascade_row
        self._ref_rows = ref_rows or {}
        self._head_revision = head_revision

    def execute(self, query, params=()):
        if query.startswith("SELECT uuid, name FROM cascade"):
            rows = [self._cascade_row] if self._cascade_row is not None else []
            return _Rows(rows)
        if query.startswith("SELECT revision_uuid FROM ref"):
            _plan_uuid, name = params
            value = self._ref_rows.get(name)
            return _Rows([(value,)] if value is not None else [])
        if query.startswith("SELECT head_revision_uuid FROM plan"):
            return _Rows([(self._head_revision,)])
        if query.startswith("SELECT node_path, child_level, revision_uuid, cascade_uuid"):
            return _Rows(self._common_rows)
        raise AssertionError(query)


def _step(uuid_value, parent_uuid, level, step_id, concepts):
    return Step(
        uuid=uuid_value,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=[],
        concepts=concepts,
        project_id=None,
        status="draft",
    )


def _tree(steps):
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


def test_common_current_missing_block_is_error():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", [])
    tree = _tree([gs, ts])
    conn = _FakeConn(common_rows=[])

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs, ts])

    assert len(findings) == 1
    assert findings[0].check_id == "context_coverage.common_current"
    assert findings[0].severity == "error"
    assert findings[0].artifact_path == "G-001"


def test_common_current_no_children_is_skipped():
    gs = _step(uuid4(), None, 3, "G-001", [])
    tree = _tree([gs])
    conn = _FakeConn(common_rows=[])

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs])

    assert findings == []


def test_common_current_happy_path_no_cascade():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", [])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            HEAD_REVISION,
            None,
            ["C-001", "C-002"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(common_rows=common_rows)

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs, ts])

    assert findings == []


def test_common_current_stale_revision_counts_as_absent():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", [])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            OTHER_REVISION,
            None,
            ["C-001"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(common_rows=common_rows)

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs, ts])

    assert len(findings) == 1
    assert findings[0].artifact_path == "G-001"


def test_common_current_open_cascade_uses_ref_not_head():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", [])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            CASCADE_REVISION,
            CASCADE_UUID,
            ["C-001"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(
        common_rows=common_rows,
        cascade_row=(CASCADE_UUID, CASCADE_NAME),
        ref_rows={CASCADE_NAME: CASCADE_REVISION},
    )

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs, ts])

    assert findings == []


def test_common_current_open_cascade_stale_within_cascade_is_absent():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", [])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            OTHER_REVISION,
            CASCADE_UUID,
            ["C-001"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(
        common_rows=common_rows,
        cascade_row=(CASCADE_UUID, CASCADE_NAME),
        ref_rows={CASCADE_NAME: CASCADE_REVISION},
    )

    findings = check_context_coverage_common_current(conn, PLAN_UUID, tree, [gs, ts])

    assert len(findings) == 1


def test_specific_subset_happy_path():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", ["C-001"])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            HEAD_REVISION,
            None,
            ["C-001", "C-002"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(common_rows=common_rows)

    findings = check_context_coverage_specific_subset(conn, PLAN_UUID, tree, [gs, ts])

    assert findings == []


def test_specific_subset_exceeding_concept_is_error():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", ["C-001", "C-099"])
    tree = _tree([gs, ts])
    common_rows = [
        (
            "G-001",
            4,
            HEAD_REVISION,
            None,
            ["C-001"],
            datetime(2026, 7, 16, tzinfo=timezone.utc),
        )
    ]
    conn = _FakeConn(common_rows=common_rows)

    findings = check_context_coverage_specific_subset(conn, PLAN_UUID, tree, [gs, ts])

    assert len(findings) == 1
    assert findings[0].check_id == "context_coverage.specific_subset"
    assert findings[0].artifact_path == "G-001/T-001"
    assert "C-099" in findings[0].message


def test_specific_subset_skips_when_parent_common_missing():
    gs_uuid = uuid4()
    gs = _step(gs_uuid, None, 3, "G-001", [])
    ts = _step(uuid4(), gs_uuid, 4, "T-001", ["C-001"])
    tree = _tree([gs, ts])
    conn = _FakeConn(common_rows=[])

    findings = check_context_coverage_specific_subset(conn, PLAN_UUID, tree, [gs, ts])

    assert findings == []


def test_specific_subset_skips_when_parent_not_in_tree():
    ts = _step(uuid4(), uuid4(), 4, "T-001", ["C-001"])
    tree = _tree([ts])
    conn = _FakeConn(common_rows=[])

    findings = check_context_coverage_specific_subset(conn, PLAN_UUID, tree, [ts])

    assert findings == []


def test_original_twentyone_checks_unchanged():
    assert GROUP_ORDER[:6] == _ORIGINAL_GROUP_ORDER
    for group, check_ids in _ORIGINAL_CHECK_IDS.items():
        assert CHECK_IDS[group] == check_ids


def test_context_coverage_group_is_wired():
    assert "context_coverage" in GROUP_ORDER
    assert CHECK_IDS["context_coverage"] == [
        "context_coverage.common_current",
        "context_coverage.specific_subset",
    ]
