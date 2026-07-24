"""Regression tests for todo b6ed4b0b: cascade_preview's view=full
gate_report_json must be bounded, not embed EVERY finding of EVERY check
plan-wide regardless of the generic entries pagination.

Root cause (verified facts from the todo): the "entries" pagination shipped
by todo 3c762bfe bounds the unified detail-entries page, but
cascade_preview_command.py separately assigned
response["gate_report_json"] = data["gate_report_json"] verbatim --
plan_manager.verify.finding.render_json serializes EVERY check and EVERY
finding plan-wide, unbounded, independent of any entries paging.

Fix: paginate_gate_report_json (cascade_preview_projection.py) parses the
raw canonical gate_report_json and rebuilds it with each check's "findings"
list narrowed to its slice of a [gate_findings_offset, gate_findings_offset
+ gate_findings_limit) window computed over the FLATTENED findings list
across every check (same "flatten across checks" order render_json/
build_report already produce); the per-check structure (check_id, passed)
stays, each check gains a "finding_count" (its real, unbounded total), and
the response gains "gate_findings_total" (the report-wide true total) plus
the applied "gate_findings_limit"/"gate_findings_offset".

Covers:
- paginate_gate_report_json: characterizes the OLD unbounded shape as the
  input it must consume, and asserts the NEW bounded shape it produces,
  including a window that spans a check boundary and an empty-checks input.
- parse_gate_findings_pagination: default/valid/invalid inputs, mirroring
  runtime_filtering.parse_pagination's INVALID_PAGINATION conventions.
- CascadePreviewCommand: end-to-end view=full shape carries
  gate_findings_total/limit/offset and a correctly bounded gate_report_json;
  gate_findings_limit/offset validation errors surface as INVALID_PAGINATION.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands.cascade_preview_command import CascadePreviewCommand
from plan_manager.commands.cascade_preview_projection import (
    paginate_gate_report_json,
    parse_gate_findings_pagination,
)
from plan_manager.commands.errors import DomainCommandError
from plan_manager.verify.finding import Finding, build_report, render_json


# --------------------------------------------------------------------------
# fixtures: a real, unbounded gate_report_json (via the actual production
# render_json/build_report pipeline) with findings spanning 3 checks and a
# check boundary crossing the default page size.
# --------------------------------------------------------------------------


def _findings() -> list[Finding]:
    a = [Finding(check_id="A", severity="error", artifact_path="A-block", message=f"a{i}") for i in range(3)]
    # check B has zero findings -> passed=True, must still appear bounded
    # with finding_count == 0.
    c = [
        Finding(check_id="C", severity="warning", artifact_path="C-block", message=f"m{i:03d}")
        for i in range(60)
    ]
    return a + c


def _raw_gate_report_json() -> str:
    report = build_report(["A", "B", "C"], _findings())
    return render_json(report)


# --------------------------------------------------------------------------
# paginate_gate_report_json
# --------------------------------------------------------------------------


def test_raw_gate_report_json_characterizes_the_old_unbounded_shape():
    """Characterize what render_json produces before pagination: EVERY
    finding of EVERY check, unbounded -- this is the todo's reproduction of
    the OLD (defect) shape cascade_preview used to embed verbatim."""
    raw = json.loads(_raw_gate_report_json())
    assert raw["green"] is False
    by_id = {c["check_id"]: c for c in raw["checks"]}
    assert len(by_id["A"]["findings"]) == 3
    assert by_id["B"]["passed"] is True
    assert len(by_id["B"]["findings"]) == 0
    assert len(by_id["C"]["findings"]) == 60
    # no "finding_count" key existed pre-fix
    assert "finding_count" not in by_id["A"]


def test_paginate_gate_report_json_default_window_spans_a_check_boundary():
    raw = _raw_gate_report_json()
    bounded_json, total = paginate_gate_report_json(raw, limit=50, offset=0)
    assert total == 63  # 3 (A) + 0 (B) + 60 (C), the true unbounded total

    bounded = json.loads(bounded_json)
    by_id = {c["check_id"]: c for c in bounded["checks"]}

    # A's findings are fully inside the window: all 3 returned, finding_count == 3.
    assert by_id["A"]["finding_count"] == 3
    assert [f["message"] for f in by_id["A"]["findings"]] == ["a0", "a1", "a2"]
    assert by_id["A"]["passed"] is False

    # B is untouched: zero real findings, zero windowed findings.
    assert by_id["B"]["finding_count"] == 0
    assert by_id["B"]["findings"] == []
    assert by_id["B"]["passed"] is True

    # C's real total (60) is preserved via finding_count even though only
    # the first 47 of its findings fall inside the 50-wide window that
    # started 3 findings into A.
    assert by_id["C"]["finding_count"] == 60
    assert len(by_id["C"]["findings"]) == 47
    assert [f["message"] for f in by_id["C"]["findings"]] == [f"m{i:03d}" for i in range(47)]


def test_paginate_gate_report_json_offset_page_continues_across_boundary():
    raw = _raw_gate_report_json()
    bounded_json, total = paginate_gate_report_json(raw, limit=200, offset=50)
    assert total == 63

    bounded = json.loads(bounded_json)
    by_id = {c["check_id"]: c for c in bounded["checks"]}

    assert by_id["A"]["findings"] == []  # fully consumed by the first page
    assert by_id["A"]["finding_count"] == 3
    assert by_id["B"]["findings"] == []
    # C contributes its remaining findings: flat indices 50..62 -> C-local 47..59.
    assert by_id["C"]["finding_count"] == 60
    assert [f["message"] for f in by_id["C"]["findings"]] == [f"m{i:03d}" for i in range(47, 60)]


def test_paginate_gate_report_json_empty_checks_key_treated_as_no_checks():
    bounded_json, total = paginate_gate_report_json('{"green": true}', limit=50, offset=0)
    assert total == 0
    assert json.loads(bounded_json) == {"green": True, "checks": []}


def test_paginate_gate_report_json_never_mutates_input():
    raw = _raw_gate_report_json()
    before = json.loads(raw)
    paginate_gate_report_json(raw, limit=1, offset=0)
    after = json.loads(raw)
    assert before == after


# --------------------------------------------------------------------------
# parse_gate_findings_pagination
# --------------------------------------------------------------------------


def test_parse_gate_findings_pagination_defaults():
    pagination = parse_gate_findings_pagination({})
    assert pagination.limit == 50
    assert pagination.offset == 0


def test_parse_gate_findings_pagination_accepts_valid_bounds():
    pagination = parse_gate_findings_pagination({"gate_findings_limit": 200, "gate_findings_offset": 5})
    assert pagination.limit == 200
    assert pagination.offset == 5


def test_parse_gate_findings_pagination_rejects_limit_out_of_range():
    with pytest.raises(DomainCommandError) as exc_info:
        parse_gate_findings_pagination({"gate_findings_limit": 0})
    assert exc_info.value.code == "INVALID_PAGINATION"
    assert "gate_findings_limit" in str(exc_info.value)

    with pytest.raises(DomainCommandError) as exc_info:
        parse_gate_findings_pagination({"gate_findings_limit": 201})
    assert exc_info.value.code == "INVALID_PAGINATION"


def test_parse_gate_findings_pagination_rejects_non_integer_limit():
    with pytest.raises(DomainCommandError) as exc_info:
        parse_gate_findings_pagination({"gate_findings_limit": "50"})
    assert exc_info.value.code == "INVALID_PAGINATION"


def test_parse_gate_findings_pagination_rejects_negative_offset():
    with pytest.raises(DomainCommandError) as exc_info:
        parse_gate_findings_pagination({"gate_findings_offset": -1})
    assert exc_info.value.code == "INVALID_PAGINATION"
    assert "gate_findings_offset" in str(exc_info.value)


# --------------------------------------------------------------------------
# CascadePreviewCommand: end-to-end, monkeypatched db layer
# --------------------------------------------------------------------------


CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000401")
BASE_REV = uuid.UUID("00000000-0000-0000-0000-000000000402")
TIP_REV = uuid.UUID("00000000-0000-0000-0000-000000000403")


class _Plan:
    def __init__(self):
        self.uuid = uuid.uuid4()
        self.name = "preview-plan"


def _preview_data():
    return {
        "cascade_uuid": str(CASCADE_UUID),
        "base_revision_uuid": str(BASE_REV),
        "tip_revision_uuid": str(TIP_REV),
        "change_set": {"added": [], "removed": [], "changed": []},
        "needs_review": [],
        "gate_green": False,
        "gate_report_json": _raw_gate_report_json(),
        "entries": [],
    }


def _patch_command(monkeypatch):
    @contextmanager
    def fake_db_connection():
        yield object()

    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.db_connection", fake_db_connection)
    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.resolve_plan", lambda _conn, _plan: _Plan())
    monkeypatch.setattr(
        "plan_manager.commands.cascade_preview_command.get_open_cascade", lambda _conn, _plan_uuid: object()
    )
    monkeypatch.setattr("plan_manager.commands.cascade_preview_command.preview_cascade", lambda _conn, _plan_uuid: _preview_data())


def test_view_full_default_gate_findings_pagination(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full"))
    data = result.to_dict()["data"]

    assert data["gate_findings_total"] == 63
    assert data["gate_findings_limit"] == 50
    assert data["gate_findings_offset"] == 0

    bounded = json.loads(data["gate_report_json"])
    by_id = {c["check_id"]: c for c in bounded["checks"]}
    assert by_id["A"]["finding_count"] == 3
    assert by_id["C"]["finding_count"] == 60
    assert len(by_id["C"]["findings"]) == 47  # 50-wide window minus A's 3


def test_view_full_custom_gate_findings_pagination(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(
        CascadePreviewCommand().execute(
            plan="preview-plan", view="full", gate_findings_limit=1, gate_findings_offset=1
        )
    )
    data = result.to_dict()["data"]

    assert data["gate_findings_total"] == 63
    assert data["gate_findings_limit"] == 1
    assert data["gate_findings_offset"] == 1

    bounded = json.loads(data["gate_report_json"])
    by_id = {c["check_id"]: c for c in bounded["checks"]}
    # flat index 1 is A's second finding ("a1"); window width 1.
    assert by_id["A"]["findings"] == [
        {"artifact_path": "A-block", "check_id": "A", "message": "a1", "severity": "error"}
    ]
    assert by_id["A"]["finding_count"] == 3
    assert by_id["C"]["findings"] == []
    assert by_id["C"]["finding_count"] == 60


def test_view_full_gate_findings_pagination_independent_of_entries_pagination(monkeypatch):
    """gate_findings_limit/offset must not be conflated with the generic
    entries limit/offset -- the two page independently (todo b6ed4b0b)."""
    _patch_command(monkeypatch)

    result = asyncio.run(
        CascadePreviewCommand().execute(plan="preview-plan", view="full", limit=5, offset=0, gate_findings_limit=200)
    )
    data = result.to_dict()["data"]

    assert data["limit"] == 5  # entries pagination, unaffected
    assert data["gate_findings_limit"] == 200  # gate pagination, independently applied
    bounded = json.loads(data["gate_report_json"])
    by_id = {c["check_id"]: c for c in bounded["checks"]}
    assert len(by_id["C"]["findings"]) == 60  # all of C fits inside a 200-wide window


def test_invalid_gate_findings_limit_surfaces_invalid_pagination(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", gate_findings_limit=0))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_invalid_gate_findings_offset_surfaces_invalid_pagination(monkeypatch):
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan", view="full", gate_findings_offset=-1))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_view_summary_never_computes_gate_findings_pagination(monkeypatch):
    """view=summary must not include any gate_findings_* keys (unchanged
    contract; only view=full is bounded/pages gate_report_json)."""
    _patch_command(monkeypatch)

    result = asyncio.run(CascadePreviewCommand().execute(plan="preview-plan"))
    data = result.to_dict()["data"]

    assert "gate_report_json" not in data
    assert "gate_findings_total" not in data
    assert "gate_findings_limit" not in data
    assert "gate_findings_offset" not in data
