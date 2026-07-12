"""Metadata for the export_read command (bug f58e7302)."""

from __future__ import annotations


def get_export_read_metadata(cls) -> dict:
    """Return extended AI/documentation metadata for ExportReadCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Read-only retrieval of the bytes plan_manager itself wrote under the configured export "
            "root. Because plan_manager owns those files (plan_export, branch_dump, export_upload_save, "
            "hrs_export), it serves their bytes back directly rather than coupling the caller to a "
            "private adapter transfer session. A file is addressed strictly under "
            "<export_root>/<plan>/<file>: the plan is resolved against the catalog to its canonical "
            "name, and the file is a plan-relative path that may contain subdirectories but must "
            "resolve (symlinks followed) strictly inside that plan's export directory. Any path that "
            "escapes the plan directory is refused with EXPORT_PATH_INVALID; a well-formed path with no "
            "file present is EXPORT_FILE_NOT_FOUND. The response carries a single base64 chunk of at "
            "most `limit` decoded bytes (hard cap 262144) starting at `offset`, plus the WHOLE file's "
            "total_size and sha256 and an eof flag. A caller reads sequentially by advancing offset by "
            "chunk_size until eof is true, concatenates the decoded chunks, and verifies the "
            "reassembled bytes against sha256 — no polling and no job queue are involved. The response "
            "contains only the plan name, the requested relative file path, offsets, the chunk, and "
            "integrity metadata; it never includes hostnames, filesystem roots, or credentials."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) whose export directory owns the file.",
                "type": "string",
                "required": True,
            },
            "file": {
                "description": (
                    "Plan-relative path of the file to read under <export_root>/<plan>/. May contain "
                    "subdirectories but must resolve strictly inside the plan export directory."
                ),
                "type": "string",
                "required": True,
            },
            "offset": {
                "description": "Zero-based byte offset to start reading from; must be in [0, total_size].",
                "type": "integer",
                "required": False,
                "default": 0,
            },
            "limit": {
                "description": "Maximum number of decoded bytes to return in this chunk; must be in [1, 262144].",
                "type": "integer",
                "required": False,
                "default": 262144,
            },
        },
        "return_value": {
            "success": {
                "description": "One bounded base64 chunk plus whole-file integrity metadata.",
                "data": {
                    "plan": "Resolved plan catalog name.",
                    "file": "The requested plan-relative file path (echoed).",
                    "offset": "Byte offset this chunk starts at.",
                    "limit": "The decoded-byte cap requested for this chunk.",
                    "chunk_base64": "Base64 of the bytes read for this chunk (decode to raw bytes).",
                    "chunk_size": "Number of decoded bytes actually returned (0 at EOF when offset == total_size).",
                    "total_size": "Total size of the whole file in bytes.",
                    "sha256": "SHA-256 hex digest of the WHOLE file, for byte-identity verification.",
                    "eof": "True when this chunk reaches the end of the file (offset + chunk_size >= total_size).",
                },
                "example": {
                    "plan": "my-plan",
                    "file": "source_spec.md",
                    "offset": 0,
                    "limit": 262144,
                    "chunk_base64": "SGVsbG8=",
                    "chunk_size": 5,
                    "total_size": 5,
                    "sha256": "185f8db32271fe25f561a6fc938b2e264306ec304eda518007d1764826381969",
                    "eof": True,
                },
            },
            "error": {
                "description": "Plan-resolution, path, or pagination error.",
                "code": "PLAN_NOT_FOUND | EXPORT_PATH_INVALID | EXPORT_FILE_NOT_FOUND | INVALID_PAGINATION",
                "message": "Human-readable explanation.",
                "details": "Programmatic diagnostic fields such as file, offset, total_size, or max_chunk_bytes.",
            },
        },
        "usage_examples": [
            {
                "description": "Read a small export file in a single chunk.",
                "command": {"plan": "my-plan", "file": "source_spec.md", "offset": 0, "limit": 262144},
                "explanation": "eof=true in one call; decode chunk_base64 and verify against sha256.",
            },
            {
                "description": "Poll-free sequential read of a large file.",
                "command": {"plan": "my-plan", "file": "export.tar", "offset": 262144, "limit": 262144},
                "explanation": (
                    "Start at offset 0; after each response advance offset by chunk_size and call again "
                    "until eof=true, concatenating the decoded chunks; then verify the reassembly against sha256."
                ),
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a stored plan.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan identifier.",
            },
            "EXPORT_PATH_INVALID": {
                "description": "The file path is empty or resolves outside the plan's export directory (traversal or symlink escape).",
                "message": "file does not resolve to a path inside the plan export directory",
                "solution": "Pass a plan-relative path (no leading '/', no '..' escaping the plan dir).",
            },
            "EXPORT_FILE_NOT_FOUND": {
                "description": "The path is valid but no file exists there under the export root.",
                "message": "no export file at the requested path",
                "solution": "Run the exporting command (e.g. plan_export/branch_dump) first, or correct the file name.",
            },
            "INVALID_PAGINATION": {
                "description": "offset is negative or past end of file, or limit is outside [1, 262144].",
                "message": "offset/limit out of range",
                "solution": "Use offset in [0, total_size] and limit in [1, 262144]; read total_size from a prior chunk.",
            },
        },
        "best_practices": [
            "Read sequentially: start at offset 0, then advance offset by the returned chunk_size until eof is true — no queue polling is involved.",
            "After reassembling all chunks, hash the concatenated bytes and compare against the returned sha256 to confirm byte-identity.",
            "Keep limit <= 262144 (the decoded-byte cap); larger values are refused with INVALID_PAGINATION.",
            "export_read is read-only and never leaves the plan's export directory; it is the retrieval counterpart to export_upload_save.",
        ],
    }
