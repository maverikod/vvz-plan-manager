"""Unit tests for the export archive of CR-2 (concept C-016, ExportArchive):
the export tree is packed into one gzip-compressed tar inside the plan's own
export directory, preserving every file's original name and relative position
byte-for-byte; re-archiving replaces the previous archive rather than
accumulating copies; and the archive never contains itself.

The export-root boundary rule the archiver stands on lives in
plan_manager.exchange.export_paths and is exercised here through its canonical
name, since the archiver imports it rather than restating it.
"""
from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from plan_manager.exchange.archiver import (
    ARCHIVE_FILENAME,
    ExportArchiveBoundaryError,
    ExportArchiveTreeMissingError,
    create_export_archive,
)
from plan_manager.exchange.export_paths import resolve_export_subdirectory


def _build_export_tree(export_root: Path) -> dict[str, bytes]:
    """Write a representative export tree and return {relative_path: content}."""
    plan_dir = export_root / "my-plan"
    tree = {
        "source_spec.md": b"{a1b2} Human readable spec.\n",
        "spec.yaml": b"concepts: []\n",
        "G-001-frame/README.yaml": b"step_id: G-001\n",
        "G-001-frame/T-001-decl/README.yaml": b"step_id: T-001\n",
        "G-001-frame/T-001-decl/atomic_steps/A-001-docstring.yaml": b"step_id: A-001\n",
    }
    for relative, content in tree.items():
        target = plan_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return tree


def test_archive_preserves_tree_names_and_relative_positions(tmp_path: Path) -> None:
    """Every file is packed under its exact relative path with identical bytes."""
    tree = _build_export_tree(tmp_path)

    report = create_export_archive(str(tmp_path), "my-plan")

    assert report["archive"] == ARCHIVE_FILENAME
    assert report["file_count"] == len(tree)
    archive_path = tmp_path / "my-plan" / ARCHIVE_FILENAME
    assert archive_path.is_file()
    assert report["size_bytes"] == archive_path.stat().st_size

    with tarfile.open(archive_path, "r:gz") as tar:
        assert sorted(tar.getnames()) == sorted(tree)
        for relative, content in tree.items():
            extracted = tar.extractfile(relative)
            assert extracted is not None
            assert extracted.read() == content


def test_archive_never_contains_itself_and_rearchiving_replaces(tmp_path: Path) -> None:
    """A second run replaces the archive and never packs the previous one."""
    tree = _build_export_tree(tmp_path)

    create_export_archive(str(tmp_path), "my-plan")
    second = create_export_archive(str(tmp_path), "my-plan")

    assert second["file_count"] == len(tree)
    plan_dir = tmp_path / "my-plan"
    archives = [p.name for p in plan_dir.iterdir() if p.name.endswith(".tar.gz")]
    assert archives == [ARCHIVE_FILENAME]
    with tarfile.open(plan_dir / ARCHIVE_FILENAME, "r:gz") as tar:
        assert ARCHIVE_FILENAME not in tar.getnames()


def test_archive_refuses_plan_name_escaping_the_export_root(tmp_path: Path) -> None:
    """A plan name that is not a single safe segment is refused."""
    with pytest.raises(ExportArchiveBoundaryError):
        create_export_archive(str(tmp_path), "../outside")


def test_archive_reports_missing_tree_distinctly(tmp_path: Path) -> None:
    """An absent or empty export directory is a distinct error, not a boundary refusal."""
    with pytest.raises(ExportArchiveTreeMissingError):
        create_export_archive(str(tmp_path), "never-exported")

    (tmp_path / "empty-plan").mkdir()
    with pytest.raises(ExportArchiveTreeMissingError):
        create_export_archive(str(tmp_path), "empty-plan")


def test_shared_resolver_boundary(tmp_path: Path) -> None:
    """The shared resolver accepts a safe segment and refuses every escape."""
    assert resolve_export_subdirectory(str(tmp_path), "my-plan") == (
        tmp_path / "my-plan"
    ).resolve()
    assert resolve_export_subdirectory(str(tmp_path), "a/b") is None
    assert resolve_export_subdirectory(str(tmp_path), "..") is None
    assert resolve_export_subdirectory(str(tmp_path), "") is None


def test_shared_resolver_resolves_a_name_with_no_directory_on_disk(tmp_path: Path) -> None:
    """A safe name resolves even when nothing exists there yet.

    The resolver answers only the boundary question; existence is the caller's
    concern. This is what lets the archiver report a missing export tree as an
    error distinct from a boundary refusal.
    """
    assert resolve_export_subdirectory(str(tmp_path), "never-exported") == (
        tmp_path / "never-exported"
    ).resolve()
