"""Regression test for bug 35ab178e: step_list, step_search, files_report,
step_xref, and runtime_link_list must all return the uniform C-001
pagination envelope {<entity-named list>, total, limit, offset} — no
total_count, no missing limit/offset echo. Exercises each command's
execute() path with stubbed stores per repo test idiom (see
tests/test_step_search_command.py).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    files_report_command,
    runtime_link_list_command,
    step_list_command,
    step_search_command,
    step_xref_command,
)
from plan_manager.commands.files_report_command import FilesReportCommand
from plan_manager.commands.runtime_link_list_command import RuntimeLinkListCommand
from plan_manager.commands.step_list_command import StepListCommand
from plan_manager.commands.step_search_command import StepSearchCommand
from plan_manager.commands.step_xref_command import StepXrefCommand
from plan_manager.domain.runtime_link import RuntimeLink
from plan_manager.domain.step import Step

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

ENVELOPE_KEYS = {"total", "limit", "offset"}


def _fake_db():
    @contextmanager
    def _cm():
        yield object()
    return _cm()


class _DummyPlan:
    def __init__(self) -> None:
        self.uuid = PLAN_UUID


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    fields: dict | None = None,
) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields if fields is not None else {},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _two_step_nodes() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid)
    return {step.uuid: step for step in (gs, ts)}


def test_step_list_envelope_uses_total_limit_offset(monkeypatch) -> None:
    nodes = _two_step_nodes()
    monkeypatch.setattr(step_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_list_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_list_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepListCommand().execute(plan="p", limit=1, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"steps"} | ENVELOPE_KEYS
    assert "total_count" not in data
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["steps"]) == 1


def test_step_search_envelope_uses_total_limit_offset(monkeypatch) -> None:
    gs = _step(
        "00000000-0000-0000-0000-000000000021", 3, "G-001", None,
        fields={"name": "Surface", "description": "has a needle in it"},
    )
    nodes = {gs.uuid: gs}
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="needle", limit=50, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"matches"} | ENVELOPE_KEYS
    assert "total_count" not in data
    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["matches"]) == 1


def test_files_report_envelope_uses_total_limit_offset(monkeypatch) -> None:
    gs = _step("00000000-0000-0000-0000-000000000031", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000032", 4, "T-001", gs.uuid)
    a1 = _step(
        "00000000-0000-0000-0000-000000000033", 5, "A-001", ts.uuid,
        fields={"target_file": "a.py", "operation": "create_file", "priority": 1},
    )
    nodes = {step.uuid: step for step in (gs, ts, a1)}
    monkeypatch.setattr(files_report_command, "db_connection", _fake_db)
    monkeypatch.setattr(files_report_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(files_report_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(FilesReportCommand().execute(plan="p", limit=50, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"files"} | ENVELOPE_KEYS
    assert "total_count" not in data
    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["files"]) == 1


def test_step_xref_envelope_uses_total_limit_offset(monkeypatch) -> None:
    shared_text = "shared prompt fragment"
    gs = _step("00000000-0000-0000-0000-000000000041", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000042", 4, "T-001", gs.uuid)
    a1 = _step(
        "00000000-0000-0000-0000-000000000043", 5, "A-001", ts.uuid,
        fields={"prompt": shared_text},
    )
    a2 = _step(
        "00000000-0000-0000-0000-000000000044", 5, "A-002", ts.uuid,
        fields={"prompt": shared_text},
    )
    nodes = {step.uuid: step for step in (gs, ts, a1, a2)}
    monkeypatch.setattr(step_xref_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_xref_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_xref_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepXrefCommand().execute(plan="p", text=shared_text, limit=50, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"locations"} | ENVELOPE_KEYS
    assert "total_count" not in data
    assert data["total"] == 2
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["locations"]) == 2


def test_runtime_link_list_envelope_uses_total_limit_offset(monkeypatch) -> None:
    link = RuntimeLink(
        link_uuid=uuid.UUID("00000000-0000-0000-0000-000000000051"),
        from_entity_type="bug",
        from_entity_uuid=uuid.UUID("00000000-0000-0000-0000-000000000052"),
        to_entity_type="todo",
        to_entity_uuid=uuid.UUID("00000000-0000-0000-0000-000000000053"),
        link_type="relates_to",
        created_by="tester",
        created_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        deleted_at=None,
    )
    monkeypatch.setattr(runtime_link_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(runtime_link_list_command, "list_runtime_links", lambda conn, **kwargs: [link])

    result = asyncio.run(RuntimeLinkListCommand().execute(limit=50, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"runtime_links"} | ENVELOPE_KEYS
    assert "total_count" not in data
    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["runtime_links"]) == 1
