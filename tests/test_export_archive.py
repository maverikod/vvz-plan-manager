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

import os
import tarfile
from pathlib import Path

import pytest

from plan_manager.exchange.archiver import (
    ARCHIVE_FILENAME,
    ExportArchiveBoundaryError,
    ExportArchiveTreeMissingError,
    create_export_archive,
)
from plan_manager.exchange.export_paths import (
    resolve_export_subdirectory,
    resolve_export_subfile,
)


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


def test_shared_resolver_refuses_altsep_when_defined(monkeypatch, tmp_path: Path) -> None:
    """A name containing os.altsep is refused whenever the platform defines one.

    POSIX leaves os.altsep unset, so this exercises the branch by simulating a
    platform that defines it (e.g. Windows, where altsep is '/').
    """
    monkeypatch.setattr(os, "altsep", "@", raising=False)
    assert resolve_export_subdirectory(str(tmp_path), "weird@name") is None


# --- resolve_export_subfile (todo 1ae3af41: consolidated from export_read_command's
# former _resolve_export_file, which now delegates here) -----------------------------


def test_subfile_resolver_resolves_inside_plan_dir(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "my-plan" / "hrs.md").write_text("x", encoding="utf-8")
    resolved = resolve_export_subfile(str(tmp_path), "my-plan", "hrs.md")
    assert resolved == (tmp_path / "my-plan" / "hrs.md").resolve()


def test_subfile_resolver_allows_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "my-plan" / "mrs").mkdir(parents=True)
    resolved = resolve_export_subfile(str(tmp_path), "my-plan", "mrs/concepts.yaml")
    assert resolved == (tmp_path / "my-plan" / "mrs" / "concepts.yaml").resolve()


def test_subfile_resolver_refuses_traversal(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    assert resolve_export_subfile(str(tmp_path), "my-plan", "../secret.txt") is None


def test_subfile_resolver_refuses_symlink_escape(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    link = tmp_path / "my-plan" / "link.txt"
    link.symlink_to(outside)
    assert resolve_export_subfile(str(tmp_path), "my-plan", "link.txt") is None


def test_subfile_resolver_refuses_bad_plan_segment(tmp_path: Path) -> None:
    assert resolve_export_subfile(str(tmp_path), "a/b", "f.txt") is None
    assert resolve_export_subfile(str(tmp_path), "..", "f.txt") is None


def test_subfile_resolver_refuses_empty_or_non_string_file(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    assert resolve_export_subfile(str(tmp_path), "my-plan", "") is None


# --- resolve_export_subdirectory reused as the single-segment filename check
# (todo 1ae3af41: consolidated from export_upload_save_command's former
# string-only _is_safe_filename) ------------------------------------------------------


def test_single_segment_variant_accepts_a_plain_filename(tmp_path: Path) -> None:
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    assert resolve_export_subdirectory(str(export_root), "result.bin") == (
        export_root / "result.bin"
    ).resolve()


def test_single_segment_variant_rejects_traversal_filenames(tmp_path: Path) -> None:
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    assert resolve_export_subdirectory(str(export_root), "..") is None
    assert resolve_export_subdirectory(str(export_root), "../evil.bin") is None
    assert resolve_export_subdirectory(str(export_root), "sub/evil.bin") is None


def test_single_segment_variant_rejects_dot_filename(tmp_path: Path) -> None:
    """Security tightening (todo 1ae3af41): the old string-only _is_safe_filename
    admitted '.' as a "safe" bare filename (no '/', no '\\', no '..' substring); the
    shared resolver rejects it outright, since '.' is not a real path segment."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    assert resolve_export_subdirectory(str(export_root), ".") is None


def test_single_segment_variant_rejects_symlink_escape_for_a_filename(tmp_path: Path) -> None:
    """Security tightening (todo 1ae3af41): a filename that is itself a pre-existing
    symlink escaping export_root was admitted by the old string-only check (it never
    touched the filesystem) and is now rejected, since the shared resolver follows
    symlinks before comparing against the resolved export_root."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    evil = export_root / "evil.bin"
    evil.symlink_to(outside)
    assert resolve_export_subdirectory(str(export_root), "evil.bin") is None


def test_single_segment_variant_refuses_altsep_when_defined(monkeypatch, tmp_path: Path) -> None:
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    monkeypatch.setattr(os, "altsep", "@", raising=False)
    assert resolve_export_subdirectory(str(export_root), "weird@name.bin") is None
