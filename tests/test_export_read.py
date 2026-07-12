"""Tests for bug f58e7302: export_read serves export-file bytes in bounded, integrity-checked
base64 chunks strictly under <export_root>/<plan>/."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from plan_manager.commands import export_read_command
from plan_manager.commands.export_read_command import (
    ExportReadCommand,
    _resolve_export_file,
)


# --- pure path-safety helper ------------------------------------------------

def test_resolve_export_file_inside_plan_dir(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "my-plan" / "hrs.md").write_text("x", encoding="utf-8")
    resolved = _resolve_export_file(str(tmp_path), "my-plan", "hrs.md")
    assert resolved == (tmp_path / "my-plan" / "hrs.md").resolve()


def test_resolve_export_file_allows_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "my-plan" / "mrs").mkdir(parents=True)
    resolved = _resolve_export_file(str(tmp_path), "my-plan", "mrs/concepts.yaml")
    assert resolved == (tmp_path / "my-plan" / "mrs" / "concepts.yaml").resolve()


def test_resolve_export_file_refuses_traversal(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    assert _resolve_export_file(str(tmp_path), "my-plan", "../secret.txt") is None


def test_resolve_export_file_refuses_symlink_escape(tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    link = tmp_path / "my-plan" / "link.txt"
    link.symlink_to(outside)
    assert _resolve_export_file(str(tmp_path), "my-plan", "link.txt") is None


def test_resolve_export_file_refuses_bad_plan_segment(tmp_path: Path) -> None:
    assert _resolve_export_file(str(tmp_path), "a/b", "f.txt") is None
    assert _resolve_export_file(str(tmp_path), "..", "f.txt") is None


# --- command surface --------------------------------------------------------

@contextmanager
def _fake_db():
    yield object()


def _wire(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(export_read_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        export_read_command, "resolve_plan",
        lambda conn, plan: SimpleNamespace(uuid=uuid.uuid4(), name="my-plan"),
    )
    monkeypatch.setattr(
        export_read_command, "app_config",
        lambda: SimpleNamespace(export_root=str(tmp_path)),
    )


def _run(**kwargs):
    return asyncio.run(ExportReadCommand().execute(**kwargs)).to_dict()


def test_chunked_read_reassembles_byte_identical(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    content = bytes(range(256)) * 2000  # 512000 bytes -> multiple chunks
    (tmp_path / "my-plan" / "export.bin").write_bytes(content)
    _wire(monkeypatch, tmp_path)
    expected_sha = hashlib.sha256(content).hexdigest()

    assembled = bytearray()
    offset = 0
    while True:
        payload = _run(plan="p", file="export.bin", offset=offset, limit=262144)
        data = payload["data"]
        assert data["sha256"] == expected_sha
        assert data["total_size"] == len(content)
        assembled.extend(base64.b64decode(data["chunk_base64"]))
        offset += data["chunk_size"]
        if data["eof"]:
            break

    assert bytes(assembled) == content


def test_traversal_is_refused(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")
    _wire(monkeypatch, tmp_path)
    payload = _run(plan="p", file="../secret.txt")
    assert payload["error"]["data"]["domain_code"] == "EXPORT_PATH_INVALID"


def test_out_of_range_offset_is_invalid_pagination(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "my-plan" / "f.bin").write_bytes(b"abc")
    _wire(monkeypatch, tmp_path)
    payload = _run(plan="p", file="f.bin", offset=99)
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_missing_file_is_export_file_not_found(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    _wire(monkeypatch, tmp_path)
    payload = _run(plan="p", file="nope.bin")
    assert payload["error"]["data"]["domain_code"] == "EXPORT_FILE_NOT_FOUND"


def test_limit_over_cap_is_invalid_pagination(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "my-plan" / "f.bin").write_bytes(b"abc")
    _wire(monkeypatch, tmp_path)
    payload = _run(plan="p", file="f.bin", limit=262145)
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"
