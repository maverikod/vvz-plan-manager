"""Characterization tests for CR-2's DeliveryIntegrityContract (concept
C-007): no downstream credential, internal hostname, or server-side
filesystem path ever appears in a returned artifact or error text, and a
digest mismatch on the inbound promotion path aborts distinctly, before
anything is persisted.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from plan_manager.commands import export_read_command
from plan_manager.commands import export_upload_save_command
from plan_manager.commands.export_read_command import ExportReadCommand
from plan_manager.commands.export_upload_save_command import ExportUploadSaveCommand


@contextmanager
def _fake_db():
    yield object()


def _wire_export_read(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(export_read_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        export_read_command, "resolve_plan",
        lambda conn, plan: SimpleNamespace(uuid=uuid.uuid4(), name="my-plan"),
    )
    monkeypatch.setattr(
        export_read_command, "app_config",
        lambda: SimpleNamespace(export_root=str(tmp_path)),
    )


def _run_export_read(**kwargs):
    return asyncio.run(ExportReadCommand().execute(**kwargs)).to_dict()


def test_export_read_payloads_never_carry_the_server_export_root(monkeypatch, tmp_path: Path) -> None:
    """Success and error payloads carry only the plan name and relative file path."""
    (tmp_path / "my-plan").mkdir()
    (tmp_path / "my-plan" / "f.bin").write_bytes(b"hello")
    _wire_export_read(monkeypatch, tmp_path)

    success_payload = _run_export_read(plan="p", file="f.bin")
    success_text = str(success_payload)
    assert str(tmp_path) not in success_text

    error_payload = _run_export_read(plan="p", file="../secret.txt")
    error_text = str(error_payload)
    assert str(tmp_path) not in error_text
    assert error_payload["error"]["data"]["domain_code"] == "EXPORT_PATH_INVALID"


class _FakeChecksumMismatchStore:
    """Fake transfer store whose completed transfer carries a wrong checksum."""

    def __init__(self, local_path: str, wrong_checksum: str) -> None:
        self._local_path = local_path
        self._wrong_checksum = wrong_checksum

    def get_completed_transfer(self, transfer_id: str) -> dict:
        return {
            "compression": "identity",
            "local_path": self._local_path,
            "checksum_value": self._wrong_checksum,
        }


def test_export_upload_save_aborts_distinctly_on_checksum_mismatch_before_persist(
    monkeypatch, tmp_path: Path
) -> None:
    """A digest mismatch on promotion aborts with a distinct error and leaves no promoted file."""
    export_root = tmp_path / "export_root"
    export_root.mkdir()
    source_file = tmp_path / "staged_upload.bin"
    source_file.write_bytes(b"real content")
    wrong_checksum = hashlib.sha256(b"different content").hexdigest()

    monkeypatch.setattr(
        export_upload_save_command, "get_transfer_store",
        lambda: _FakeChecksumMismatchStore(str(source_file), wrong_checksum),
    )
    monkeypatch.setattr(
        export_upload_save_command, "app_config",
        lambda: SimpleNamespace(export_root=str(export_root)),
    )

    payload = asyncio.run(
        ExportUploadSaveCommand().execute(transfer_id="tr_1", filename="result.bin")
    ).to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["error_type"] == "TransferChecksumMismatchError"
    assert not (export_root / "result.bin").exists()
