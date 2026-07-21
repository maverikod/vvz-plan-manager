"""Regression/contract tests for the step_search command (G-002/T-002/A-003)."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands import step_search_command
from plan_manager.commands.step_search_command import StepSearchCommand
from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.domain.step import Step
from plan_manager.views.branch import Branch


def _fake_db():
    @contextmanager
    def _cm():
        yield object()
    return _cm()


class _DummyPlan:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()


def _make_step(level: int, step_id: str, parent_uuid, fields: dict) -> Step:
    return Step(
        uuid=uuid.uuid4(), plan_uuid=uuid.uuid4(), parent_step_uuid=parent_uuid,
        level=level, step_id=step_id, slug="slug", fields=fields, depends_on=[],
        concepts=[], project_id=None, status="draft",
    )


def _build_nodes():
    gs = _make_step(3, "G-001", None, {"name": "Surface conventions", "description": "Holds a needle in the haystack description."})
    ts = _make_step(4, "T-001", gs.uuid, {"name": "Tactical needle step", "description": "no match field here"})
    atomic = _make_step(5, "A-001", ts.uuid, {"name": "atomic", "target_file": "plan_manager/x.py", "prompt": "find the needle please"})
    extra = _make_step(3, "G-002", None, {"name": "Extra branch", "description": "also has a needle but outside the branch"})
    nodes = {s.uuid: s for s in (gs, ts, atomic, extra)}
    return nodes, gs, ts, atomic, extra


def _assert_domain_error(result, code: str) -> None:
    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == code


def test_substring_search_finds_matches_across_levels(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="needle"))
    payload = result.to_dict()
    assert payload["success"] is True
    paths = {m["path"] for m in payload["data"]["matches"]}
    assert "G-001" in paths
    assert "G-001/T-001/A-001" in paths
    assert "G-002" in paths
    assert payload["data"]["total"] == len(payload["data"]["matches"])


def test_pagination_limits_page_size(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="needle", limit=1, offset=0))
    payload = result.to_dict()
    assert payload["success"] is True
    assert len(payload["data"]["matches"]) == 1
    assert payload["data"]["total"] > 1
    assert payload["data"]["limit"] == 1
    assert payload["data"]["offset"] == 0


def test_regex_mode_finds_match(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="need.e", mode="regex"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["total"] >= 1


def test_invalid_regex_syntax_raises_invalid_filter(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="(unclosed", mode="regex"))
    _assert_domain_error(result, "INVALID_FILTER")


def test_pattern_too_long_raises_invalid_filter(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(StepSearchCommand().execute(plan="p", pattern="a" * 201))
    _assert_domain_error(result, "INVALID_FILTER")


def test_branch_scope_requires_all_three_step_ids() -> None:
    try:
        StepSearchCommand().validate_params({"plan": "p", "pattern": "needle", "scope": "branch", "gs_step_id": "G-001"})
        raised = False
    except InvalidParamsError:
        raised = True
    assert raised is True


def test_plan_scope_rejects_branch_step_ids() -> None:
    try:
        StepSearchCommand().validate_params({"plan": "p", "pattern": "needle", "scope": "plan", "gs_step_id": "G-001"})
        raised = False
    except InvalidParamsError:
        raised = True
    assert raised is True


def test_validate_params_rejects_invalid_regex() -> None:
    try:
        StepSearchCommand().validate_params({"plan": "p", "pattern": "(unclosed", "mode": "regex"})
        raised = False
    except InvalidParamsError:
        raised = True
    assert raised is True


def test_validate_params_substring_mode_skips_regex_validation() -> None:
    params = StepSearchCommand().validate_params({"plan": "p", "pattern": "(unclosed", "mode": "substring"})
    assert params["pattern"] == "(unclosed"


def test_schema_declares_enums_and_additional_properties_false() -> None:
    schema = StepSearchCommand.get_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["mode"]["enum"] == ["substring", "regex"]
    assert schema["properties"]["scope"]["enum"] == ["plan", "branch"]
    assert schema["required"] == ["plan", "pattern"]


def test_metadata_error_codes_are_registered_domain_codes() -> None:
    metadata = StepSearchCommand.metadata()
    assert set(metadata["error_cases"].keys()).issubset(DOMAIN_CODES)


def test_branch_scope_searches_only_branch_steps(monkeypatch) -> None:
    nodes, gs, ts, atomic, extra = _build_nodes()
    branch = Branch(plan_uuid=uuid.uuid4(), gs=gs, ts=ts, atomic=atomic, hrs_slice=[])
    monkeypatch.setattr(step_search_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_search_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_search_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_search_command, "resolve_branch", lambda conn, plan_uuid, g, t, a: branch)

    result = asyncio.run(StepSearchCommand().execute(
        plan="p", pattern="needle", scope="branch",
        gs_step_id="G-001", ts_step_id="T-001", as_step_id="A-001",
    ))
    payload = result.to_dict()
    assert payload["success"] is True
    paths = {m["path"] for m in payload["data"]["matches"]}
    assert "G-002" not in paths
    assert all(p.startswith("G-001") for p in paths)
