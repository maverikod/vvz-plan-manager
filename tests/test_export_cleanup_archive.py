"""Archive-inclusion guard for the export cleanup file walk (C-008, C-009, C-016).

An export archive is an ordinary export artifact: the cleanup walk must count
its bytes and list it in the manifest exactly like any other file, with no
extension filter and no exemption. These tests fail if anyone ever teaches the
walk to skip or special-case an archive, which would silently under-report a
purge's blast radius.

These are pure filesystem tests: they exercise the walk directly and need no
database connection.
"""

import io
import tarfile
from pathlib import Path

from plan_manager.exchange.export_cleanup import _directory_size_and_manifest


def _write_export_tree(root: Path) -> None:
    """Create a minimal export tree (no archive) under root."""
    (root / "source_spec.md").write_bytes(b"# spec\n")
    (root / "spec.yaml").write_bytes(b"concepts: []\n")
    step_dir = root / "G-001-example"
    step_dir.mkdir()
    (step_dir / "README.yaml").write_bytes(b"name: example\n")


def _write_archive(root: Path, name: str) -> int:
    """Write a real .tar.gz into root and return its size in bytes."""
    archive_path = root / name
    payload = b"archived payload"
    with tarfile.open(archive_path, "w:gz") as tar:
        info = tarfile.TarInfo(name="source_spec.md")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return archive_path.stat().st_size


def test_archive_is_listed_in_the_file_manifest(tmp_path: Path) -> None:
    """The archive appears in the manifest alongside the ordinary export files."""
    _write_export_tree(tmp_path)
    _write_archive(tmp_path, "my-plan.tar.gz")

    _total, manifest = _directory_size_and_manifest(tmp_path)

    listed = {entry["path"] for entry in manifest}
    assert "my-plan.tar.gz" in listed
    assert "source_spec.md" in listed
    assert "spec.yaml" in listed
    assert "G-001-example/README.yaml" in listed


def test_archive_bytes_are_counted_in_the_total(tmp_path: Path) -> None:
    """The reported total is the tree's bytes PLUS the archive's bytes."""
    _write_export_tree(tmp_path)
    tree_only_total, _tree_manifest = _directory_size_and_manifest(tmp_path)

    archive_size = _write_archive(tmp_path, "my-plan.tar.gz")
    total_with_archive, _manifest = _directory_size_and_manifest(tmp_path)

    assert total_with_archive == tree_only_total + archive_size


def test_archive_manifest_entry_reports_its_real_size(tmp_path: Path) -> None:
    """The archive's manifest entry carries its true on-disk size."""
    _write_export_tree(tmp_path)
    archive_size = _write_archive(tmp_path, "my-plan.tar.gz")

    _total, manifest = _directory_size_and_manifest(tmp_path)

    entry = next(e for e in manifest if e["path"] == "my-plan.tar.gz")
    assert entry["size"] == archive_size


def test_a_stale_second_archive_is_also_enumerated(tmp_path: Path) -> None:
    """A stale archive left by an earlier export is enumerated like any other file."""
    _write_export_tree(tmp_path)
    current_size = _write_archive(tmp_path, "my-plan.tar.gz")
    stale_size = _write_archive(tmp_path, "my-plan-2026-07-01.tar.gz")

    total, manifest = _directory_size_and_manifest(tmp_path)

    listed = {entry["path"] for entry in manifest}
    assert "my-plan.tar.gz" in listed
    assert "my-plan-2026-07-01.tar.gz" in listed
    assert total >= current_size + stale_size


def test_walk_of_a_tree_without_an_archive_is_unaffected(tmp_path: Path) -> None:
    """An export tree with no archive enumerates exactly its three files."""
    _write_export_tree(tmp_path)

    _total, manifest = _directory_size_and_manifest(tmp_path)

    assert {entry["path"] for entry in manifest} == {
        "source_spec.md",
        "spec.yaml",
        "G-001-example/README.yaml",
    }
