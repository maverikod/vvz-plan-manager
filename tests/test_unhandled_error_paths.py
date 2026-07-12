"""Regression tests for bug b3da4ed2: previously unguarded error paths must surface documented
domain codes instead of leaking a raw ValueError (-32603).

  * malformed UUID inputs -> RUNTIME_VALIDATION_ERROR (validate_uuid guards)
  * PromptAssemblyError -> PROMPT_ASSEMBLY_FAILED (branch_prompt / branch_dump)
  * corrupted parent-step chain -> GRAPH_CORRUPTED_CHAIN
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands import (
    block_list_command,
    branch_prompt_command,
    context_specific_command,
    hrs_import_command,
    project_dependency_add_command,
    project_dependency_list_command,
    project_dependency_remove_command,
)
from plan_manager.commands.errors import DOMAIN_CODES, map_exception
from plan_manager.views.dependency_graph import GraphIntegrityError
from plan_manager.views.prompt_assembly import PromptAssemblyError

BAD_UUID = "not-a-valid-uuid"
GOOD_UUID = str(uuid.uuid4())


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    uuid = uuid.uuid4()
    context_budget = 1000


def _stub_plan(conn, plan):
    return _DummyPlan()


def _domain_code(result) -> str:
    return result.to_dict()["error"]["data"]["domain_code"]


def test_context_specific_rejects_malformed_block_id(monkeypatch) -> None:
    monkeypatch.setattr(context_specific_command, "db_connection", _fake_db)
    monkeypatch.setattr(context_specific_command, "resolve_plan", _stub_plan)
    result = asyncio.run(
        context_specific_command.ContextSpecificCommand().execute(
            plan="p", common_block_id=BAD_UUID, concepts=[]
        )
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_block_list_rejects_malformed_revision(monkeypatch) -> None:
    monkeypatch.setattr(block_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(block_list_command, "resolve_plan", _stub_plan)
    result = asyncio.run(
        block_list_command.BlockListCommand().execute(plan="p", revision=BAD_UUID)
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_hrs_import_rejects_malformed_cascade_uuid(monkeypatch) -> None:
    monkeypatch.setattr(hrs_import_command, "db_connection", _fake_db)
    result = asyncio.run(
        hrs_import_command.HrsImportCommand().execute(
            plan="p", source_text="# hi", cascade_uuid=BAD_UUID
        )
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_project_dependency_add_rejects_malformed_project_id(monkeypatch) -> None:
    monkeypatch.setattr(project_dependency_add_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependency_add_command, "resolve_plan", _stub_plan)
    result = asyncio.run(
        project_dependency_add_command.ProjectDependencyAddCommand().execute(
            plan="p", dependent_project_id=BAD_UUID, depends_on_project_id=GOOD_UUID,
            dependency_type="build", discovery_source="manual", actor="a",
        )
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_project_dependency_remove_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(project_dependency_remove_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependency_remove_command, "resolve_plan", _stub_plan)
    result = asyncio.run(
        project_dependency_remove_command.ProjectDependencyRemoveCommand().execute(
            plan="p", dependency_uuid=BAD_UUID, actor="a"
        )
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_project_dependency_list_rejects_malformed_filter(monkeypatch) -> None:
    monkeypatch.setattr(project_dependency_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependency_list_command, "resolve_plan", _stub_plan)
    result = asyncio.run(
        project_dependency_list_command.ProjectDependencyListCommand().execute(
            plan="p", dependent_project_id=BAD_UUID
        )
    )
    assert _domain_code(result) == "RUNTIME_VALIDATION_ERROR"


def test_map_exception_prompt_assembly_failed() -> None:
    result = map_exception(PromptAssemblyError("no concept row for C-999"))
    assert result.to_dict()["error"]["data"]["domain_code"] == "PROMPT_ASSEMBLY_FAILED"
    assert "PROMPT_ASSEMBLY_FAILED" in DOMAIN_CODES


def test_map_exception_graph_corrupted_chain() -> None:
    result = map_exception(GraphIntegrityError("parent of step A-001 not found in nodes"))
    assert result.to_dict()["error"]["data"]["domain_code"] == "GRAPH_CORRUPTED_CHAIN"
    assert "GRAPH_CORRUPTED_CHAIN" in DOMAIN_CODES


def test_branch_prompt_maps_prompt_assembly_error(monkeypatch) -> None:
    monkeypatch.setattr(branch_prompt_command, "db_connection", _fake_db)
    monkeypatch.setattr(branch_prompt_command, "resolve_plan", _stub_plan)
    monkeypatch.setattr(branch_prompt_command, "resolve_branch", lambda *a, **k: object())

    def _raise(*a, **k):
        raise PromptAssemblyError("no concept row for C-999")

    monkeypatch.setattr(branch_prompt_command, "assemble_prompt", _raise)
    result = asyncio.run(
        branch_prompt_command.BranchPromptCommand().execute(
            plan="p", gs_step_id="G-001", ts_step_id="T-001", as_step_id="A-001"
        )
    )
    assert _domain_code(result) == "PROMPT_ASSEMBLY_FAILED"
