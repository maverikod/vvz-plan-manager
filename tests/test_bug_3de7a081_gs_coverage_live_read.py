"""Regression test for bug 3de7a081: coverage.gs was reported (against the
doc-store plan's open cascade) to evaluate a state inconsistent with the
concepts persisted by sequential in-cascade step_update calls, while
step_get read back the same calls' persisted concepts correctly and
coverage.relations passed.

Live reproduction against 0.1.57 (three scratch-plan trials on
scratch-bugrepro-3de7a081, hard-deleted after) disproved the divergent
read path theory: check_coverage_gs (plan_manager.verify.gate) and its
gs_coverage view (plan_manager.views.coverage) always read the exact rows
handed to them by the open connection -- the SAME "step" table row set
step_get resolves, with no revision overlay or cache layer at any level.
The doc-store plan's flagged GS (e.g. G-007's own concept C-061) had no
TS child referencing the concept at all: a genuine, still-open authoring
gap, not a stale/divergent read.

These tests pin that behavior at the unit level using the real
check_coverage_gs / gs_coverage functions against a fake connection (repo
convention, see test_step_update_validation.py / test_gate_context_coverage.py),
so a future change that introduces caching or a stale read path here
would fail immediately.
"""

from __future__ import annotations

import uuid

from plan_manager.verify.gate import check_coverage_gs
from plan_manager.views.coverage import gs_coverage

PLAN_UUID = uuid.uuid4()
GS_UUID = uuid.uuid4()
TS_UUID = uuid.uuid4()


class _Rows:
    """Minimal cursor-shaped wrapper over a fixed row list."""

    def __init__(self, rows: list) -> None:
        """Store the fixed rows a fake query resolves to.

        Args:
            rows: The row tuples ``fetchall`` returns for this query.
        """
        self._rows = rows

    def fetchall(self) -> list:
        """Return every row registered for this fake query.

        Returns:
            The list of row tuples supplied at construction time.
        """
        return list(self._rows)


class _StepTableConn:
    """Fake connection dispatching only the two queries gs_coverage issues.

    Models the "step" table as it would read immediately after sequential
    in-cascade step_update calls on a GS and its TS child: both rows carry
    whatever concepts list this fixture was built with, exactly mirroring
    what a real, already-committed psycopg connection would return (no
    cascade overlay, no cache -- see plan_manager.domain.step_store,
    which UPDATEs the "step" row in place and commits per-command).
    """

    def __init__(self, gs_concepts: list[str], ts_concepts: list[str]) -> None:
        """Fix the concepts the GS row and its one TS child row carry.

        Args:
            gs_concepts: The level-3 GS row's own ``concepts`` column, as
                it would read immediately after its step_update commit.
            ts_concepts: The level-4 TS child row's own ``concepts``
                column, as it would read immediately after its own,
                possibly separate, step_update commit.
        """
        self._gs_concepts = gs_concepts
        self._ts_concepts = ts_concepts

    def execute(self, query: str, _params: tuple) -> _Rows:
        """Resolve one of gs_coverage's two fixed SELECT statements.

        Args:
            query: The SQL text gs_coverage issued.
            _params: The bound parameters (unused; both queries in this
                fixture are scoped to the single fixed plan_uuid).

        Returns:
            The fixed row set for the matched query.

        Raises:
            AssertionError: If a query neither gs_coverage nor
                check_coverage_gs is expected to issue is received.
        """
        if "SELECT uuid, step_id, concepts FROM step" in query:
            return _Rows([(GS_UUID, "G-001", self._gs_concepts)])
        if "SELECT parent_step_uuid, concepts FROM step" in query:
            return _Rows([(GS_UUID, self._ts_concepts)])
        raise AssertionError(query)


def test_gs_coverage_sees_sequential_in_cascade_updates_on_both_levels() -> None:
    """A concept set on both GS and its TS child within the same cascade
    reports no gap, mirroring step_get's own read of the committed rows.
    """
    conn = _StepTableConn(gs_concepts=["C-001"], ts_concepts=["C-001"])

    report = gs_coverage(conn, PLAN_UUID)["G-001"]

    assert report.missing == []
    assert report.extra == []


def test_check_coverage_gs_reports_no_finding_when_child_already_covers() -> None:
    """check_coverage_gs (the actual "coverage.gs" gate check) produces no
    finding once the TS child's own concepts already cover the GS's own
    concepts -- the exact sequence bug 3de7a081 described as broken.
    """
    conn = _StepTableConn(gs_concepts=["C-001"], ts_concepts=["C-001"])

    findings = check_coverage_gs(conn, PLAN_UUID)

    assert findings == []


def test_check_coverage_gs_flags_a_genuine_uncovered_concept() -> None:
    """A concept present only on the GS (no TS child references it yet)
    is a real authoring gap and must still be flagged -- proving the
    check was never silenced, only ever correctly evaluating live state.
    """
    conn = _StepTableConn(gs_concepts=["C-001", "C-002"], ts_concepts=["C-001"])

    findings = check_coverage_gs(conn, PLAN_UUID)

    assert len(findings) == 1
    assert findings[0].check_id == "coverage.gs"
    assert findings[0].artifact_path == "G-001"
    assert "C-002" in findings[0].message


def test_check_coverage_gs_clears_once_the_child_is_updated_in_turn() -> None:
    """Simulates the second half of an in-cascade fix sequence: after the
    TS child is updated (in a fresh connection, as a real second
    step_update call would commit), the same check clears -- there is no
    cached "still missing" result carried over from the prior read.
    """
    before = check_coverage_gs(
        _StepTableConn(gs_concepts=["C-001", "C-002"], ts_concepts=["C-001"]),
        PLAN_UUID,
    )
    assert len(before) == 1

    after = check_coverage_gs(
        _StepTableConn(gs_concepts=["C-001", "C-002"], ts_concepts=["C-001", "C-002"]),
        PLAN_UUID,
    )
    assert after == []
