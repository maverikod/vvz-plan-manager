"""Regression tests for todo 3c762bfe: cascade_preview must return compact
summary counts by default and offer a paginated, filterable "entries" detail
page via view=full, instead of embedding the raw unbounded change_set.

Covers:
- build_preview_entries: unified/deterministic entry construction, entity
  classification (step-for-free vs. batched identity resolution).
- cascade_preview_projection: category/check_id parsing, entry filtering,
  summary counting.
- CascadePreviewCommand: default (summary) shape, view=full shape, pagination,
  filters, and that CASCADE_REQUIRED / INVALID_FILTER / INVALID_PAGINATION
  still surface correctly.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.cascade.preview import build_preview_entries, needs_review_steps
from plan_manager.commands.cascade_preview_command import CascadePreviewCommand
from plan_manager.commands.cascade_preview_projection import filter_entries, parse_category, summarize
from plan_manager.domain.step import Step
from plan_manager.verify.finding import CheckResult, Finding, Report


def _step(uuid_: uuid.UUID, *, level: int, step_id: str, status: str, parent: uuid.UUID | None = None) -> Step:
    return Step(
        uuid=uuid_,
        plan_uuid=uuid.uuid4(),
        parent_step_uuid=parent,
        level=level,
        step_id=step_id,
        slug="slug",
        fields={},
        depends_on=[],
        concepts=[],
        project_id=None,
        status=status,
    )


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal conn.execute(...).fetchall() stand-in for resolve_entity_identities_batch."""

    def __init__(self, identity_rows: dict[uuid.UUID, tuple]):
        self._identity_rows = identity_rows

    def execute(self, sql, params):
        assert "entity_identity" in sql
        (ids,) = params
        rows = [self._identity_rows[i] for i in ids if i in self._identity_rows]
        return _FakeCursor(rows)


G1 = uuid.UUID("00000000-0000-0000-0000-000000000101")
T1 = uuid.UUID("00000000-0000-0000-0000-000000000102")
CONCEPT_1 = uuid.UUID("00000000-0000-0000-0000-000000000201")


def _nodes() -> dict[uuid.UUID, Step]:
    g1 = _step(G1, level=3, step_id="G-001", status="draft")
    t1 = _step(T1, level=4, step_id="T-001", status="needs_review", parent=G1)
    return {G1: g1, T1: t1}


def _report(*, findings: list[Finding]) -> Report:
    by_check: dict[str, list[Finding]] = {}
    for f in findings:
        by_check.setdefault(f.check_id, []).append(f)
    checks = [
        CheckResult(check_id=check_id, passed=False, findings=matched)
        for check_id, matched in by_check.items()
    ]
    return Report(checks=checks, green=not findings)


# --------------------------------------------------------------------------
# build_preview_entries
# --------------------------------------------------------------------------


def test_needs_review_steps_filters_and_sorts_by_artifact_path():
    nodes = _nodes()
    result = needs_review_steps(nodes)
    assert [s.uuid for s in result] == [T1]


def test_build_preview_entries_classifies_step_without_identity_query():
    nodes = _nodes()
    change_set = {"added": [T1], "removed": [], "changed": []}
    conn = _FakeConn({})  # no identity rows needed: T1 resolves via nodes
    entries = build_preview_entries(conn, nodes, change_set, _report(findings=[]))

    added = [e for e in entries if e["category"] == "added"]
    assert len(added) == 1
    assert added[0]["entity_type"] == "step"
    assert added[0]["step_path"] == "G-001/T-001"
    assert added[0]["step_status"] == "needs_review"


def test_build_preview_entries_batches_identity_resolution_for_non_step_entities():
    nodes = _nodes()
    change_set = {"added": [CONCEPT_1], "removed": [], "changed": []}
    conn = _FakeConn({CONCEPT_1: (CONCEPT_1, "concept", "concept", None)})
    entries = build_preview_entries(conn, nodes, change_set, _report(findings=[]))

    added = [e for e in entries if e["category"] == "added"]
    assert added[0]["entity_type"] == "concept"
    assert added[0]["step_path"] is None


def test_build_preview_entries_unresolvable_entity_is_none_not_raise():
    nodes = _nodes()
    ghost = uuid.uuid4()
    change_set = {"added": [ghost], "removed": [], "changed": []}
    conn = _FakeConn({})
    entries = build_preview_entries(conn, nodes, change_set, _report(findings=[]))

    added = [e for e in entries if e["category"] == "added"]
    assert added[0]["entity_type"] is None


def test_build_preview_entries_deterministic_order_and_needs_review_gate_finding_included():
    nodes = _nodes()
    change_set = {
        "added": [T1],
        "removed": [G1],
        "changed": [{"entity_uuid": T1, "fields": ["fields"]}],
    }
    finding = Finding(check_id="coverage.gs", severity="error", artifact_path="G-001", message="concept missing")
    conn = _FakeConn({})
    entries_a = build_preview_entries(conn, nodes, change_set, _report(findings=[finding]))
    entries_b = build_preview_entries(conn, nodes, change_set, _report(findings=[finding]))

    categories = [e["category"] for e in entries_a]
    # added(0) < removed(1) < changed(2) < needs_review(3) < gate_finding(4)
    assert categories == sorted(categories, key=lambda c: {
        "added": 0, "removed": 1, "changed": 2, "needs_review": 3, "gate_finding": 4,
    }[c])
    assert entries_a == entries_b  # stable/deterministic across repeated builds

    gate_entries = [e for e in entries_a if e["category"] == "gate_finding"]
    assert gate_entries == [{
        "category": "gate_finding", "check_id": "coverage.gs", "severity": "error",
        "artifact_path": "G-001", "message": "concept missing",
    }]

    changed_entries = [e for e in entries_a if e["category"] == "changed"]
    assert changed_entries[0]["fields"] == ["fields"]


# --------------------------------------------------------------------------
# cascade_preview_projection: parse_category / filter_entries / summarize
# --------------------------------------------------------------------------


def test_parse_category_accepts_known_values_and_none():
    assert parse_category(None) is None
    assert parse_category("gate_finding") == "gate_finding"


def test_parse_category_rejects_unknown_value():
    from plan_manager.commands.errors import DomainCommandError

    with pytest.raises(DomainCommandError) as exc_info:
        parse_category("bogus")
    assert exc_info.value.code == "INVALID_FILTER"


def _sample_entries():
    return [
        {"category": "added", "entity_uuid": "e1", "entity_type": "step", "step_path": "G-001", "step_status": "draft"},
        {"category": "added", "entity_uuid": "e2", "entity_type": "concept", "step_path": None, "step_status": None},
        {"category": "needs_review", "entity_uuid": "e1", "entity_type": "step", "step_path": "G-001", "step_status": "needs_review"},
        {"category": "gate_finding", "check_id": "coverage.gs", "severity": "error", "artifact_path": "G-001", "message": "m"},
        {"category": "gate_finding", "check_id": "coverage.relations", "severity": "warning", "artifact_path": "G-002", "message": "m2"},
    ]


def test_filter_entries_by_category():
    result = filter_entries(_sample_entries(), category="gate_finding")
    assert len(result) == 2
    assert all(e["category"] == "gate_finding" for e in result)


def test_filter_entries_by_check_id_only_touches_gate_findings():
    result = filter_entries(_sample_entries(), check_id="coverage.gs")
    assert result == [{"category": "gate_finding", "check_id": "coverage.gs", "severity": "error", "artifact_path": "G-001", "message": "m"}]


def test_filter_entries_by_entity_type_and_step_and_status_compose():
    result = filter_entries(_sample_entries(), entity_type="step", step="e1", status="draft")
    assert len(result) == 1
    assert result[0]["category"] == "added"


def test_summarize_reflects_unfiltered_totals():
    counts = summarize(_sample_entries())
    assert counts == {"added": 2, "removed": 0, "changed": 0, "needs_review": 1, "gate_findings": 2}


# --------------------------------------------------------------------------
# CascadePreviewCommand: end-to-end shape via monkeypatched db layer
# --------------------------------------------------------------------------


CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000301")
BASE_REV = uuid.UUID("00000000-0000-0000-0000-000000000302")
TIP_REV = uuid.UUID("00000000-0000-0000-0000-000000000303")


class _Plan:
    def __init__(self):
        self.uuid = uuid.uuid4()
        self.name = "preview-plan"


def _preview_data():
    entries = [
        {"category": "added", "entity_uuid": str(T1), "entity_type": "step", "step_path": "G-001/T-001", "step_status": "draft"},
        {"category": "needs_review", "entity_uuid": str(T1), "entity_type": "step", "step_path": "G-001/T-001", "step_status": "needs_review"},
        {"category": "gate_finding", "check_id": "coverage.gs", "severity": "error", "artifact_path": "G-001", "message": "m"},
    ]
    return {
        "cascade_uuid": str(CASCADE_UUID),
        "base_revision_uuid": str(BASE_REV),
        "tip_revision_uuid": str(TIP_REV),
        "change_set": {"added": [T1], "removed": [], "changed": []},
        "needs_review": ["G-001/T-001"],
        "gate_green": False,
        "gate_report_json": '{"green": false}',
        "entries": entries,
    }


def _patch_command(monkeypatch, *, cascade_open: bool = True):
    @contextmanager
    def fake_db_connection():
        yield object()

    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.db_connection", fake_db_connection)
    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.resolve_plan", lambda _conn, _plan: _Plan())
    monkeypatch.setattr(
        "plan_manager.commands.cascade_preview_command.get_open_cascade",
        lambda _conn, _plan_uuid: object() if cascade_open else None,
    )
    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.preview_cascade", lambda _conn, _plan_uuid: _preview_data())


def test_default_view_returns_summary_only_no_entries(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan"))
    data = result.to_dict()["data"]

    assert data["cascade_uuid"] == str(CASCADE_UUID)
    assert data["gate_green"] is False
    assert data["summary"] == {"added": 1, "removed": 0, "changed": 0, "needs_review": 1, "gate_findings": 1}
    assert "entries" not in data
    assert "change_set" not in data
    assert "gate_report_json" not in data


def test_view_full_returns_paginated_entries_and_gate_report_json(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full"))
    data = result.to_dict()["data"]

    assert data["total"] == 3
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["entries"]) == 3
    assert data["gate_report_json"] == '{"green": false}'
    assert data["summary"] == {"added": 1, "removed": 0, "changed": 0, "needs_review": 1, "gate_findings": 1}


def test_view_full_with_category_filter_narrows_entries_and_total(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", category="gate_finding"))
    data = result.to_dict()["data"]

    assert data["total"] == 1
    assert data["entries"][0]["category"] == "gate_finding"
    # summary is unaffected by the category filter (always the real totals)
    assert data["summary"]["added"] == 1


def test_view_full_pagination_bounds_page_size(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", limit=1, offset=1))
    data = result.to_dict()["data"]

    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["entries"]) == 1
    assert data["total"] == 3


def test_invalid_category_surfaces_invalid_filter(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", category="bogus"))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_FILTER"


def test_invalid_pagination_surfaces_invalid_pagination(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", limit=0))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_cascade_required_still_returned_when_no_open_cascade(monkeypatch):
    _patch_command(monkeypatch, cascade_open=False)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan"))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"
