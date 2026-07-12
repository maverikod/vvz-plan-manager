"""Pure unit tests for the plan_delete export-layout cleanup helper.

`_remove_export_layout` is a small, filesystem-only helper used by the hard
branch of plan_delete to remove a plan's on-disk export layout directory
after the DB rows are gone. These tests exercise it directly with tmp_path
fixtures; no database is involved.
"""

from pathlib import Path

from plan_manager.commands.plan_delete_command import _remove_export_layout


def test_removes_existing_export_layout(tmp_path: Path) -> None:
    """An existing <export_root>/<plan_name> directory is removed."""
    plan_dir = tmp_path / "my-plan"
    plan_dir.mkdir()
    (plan_dir / "hrs.md").write_text("content", encoding="utf-8")

    result = _remove_export_layout(str(tmp_path), "my-plan")

    assert result is True
    assert not plan_dir.exists()


def test_missing_export_layout_returns_false_without_error(tmp_path: Path) -> None:
    """A plan that was never exported yields False, not an error."""
    result = _remove_export_layout(str(tmp_path), "never-exported")

    assert result is False
    assert not (tmp_path / "never-exported").exists()


def test_traversal_parent_segment_refused(tmp_path: Path) -> None:
    """A name containing '..' is refused; nothing outside root is touched."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    result = _remove_export_layout(str(export_root), "../evil")

    assert result is False
    assert sentinel.exists()


def test_traversal_nested_segment_refused(tmp_path: Path) -> None:
    """A name containing a path separator ('a/b') is refused."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    result = _remove_export_layout(str(export_root), "a/b")

    assert result is False
    assert sentinel.exists()


def test_dotdot_name_refused(tmp_path: Path) -> None:
    """A plan_name of exactly '..' is refused."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    result = _remove_export_layout(str(export_root), "..")

    assert result is False
    assert sentinel.exists()


def test_dot_name_refused(tmp_path: Path) -> None:
    """A plan_name of exactly '.' is refused."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()

    result = _remove_export_layout(str(export_root), ".")

    assert result is False
    assert export_root.exists()


def test_empty_name_refused(tmp_path: Path) -> None:
    """An empty plan_name is refused."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()

    result = _remove_export_layout(str(export_root), "")

    assert result is False
    assert export_root.exists()


def test_nested_layout_fully_removed(tmp_path: Path) -> None:
    """A layout with files and subdirectories is removed via rmtree, not rmdir."""
    plan_dir = tmp_path / "nested-plan"
    plan_dir.mkdir()
    (plan_dir / "hrs.md").write_text("hrs", encoding="utf-8")
    subdir = plan_dir / "mrs"
    subdir.mkdir()
    (subdir / "concepts.yaml").write_text("concepts: []", encoding="utf-8")
    subsubdir = subdir / "nested"
    subsubdir.mkdir()
    (subsubdir / "deep.yaml").write_text("deep", encoding="utf-8")

    result = _remove_export_layout(str(tmp_path), "nested-plan")

    assert result is True
    assert not plan_dir.exists()
