"""Metadata for the export_cleanup command."""

from typing import Any


def get_export_cleanup_metadata(cls: Any) -> dict:
    """Return the full metadata dictionary for ExportCleanupCommand.

    Args:
        cls: The ExportCleanupCommand class, providing name, version, descr,
            category, author, email class attributes.

    Returns:
        dict: Metadata dictionary conforming to metadatastd.yaml
            required_fields: name, version, description, category,
            author, email, detailed_description, parameters,
            return_value, usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Purges export artifacts left behind under the configured export "
            "root without ever requiring filesystem access from the caller "
            "(C-008, C-009, C-016). Scope is per plan: the optional plan "
            "parameter narrows the operation to the single export directory "
            "named for that plan; when omitted, every directory directly "
            "under the export root is considered. Each candidate directory "
            "is classified against the plan catalog (including soft-deleted "
            "plans): LIVE when its plan exists and is not deleted (never "
            "eligible for removal), SOFT_DELETED_ORPHANED_ELIGIBLE when its "
            "plan exists and is soft-deleted (always eligible), or "
            "ORPHANED_UNRESOLVABLE when no plan row matches the directory "
            "name at all (eligible only when include_orphaned=true; "
            "otherwise reported but left untouched). Every regular file in a "
            "reported directory is counted, including an export archive "
            "(.tar.gz) produced for that plan by export_archive: an archive "
            "is an ordinary export artifact with no exemption, so its bytes "
            "are counted in a dry run's reported totals and it is removed "
            "together with the rest of the tree on a real run, exactly like "
            "any other file. There is no archive-specific parameter, filter "
            "or special case, and a stale archive left by an earlier export "
            "is purged like any other artifact. dry_run defaults to true: in "
            "that mode nothing is removed and the response reports the exact "
            "directories, their files, and their byte counts that would be "
            "removed. Passing dry_run=false performs the removal: every "
            "eligible directory that re-passes the export-root boundary "
            "check is recursively deleted from disk. A plan filter that "
            "matches nothing on disk is not an error: the response is a "
            "truthful empty-scope result (zero directories, zero bytes). "
            "The command refuses, with EXPORT_PATH_INVALID, a caller-supplied "
            "plan filter whose resolved directory name would escape the "
            "export root; when sweeping every directory instead, such an "
            "entry is reported inline as a boundary refusal rather than "
            "aborting the sweep. Every invocation, dry or real, writes one "
            "runtime audit entry per classified directory in scope through "
            "the existing runtime audit machinery, recording the acting "
            "changed_by, the target plan or export directory, a timestamp, "
            "and bytes freed (zero for dry runs and for failed removals)."
        ),
        "parameters": {
            "plan": {
                "description": (
                    "Optional plan name or UUID narrowing scope to that "
                    "plan's single export directory; a UUID is resolved to "
                    "its plan name via the plan catalog (including "
                    "soft-deleted plans) before matching against export "
                    "directory names. Omit to sweep every directory under "
                    "the export root."
                ),
                "type": "string",
                "required": False,
                "examples": ["my-plan", "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e"],
            },
            "include_orphaned": {
                "description": (
                    "False (default): directories with no matching plan row "
                    "at all (ORPHANED_UNRESOLVABLE) are classified and "
                    "reported but never removed. True: such directories are "
                    "also eligible for removal."
                ),
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "dry_run": {
                "description": (
                    "True (default): report the exact directories, files, "
                    "and byte counts that would be removed; nothing is "
                    "removed. False: actually remove every eligible "
                    "directory."
                ),
                "type": "boolean",
                "required": False,
                "default": True,
            },
            "changed_by": {
                "description": (
                    "Identity of the acting caller; recorded on every "
                    "runtime audit entry this invocation writes."
                ),
                "type": "string",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "On a dry run: the classified directory list and "
                    "aggregate preview totals. On a real run: the removal "
                    "outcome list and aggregate removal totals."
                ),
                "data": {
                    "dry_run": "Whether this invocation was a dry run.",
                    "classified_directories": (
                        "Dry-run only: one entry per candidate directory in "
                        "scope with directory_name, classification, "
                        "plan_name, plan_uuid, byte_count, file_manifest, "
                        "eligible_for_removal."
                    ),
                    "preview_totals": (
                        "Dry-run only: eligible_directory_count, "
                        "eligible_file_count, eligible_byte_count."
                    ),
                    "removal_outcomes": (
                        "Real-run only: one entry per eligible directory "
                        "processed with directory_name, plan_name, "
                        "plan_uuid, bytes_freed, files_removed, removed, "
                        "failure_reason."
                    ),
                    "removal_totals": (
                        "Real-run only: directories_removed, files_removed, "
                        "total_bytes_freed."
                    ),
                },
                "example": {
                    "dry_run": True,
                    "classified_directories": [
                        {
                            "directory_name": "old-plan",
                            "classification": "SOFT_DELETED_ORPHANED_ELIGIBLE",
                            "plan_name": "old-plan",
                            "plan_uuid": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                            "byte_count": 8192,
                            "file_manifest": [
                                {"path": "spec.yaml", "size": 4096},
                                {"path": "old-plan.tar.gz", "size": 4096},
                            ],
                            "eligible_for_removal": True,
                        }
                    ],
                    "preview_totals": {
                        "eligible_directory_count": 1,
                        "eligible_file_count": 2,
                        "eligible_byte_count": 8192,
                    },
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "EXPORT_PATH_INVALID",
                "message": "export directory name escapes the export root",
            },
        },
        "usage_examples": [
            {
                "description": "Preview what a per-plan cleanup would remove.",
                "command": {"plan": "old-plan", "changed_by": "agent-1"},
                "explanation": (
                    "dry_run defaults to true: reports old-plan's export "
                    "directory contents and byte count without removing "
                    "anything."
                ),
            },
            {
                "description": "Actually remove a soft-deleted plan's export directory.",
                "command": {"plan": "old-plan", "changed_by": "agent-1", "dry_run": False},
                "explanation": (
                    "Removes old-plan's export directory from disk if it is "
                    "SOFT_DELETED_ORPHANED_ELIGIBLE, archive included; a "
                    "LIVE plan's directory is never removed."
                ),
            },
            {
                "description": "Preview a full sweep including true orphans.",
                "command": {"include_orphaned": True, "changed_by": "agent-1"},
                "explanation": (
                    "Scans every directory under the export root and "
                    "includes directories with no matching plan row at all "
                    "in the eligible-for-removal preview."
                ),
            },
        ],
        "error_cases": {
            "EXPORT_PATH_INVALID": {
                "description": (
                    "A caller-supplied plan filter resolves to a directory "
                    "name that fails export-root boundary validation (an "
                    "unsafe or traversal-shaped name)."
                ),
                "message": "export directory name escapes the export root: {plan}",
                "solution": (
                    "Pass a plain plan name or UUID with no path separators "
                    "or '..' segments."
                ),
            },
        },
        "best_practices": [
            "dry_run defaults to true; always review the preview's classified_directories and preview_totals before retrying with dry_run=false.",
            "A plan filter matching nothing on disk is not an error: it returns an empty, truthful preview.",
            "include_orphaned=true widens removal to directories with no matching plan row at all; omit it to only ever touch directories of plans that were actually soft-deleted.",
            "An export archive is an ordinary artifact here: it is counted in the preview and removed with its directory. To keep an archive, do not clean up that plan's directory - there is no per-file exemption.",
            "Every invocation, dry or real, is recorded on the runtime audit trail under changed_by; inspect it to reconstruct who purged what and when.",
        ],
    }
