"""Tests for export_cleanup command end to end at the command level."""
from __future__ import annotations

import asyncio
import uuid as uuid_module
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import plan_manager.commands.export_cleanup_command as export_cleanup_command
import plan_manager.exchange.export_cleanup as export_cleanup
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from plan_manager.commands.export_cleanup_command import ExportCleanupCommand
from plan_manager.domain.plan import Plan
from plan_manager.exchange.export_cleanup import (
    BOUNDARY_REFUSED,
    LIVE,
    ORPHANED_UNRESOLVABLE,
    SOFT_DELETED_ORPHANED_ELIGIBLE,
)


# --- Fixtures and helpers ------------------------------------------------


@contextmanager
def _fake_db():
    yield object()


def _make_plan(name, *, deleted=False):
    return Plan(
        uuid=uuid_module.uuid4(),
        name=name,
        status="draft",
        context_budget=4000,
        head_revision_uuid=None,
        project_ids=[],
        primary_project_id=None,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )


def _noop_audit(conn, entry, dry_run, removal_outcome, changed_by):
    return {"uuid": str(uuid_module.uuid4()), "dry_run": dry_run}


def _wire(monkeypatch, tmp_path: Path, plans, audit_stub=None):
    monkeypatch.setattr(export_cleanup_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        export_cleanup_command, "app_config", lambda: SimpleNamespace(export_root=str(tmp_path))
    )
    monkeypatch.setattr(export_cleanup, "list_plans", lambda conn, show_deleted=True: plans)
    monkeypatch.setattr(
        export_cleanup_command, "record_export_cleanup_audit", audit_stub or _noop_audit
    )


def _run(**kwargs):
    return asyncio.run(ExportCleanupCommand().execute(**kwargs))


# --- Tests ---------------------------------------------------------------


def test_dry_run_is_the_default_and_removes_nothing(monkeypatch, tmp_path: Path) -> None:
    """Test that dry_run=True is the default and no files are removed."""
    # Create dead-plan directory with files
    dead_plan_dir = tmp_path / "dead-plan"
    dead_plan_dir.mkdir()
    (dead_plan_dir / "file1.txt").write_text("content1")
    (dead_plan_dir / "subdir").mkdir()
    (dead_plan_dir / "subdir" / "file2.txt").write_text("content2")
    (dead_plan_dir / "export.tar.gz").write_text("fake archive")

    # Setup fakes
    plans = [_make_plan("dead-plan", deleted=True)]
    _wire(monkeypatch, tmp_path, plans)

    # Calculate expected byte count
    expected_bytes = (
        len("content1") + len("content2") + len("fake archive")
    )

    # Execute with plan filter and changed_by only (dry_run defaults to True)
    result = _run(plan="dead-plan", changed_by="agent-1")

    assert isinstance(result, SuccessResult)
    data = result.data
    assert data["dry_run"] is True
    assert len(data["classified_directories"]) == 1

    entry = data["classified_directories"][0]
    assert entry["classification"] == SOFT_DELETED_ORPHANED_ELIGIBLE
    assert entry["eligible_for_removal"] is True
    assert entry["byte_count"] == expected_bytes
    assert len(entry["file_manifest"]) == 3

    # Verify file paths in manifest
    manifest_paths = {f["path"] for f in entry["file_manifest"]}
    assert "file1.txt" in manifest_paths
    assert "subdir/file2.txt" in manifest_paths
    assert "export.tar.gz" in manifest_paths

    # Check preview totals
    assert data["preview_totals"]["eligible_directory_count"] == 1
    assert data["preview_totals"]["eligible_file_count"] == 3
    assert data["preview_totals"]["eligible_byte_count"] == expected_bytes

    # Verify files still exist
    assert (dead_plan_dir / "file1.txt").exists()
    assert (dead_plan_dir / "subdir" / "file2.txt").exists()
    assert (dead_plan_dir / "export.tar.gz").exists()


def test_real_run_removes_eligible_directories(monkeypatch, tmp_path: Path) -> None:
    """Test that dry_run=False removes eligible directories."""
    # Create dead-plan directory with files
    dead_plan_dir = tmp_path / "dead-plan"
    dead_plan_dir.mkdir()
    (dead_plan_dir / "file1.txt").write_text("content1")
    (dead_plan_dir / "subdir").mkdir()
    (dead_plan_dir / "subdir" / "file2.txt").write_text("content2")

    # Setup fakes
    plans = [_make_plan("dead-plan", deleted=True)]
    _wire(monkeypatch, tmp_path, plans)

    # Calculate expected byte count
    expected_bytes = len("content1") + len("content2")

    # Execute with plan filter, changed_by, and dry_run=False
    result = _run(plan="dead-plan", changed_by="agent-1", dry_run=False)

    assert isinstance(result, SuccessResult)
    data = result.data
    assert data["dry_run"] is False
    assert len(data["removal_outcomes"]) == 1

    outcome = data["removal_outcomes"][0]
    assert outcome["directory_name"] == "dead-plan"
    assert outcome["removed"] is True
    assert outcome["bytes_freed"] == expected_bytes
    assert outcome["files_removed"] == 2
    assert outcome["failure_reason"] is None or outcome["failure_reason"] is False

    # Check removal totals
    assert data["removal_totals"]["directories_removed"] == 1
    assert data["removal_totals"]["files_removed"] == 2
    assert data["removal_totals"]["total_bytes_freed"] == expected_bytes

    # Verify directory no longer exists
    assert not dead_plan_dir.exists()


def test_live_plan_directory_is_never_eligible(monkeypatch, tmp_path: Path) -> None:
    """Test that LIVE plan directories are never eligible for removal."""
    # Create live-plan directory with file
    live_plan_dir = tmp_path / "live-plan"
    live_plan_dir.mkdir()
    (live_plan_dir / "file.txt").write_text("content")

    # Setup fakes
    plans = [_make_plan("live-plan")]  # Not deleted = LIVE
    _wire(monkeypatch, tmp_path, plans)

    # First, do a dry run to verify classification is LIVE
    dry_result = _run(plan="live-plan", changed_by="agent-1", dry_run=True)
    assert isinstance(dry_result, SuccessResult)
    dry_data = dry_result.data
    assert len(dry_data["classified_directories"]) == 1
    assert dry_data["classified_directories"][0]["classification"] == LIVE

    # Execute real run (dry_run=False) to prove protection works
    result = _run(plan="live-plan", changed_by="agent-1", dry_run=False)

    assert isinstance(result, SuccessResult)
    data = result.data
    # LIVE directories are not eligible, so removal_outcomes will be empty
    assert len(data["removal_outcomes"]) == 0

    # Check removal totals - nothing was removed
    assert data["removal_totals"]["directories_removed"] == 0

    # Verify directory and file still exist
    assert live_plan_dir.exists()
    assert (live_plan_dir / "file.txt").exists()


def test_orphan_requires_the_explicit_flag(monkeypatch, tmp_path: Path) -> None:
    """Test that orphan directories require include_orphaned=True to be eligible."""
    # Create orphan directory with file
    orphan_dir = tmp_path / "orphan-dir"
    orphan_dir.mkdir()
    (orphan_dir / "file.txt").write_text("content")

    # Setup fakes (no matching plan for orphan-dir)
    plans = []
    _wire(monkeypatch, tmp_path, plans)

    # First invocation: no plan filter (sweep), include_orphaned defaults to False
    result1 = _run(changed_by="agent-1")

    assert isinstance(result1, SuccessResult)
    data1 = result1.data
    assert data1["dry_run"] is True
    orphan_entry1 = next(
        (e for e in data1["classified_directories"] if e["directory_name"] == "orphan-dir"), None
    )
    assert orphan_entry1 is not None
    assert orphan_entry1["classification"] == ORPHANED_UNRESOLVABLE
    assert orphan_entry1["eligible_for_removal"] is False
    assert data1["preview_totals"]["eligible_directory_count"] == 0

    # Second invocation: same sweep but include_orphaned=True
    result2 = _run(changed_by="agent-1", include_orphaned=True)

    assert isinstance(result2, SuccessResult)
    data2 = result2.data
    assert data2["dry_run"] is True
    orphan_entry2 = next(
        (e for e in data2["classified_directories"] if e["directory_name"] == "orphan-dir"), None
    )
    assert orphan_entry2 is not None
    assert orphan_entry2["classification"] == ORPHANED_UNRESOLVABLE
    assert orphan_entry2["eligible_for_removal"] is True
    assert data2["preview_totals"]["eligible_directory_count"] == 1

    # Both are dry runs; verify directory still exists after both
    assert orphan_dir.exists()


def test_boundary_refusal_for_a_plan_filter(monkeypatch, tmp_path: Path) -> None:
    """Test that traversal-shaped plan values are rejected."""
    # Create sentinel file outside export root
    sentinel = tmp_path.parent / "sentinel.txt"
    sentinel.write_text("original content")

    # Setup fakes (empty plan catalog is fine for this path)
    plans = []
    _wire(monkeypatch, tmp_path, plans)

    # Execute with traversal-shaped plan value
    result = _run(plan="../outside", changed_by="agent-1")

    assert isinstance(result, ErrorResult)
    assert result.details["domain_code"] == "EXPORT_PATH_INVALID"

    # Verify sentinel file was not touched
    assert sentinel.exists()
    assert sentinel.read_text() == "original content"


def test_every_invocation_is_audited(monkeypatch, tmp_path: Path) -> None:
    """Test that every invocation is audited with correct parameters."""
    # Create dead-plan directory with file
    dead_plan_dir = tmp_path / "dead-plan"
    dead_plan_dir.mkdir()
    (dead_plan_dir / "file.txt").write_text("content")

    # Setup fakes
    plans = [_make_plan("dead-plan", deleted=True)]

    # Create recording audit stub
    audit_calls = []

    def recording_audit(conn, entry, dry_run, removal_outcome, changed_by):
        audit_calls.append(
            {
                "entry": entry,
                "dry_run": dry_run,
                "removal_outcome": removal_outcome,
                "changed_by": changed_by,
            }
        )
        return {"uuid": str(uuid_module.uuid4()), "dry_run": dry_run}

    _wire(monkeypatch, tmp_path, plans, audit_stub=recording_audit)

    # First invocation: dry run
    result1 = _run(plan="dead-plan", changed_by="agent-1")
    assert isinstance(result1, SuccessResult)
    assert result1.data["dry_run"] is True

    # Second invocation: real run
    result2 = _run(plan="dead-plan", changed_by="agent-1", dry_run=False)
    assert isinstance(result2, SuccessResult)
    assert result2.data["dry_run"] is False

    # Verify audit was called on both invocations
    assert len(audit_calls) == 2

    # Verify dry-run call
    dry_run_call = audit_calls[0]
    assert dry_run_call["dry_run"] is True
    assert dry_run_call["changed_by"] == "agent-1"
    assert dry_run_call["entry"]["directory_name"] == "dead-plan"
    assert dry_run_call["removal_outcome"] is None

    # Verify real-run call
    real_run_call = audit_calls[1]
    assert real_run_call["dry_run"] is False
    assert real_run_call["changed_by"] == "agent-1"
    assert real_run_call["entry"]["directory_name"] == "dead-plan"
    assert real_run_call["removal_outcome"] is not None
    assert real_run_call["removal_outcome"]["removed"] is True


def test_plan_filter_matching_nothing_is_not_an_error(monkeypatch, tmp_path: Path) -> None:
    """Test that filtering for a never-exported plan returns empty results."""
    # Setup fakes (no directory exists)
    plans = []
    _wire(monkeypatch, tmp_path, plans)

    # Execute with plan filter for non-existent plan
    result = _run(plan="never-exported", changed_by="agent-1")

    assert isinstance(result, SuccessResult)
    data = result.data
    assert data["classified_directories"] == []
    assert data["preview_totals"]["eligible_directory_count"] == 0
    assert data["preview_totals"]["eligible_file_count"] == 0
    assert data["preview_totals"]["eligible_byte_count"] == 0
