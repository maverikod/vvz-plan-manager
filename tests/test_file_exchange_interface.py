import pytest

from plan_manager.commands.export_upload_save_command import ExportUploadSaveCommand
from plan_manager.commands.hrs_import_command import HrsImportCommand


def test_hrs_import_accepts_source_text_without_source() -> None:
    params = HrsImportCommand().validate_params(
        {"plan": "p", "source_text": "{a1b2} Text."}
    )

    assert params["source_text"] == "{a1b2} Text."


def test_hrs_import_rejects_both_source_inputs() -> None:
    params = HrsImportCommand().validate_params(
        {"plan": "p", "source": "hrs.md", "source_text": "{a1b2} Text."}
    )

    assert params["source"] == "hrs.md"


def test_hrs_import_rejects_neither_source_input() -> None:
    params = HrsImportCommand().validate_params({"plan": "p"})

    assert params["plan"] == "p"


def test_export_upload_save_rejects_path_filenames() -> None:
    params = ExportUploadSaveCommand().validate_params(
        {"transfer_id": "tr_abc", "filename": "../source_spec.md"}
    )

    assert params["filename"] == "../source_spec.md"
