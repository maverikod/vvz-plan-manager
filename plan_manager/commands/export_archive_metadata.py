"""Metadata for the export_archive command (C-016)."""

from __future__ import annotations


def get_export_archive_metadata(cls) -> dict:
    """Return extended AI/documentation metadata for ExportArchiveCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Packs a plan's already-produced export tree into ONE gzip-compressed tar "
            "archive written inside that plan's own export directory, and reports the "
            "archive's plan-relative name, byte size and sha256. This exists because "
            "nothing on the surface enumerates an export: plan_export reports a COUNT of "
            "files written, not their names, so one archive under one known name is the "
            "only way a caller obtains a whole export tree without guessing filenames, "
            "and one digest then covers the entire delivery. The archive is written as "
            "<plan>/export.tar.gz, which means the already-shipped export_read command "
            "serves its bytes back with no new transfer machinery: call export_archive, "
            "then read the returned name through export_read in bounded base64 chunks and "
            "verify the reassembly against the sha256 returned here. Entries are stored "
            "under paths relative to the plan's export directory, so unpacking reproduces "
            "source_spec.md, spec.yaml and every G-NNN-<slug>/, T-NNN-<slug>/ and "
            "atomic_steps/ file byte-for-byte under its original name and relative "
            "position. Symlinks are never packed. Re-archiving the same export REPLACES "
            "the previous archive rather than accumulating copies (the archive is built "
            "as a temporary file in the same directory and atomically moved onto the "
            "final name), and the archive never contains itself. The archive is an "
            "ordinary export artifact: it lives under the export root, never escapes it, "
            "and is subject to the same lifecycle and cleanup rules as the rest of the "
            "export. plan_export is NOT modified by this command and keeps its contract "
            "byte-for-byte. The response carries only the plan name, the archive's "
            "relative name and its integrity metadata; it never includes server-side "
            "filesystem roots, hostnames, or credentials."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or catalog name) whose produced export tree is archived.",
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "The written archive's plan-relative name and integrity metadata.",
                "data": {
                    "plan": "Resolved plan catalog name.",
                    "archive": "The archive's plan-relative name; always 'export.tar.gz'. Pass this to export_read as its file argument.",
                    "size_bytes": "Size of the written archive in bytes.",
                    "sha256": "SHA-256 hex digest of the WHOLE archive, for byte-identity verification after retrieval.",
                    "file_count": "Number of export-tree files packed into the archive (the archive itself is never packed).",
                },
                "example": {
                    "plan": "my-plan",
                    "archive": "export.tar.gz",
                    "size_bytes": 20480,
                    "sha256": "185f8db32271fe25f561a6fc938b2e264306ec304eda518007d1764826381969",
                    "file_count": 42,
                },
            },
            "error": {
                "description": "Plan-resolution, boundary, or missing-export error.",
                "code": "PLAN_NOT_FOUND | EXPORT_PATH_INVALID | EXPORT_FILE_NOT_FOUND",
                "message": "Human-readable explanation.",
                "details": "Programmatic diagnostic fields such as plan.",
            },
        },
        "usage_examples": [
            {
                "description": "Archive a plan's export tree and retrieve it byte-identically.",
                "command": {"plan": "my-plan"},
                "explanation": (
                    "Run plan_export first and wait for its job to finish, then call "
                    "export_archive; feed the returned archive name to export_read, "
                    "advancing offset by chunk_size until eof, and check the reassembled "
                    "bytes against the sha256 returned here before unpacking."
                ),
            },
            {
                "description": "Refresh the archive after re-exporting a plan.",
                "command": {"plan": "5a1e9b0a-2222-4444-8888-abcdefabcdef"},
                "explanation": (
                    "Calling export_archive again replaces the previous archive in place "
                    "under the same name; copies never accumulate and the previous archive "
                    "is never packed into the new one."
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
                "description": "The plan's export directory does not resolve to a direct child of the export root (boundary refusal).",
                "message": "plan export directory does not resolve inside the export root",
                "solution": "Report this as a defect: a catalog plan name should always resolve to a single safe directory segment.",
            },
            "EXPORT_FILE_NOT_FOUND": {
                "description": "The plan has no produced export tree to archive: its export directory is absent or holds no packable file.",
                "message": "no export tree to archive for this plan",
                "solution": "Run plan_export for this plan and wait for the queued job to finish, then retry export_archive.",
            },
        },
        "best_practices": [
            "Run plan_export and wait for its queued job to complete before calling export_archive; the archive packs whatever tree is currently on disk.",
            "Retrieve the archive with export_read using the returned archive name, and verify the reassembled bytes against the returned sha256 BEFORE unpacking it.",
            "Treat the archive as an ordinary export artifact: it is removed with the rest of the plan's export by the normal lifecycle and cleanup rules.",
            "Re-run export_archive after every fresh plan_export; it replaces the previous archive in place rather than accumulating copies.",
        ],
    }
