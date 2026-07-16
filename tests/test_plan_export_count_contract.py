"""Characterization tests for CR-2 (concept C-002, ExportReadByteSource): the
export production command reports a COUNT of files written and NO file list,
so nothing on the plan_manager surface enumerates an export.

This is not an incidental detail — it is the entire reason the export archive
(C-016) exists. Because no caller can be handed the names of the files
plan_export just wrote, one archive under one known name is the only way to
obtain a whole export tree without guessing filenames, and one digest then
covers the whole delivery. If plan_export were ever changed to return a file
list, that rationale would dissolve silently; these tests fail instead.

plan_export is NOT modified by CR-2: this pins its existing contract.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from plan_manager.commands.plan_export_command import PlanExportCommand
from plan_manager.exchange import exporter


def _wire_empty_plan(monkeypatch) -> None:
    """Patch the exporter's collaborators so export_plan runs without a database."""
    monkeypatch.setattr(
        exporter,
        "get_plan",
        lambda conn, plan_uuid: SimpleNamespace(
            name="my-plan", project_ids=[], primary_project_id=None
        ),
    )
    monkeypatch.setattr(exporter, "load_steps", lambda conn, plan_uuid: {})
    monkeypatch.setattr(exporter, "list_concepts", lambda conn, plan_uuid: [])
    monkeypatch.setattr(exporter, "list_relations", lambda conn, plan_uuid: [])
    monkeypatch.setattr(exporter, "list_paragraphs", lambda conn, plan_uuid: [])


def test_export_plan_returns_a_file_count_and_no_file_list(monkeypatch, tmp_path: Path) -> None:
    """export_plan reports how many files it wrote, never which files."""
    _wire_empty_plan(monkeypatch)

    summary = exporter.export_plan(None, uuid.uuid4(), str(tmp_path))

    assert set(summary) == {"root", "files"}
    assert isinstance(summary["files"], int)
    assert not isinstance(summary["files"], bool)
    assert summary["files"] == 2


def test_export_plan_count_matches_the_files_actually_written(monkeypatch, tmp_path: Path) -> None:
    """The reported count is a real count of the tree, not a constant."""
    _wire_empty_plan(monkeypatch)

    summary = exporter.export_plan(None, uuid.uuid4(), str(tmp_path))

    written = sorted(p.name for p in (tmp_path / "my-plan").iterdir() if p.is_file())
    assert written == ["source_spec.md", "spec.yaml"]
    assert summary["files"] == len(written)


def test_plan_export_published_contract_documents_a_count(monkeypatch) -> None:
    """The published metadata describes files as a count and never as a list."""
    data = PlanExportCommand.metadata()["return_value"]["success"]["data"]
    assert data["files"] == "Number of files written."

    example = PlanExportCommand.metadata()["return_value"]["success"]["example"]
    assert isinstance(example["files"], int)
    assert not isinstance(example["files"], (list, tuple, dict, set))
