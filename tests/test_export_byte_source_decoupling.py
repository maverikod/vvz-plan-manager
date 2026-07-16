"""Characterization tests for bug f58e7302 / CR-2 (concept C-002,
ExportReadByteSource): export_read is the ONLY byte source on the
plan_manager command surface, and the export byte path stays decoupled
from the adapter's generic chunk-transfer builtins (transfer_download_begin
/ transfer_download_status), so a future change cannot silently rewire
byte serving onto that unrelated session-based mechanism.
"""
from __future__ import annotations

import inspect

from plan_manager.commands import export_read_command
from plan_manager.commands import plan_export_command


def test_export_read_module_does_not_import_transfer_store() -> None:
    """export_read_command must not import the adapter's transfer session store."""
    source = inspect.getsource(export_read_command)
    assert "get_transfer_store" not in source
    assert "transfer_download_begin" not in source
    assert "transfer_download_status" not in source


def test_plan_export_module_does_not_import_transfer_store() -> None:
    """plan_export_command must not import the adapter's transfer session store."""
    source = inspect.getsource(plan_export_command)
    assert "get_transfer_store" not in source
    assert "transfer_download_begin" not in source
    assert "transfer_download_status" not in source


def test_export_read_command_name_is_the_declared_byte_source() -> None:
    """The command surface exposes export_read as the byte-serving command name."""
    assert export_read_command.ExportReadCommand.name == "export_read"
