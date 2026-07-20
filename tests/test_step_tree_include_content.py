from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

from plan_manager.commands.step_tree_command import StepTreeCommand
from plan_manager.domain.step import Step


def make_step() -> Step:
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=None,
        level=3,
        step_id="G-001",
        slug="global",
        fields={"name": "Global", "description": "D"},
        depends_on=["G-000"],
        concepts=["C-001"],
        project_id=None,
        status="draft",
    )


PLAN_UUID = uuid.uuid4()


@contextmanager
def fake_db():
    yield object()


def prepare(monkeypatch):
    step = make_step()
    monkeypatch.setattr("plan_manager.commands.step_tree_command.db_connection", fake_db)
    monkeypatch.setattr("plan_manager.commands.step_tree_command.resolve_plan", lambda conn, plan: SimpleNamespace(uuid=PLAN_UUID))
    monkeypatch.setattr("plan_manager.commands.step_tree_command.load_steps", lambda conn, plan_uuid: {step.uuid: step})
    monkeypatch.setattr("plan_manager.commands.step_tree_command.canonical_step_path", lambda nodes, value: "G-001-global")
    monkeypatch.setattr("plan_manager.commands.step_tree_command.parent_canonical_path", lambda nodes, value: None)
    monkeypatch.setattr("plan_manager.commands.step_tree_command.parent_uuid", lambda nodes, value: None)
    monkeypatch.setattr("plan_manager.commands.step_tree_command.artifact_path_of", lambda nodes, value: "G-001-global/README.yaml")
    monkeypatch.setattr("plan_manager.commands.step_tree_command.get_runtime_record", lambda conn, plan_uuid, step_uuid: {"state": "ready"})


def run(**kwargs):
    return asyncio.run(StepTreeCommand().execute(plan="p", **kwargs)).data["tree"][0]


def test_include_content_defaults_false(monkeypatch) -> None:
    prepare(monkeypatch)
    entry = run()
    assert "fields" not in entry
    assert "depends_on" not in entry
    assert "concepts" not in entry
    assert "runtime" not in entry


def test_include_content_true_returns_normative_content(monkeypatch) -> None:
    prepare(monkeypatch)
    entry = run(include_content=True)
    assert entry["fields"]["name"] == "Global"
    assert entry["depends_on"] == ["G-000"]
    assert entry["concepts"] == ["C-001"]
    assert "runtime" not in entry


def test_include_content_combines_with_runtime(monkeypatch) -> None:
    prepare(monkeypatch)
    entry = run(include_content=True, include_runtime=True)
    assert entry["fields"]["name"] == "Global"
    assert entry["runtime"] == {"state": "ready"}


def test_schema_documents_false_default() -> None:
    prop = StepTreeCommand.get_schema()["properties"]["include_content"]
    assert prop["default"] is False
