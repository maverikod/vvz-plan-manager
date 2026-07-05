"""ExportUploadSaveCommand: promote completed uploads into export_root."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, ClassVar

from mcp_proxy_adapter.api.handlers import get_transfer_store
from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.commands.transfer_command_support import (
    transfer_domain_error_result,
)
from mcp_proxy_adapter.transfer.checksums import compute_file_checksum
from mcp_proxy_adapter.transfer.compression import decompress_file
from mcp_proxy_adapter.transfer.errors import (
    TransferChecksumMismatchError,
    TransferError,
)

from plan_manager.commands.export_upload_save_metadata import (
    get_export_upload_save_metadata,
)
from plan_manager.commands.errors import map_exception
from plan_manager.runtime.context import app_config


def _is_safe_filename(filename: str) -> bool:
    return bool(filename) and "/" not in filename and "\\" not in filename and ".." not in filename


class ExportUploadSaveCommand(Command):
    """Promote a completed transfer upload into the configured export root."""

    name: ClassVar[str] = "export_upload_save"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Promote a completed transfer upload session into the configured "
        "export root under a safe bare filename."
    )
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "transfer_id": {
                    "type": "string",
                    "description": "Completed transfer upload session id.",
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Bare filename to write under export_root; no '/', "
                        "'\\', or '..'."
                    ),
                },
            },
            "required": ["transfer_id", "filename"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_export_upload_save_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        transfer_id: str,
        filename: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            if not _is_safe_filename(filename):
                return ErrorResult(
                    message="filename must be a bare file name without path separators",
                    code=-32602,
                    details={
                        "error_type": "InvalidRequest",
                        "field": "filename",
                    },
                )
            try:
                completed = get_transfer_store().get_completed_transfer(transfer_id)
            except TransferError as exc:
                return transfer_domain_error_result(exc)

            export_root = Path(app_config().export_root)
            export_root.mkdir(parents=True, exist_ok=True)
            destination = export_root / filename
            temp_destination = export_root / f".{filename}.tmp.{os.getpid()}"
            try:
                compression = str(completed["compression"])
                source_path = str(completed["local_path"])
                if compression == "identity":
                    shutil.copyfile(source_path, temp_destination)
                elif compression == "gzip":
                    decompress_file(source_path, str(temp_destination), "gzip")
                else:
                    raise TransferError(
                        "Unsupported transfer compression",
                        transfer_id=transfer_id,
                        compression=compression,
                        phase="commit",
                    )
                actual_sha256 = compute_file_checksum(str(temp_destination))
                expected_sha256 = str(completed["checksum_value"])
                if actual_sha256 != expected_sha256:
                    raise TransferChecksumMismatchError(
                        "Staged export checksum mismatch",
                        transfer_id=transfer_id,
                        checksum_expected=expected_sha256,
                        checksum_actual=actual_sha256,
                        phase="commit",
                    )
                os.replace(temp_destination, destination)
            except TransferError as exc:
                if temp_destination.exists():
                    temp_destination.unlink()
                return transfer_domain_error_result(exc)
            except Exception:
                if temp_destination.exists():
                    temp_destination.unlink()
                raise

            return SuccessResult(
                data={
                    "filename": filename,
                    "size_bytes": destination.stat().st_size,
                    "sha256": compute_file_checksum(str(destination)),
                }
            )
        except Exception as exc:
            return map_exception(exc)
