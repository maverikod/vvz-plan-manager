"""Metadata for the export_upload_save command."""

from __future__ import annotations


def get_export_upload_save_metadata(cls) -> dict:
    """Return extended AI/documentation metadata for ExportUploadSaveCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Promotes a completed mcp_proxy_adapter transfer upload session "
            "into the plan-manager export root under a caller-supplied bare "
            "filename. This command is the bridge between the built-in "
            "transfer_upload_begin/status/complete API and import commands "
            "such as hrs_import and plan_import, which intentionally accept "
            "only names under export_root. The filename is never a path: '/', "
            "'\\', empty strings, and '..' are rejected before any file is "
            "written. The transfer session must be an upload session in the "
            "completed uploaded state; active, failed, expired, missing, "
            "download, or consumed sessions are refused. For identity uploads "
            "the staged bytes are copied as-is; for gzip uploads the payload is "
            "decompressed before writing to export_root. The staged file's "
            "sha256 is computed after writing and must match the transfer "
            "session checksum, preserving byte-for-byte integrity through the "
            "existing transfer checksum mechanism."
        ),
        "parameters": {
            "transfer_id": {
                "description": "Identifier returned by transfer_upload_begin and completed by transfer_upload_complete.",
                "type": "string",
                "required": True,
            },
            "filename": {
                "description": "Bare filename to write under export_root; must not contain '/', '\\', or '..'.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The export-root filename and checksum of the staged file.",
                "data": {
                    "filename": "Bare filename written under export_root.",
                    "size_bytes": "Size of the staged export-root file in bytes.",
                    "sha256": "SHA-256 checksum of the staged export-root file.",
                },
                "example": {
                    "filename": "source_spec.md",
                    "size_bytes": 17408,
                    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                },
            },
            "error": {
                "description": "Parameter or transfer-domain error.",
                "code": "-32602 for invalid filename parameters; -32000 for transfer-domain errors.",
                "message": "Human-readable explanation.",
                "details": "Transfer errors include error_type and transfer_id details when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Save a completed upload as an HRS Markdown file for hrs_import.",
                "command": {
                    "transfer_id": "tr_00000000000000000000000000000000",
                    "filename": "source_spec.md",
                },
                "explanation": "After success, call hrs_import with source='source_spec.md'.",
            }
        ],
        "error_cases": {
            "InvalidRequest": {
                "description": "The requested filename is not a bare export-root name.",
                "message": "filename must be a bare file name without path separators",
                "solution": "Pass only a file name such as source_spec.md, never a path.",
            },
            "TransferSessionNotFoundError": {
                "description": "The transfer_id does not name a usable upload session.",
                "message": "Transfer session not found",
                "solution": "Call transfer_upload_status with the transfer_id and retry before the session expires.",
            },
            "TransferError": {
                "description": "The upload session is not complete or cannot be promoted.",
                "message": "Upload not complete",
                "solution": "Finish transfer_upload_complete successfully before calling export_upload_save.",
            },
            "TransferChecksumMismatchError": {
                "description": "The staged export file checksum does not match the transfer checksum.",
                "message": "Staged export checksum mismatch",
                "solution": "Start a new upload; the command removes the partial staged file before returning this error.",
            },
        },
        "best_practices": [
            "Use source_text on hrs_import for small Markdown documents; use export_upload_save for larger files and archives.",
            "Call transfer_upload_complete before export_upload_save; this command never accepts active partial uploads.",
            "After export_upload_save succeeds, pass the returned filename to hrs_import or plan_import rather than a filesystem path.",
        ],
    }
