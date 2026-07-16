"""Export directory lifecycle: classify, size and purge the export artifacts
of a plan for the export_cleanup command (C-008, C-009, C-016).

An export directory is a direct child of the configured export root, named
after the plan it was exported from (plan_manager.exchange.exporter writes
one such directory per plan, named exactly plan.name). Every regular file
inside that directory is an ordinary export artifact, an export archive
(.tar.gz) produced for the plan included: an archive is counted, reported
and removed exactly like any other file, with no exemption, no extension
filter and no archive-aware branch anywhere in this module.

The export-root boundary rule is not restated here: this module imports the
single canonical resolver from plan_manager.exchange.export_paths, so every
operation that touches the export root enforces one identical rule.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import psycopg

from plan_manager.domain.plan import Plan, list_plans
from plan_manager.exchange.export_paths import resolve_export_subdirectory
from plan_manager.storage.runtime_audit_store import record_runtime_change


LIVE = "LIVE"
SOFT_DELETED_ORPHANED_ELIGIBLE = "SOFT_DELETED_ORPHANED_ELIGIBLE"
ORPHANED_UNRESOLVABLE = "ORPHANED_UNRESOLVABLE"
BOUNDARY_REFUSED = "BOUNDARY_REFUSED"


def _directory_size_and_manifest(path: Path) -> tuple[int, list[dict[str, object]]]:
    """Recursively sum file sizes under `path` and list every contained file.

    Every regular file found is included unconditionally: there is no
    extension filter, no name pattern and no exclusion list, so an export
    archive (.tar.gz) sitting in the tree is counted into the total and
    listed in the manifest exactly like any other file. Adding such a filter
    here would silently under-report a purge's blast radius and is forbidden.

    Args:
        path: Absolute directory path to walk.

    Returns:
        tuple[int, list[dict[str, object]]]: The total byte count of every
            regular file found under path (recursively), and a list of one
            dict per regular file with keys "path" (the file's path relative
            to `path`, using forward slashes) and "size" (the file's size in
            bytes as reported by Path.stat().st_size). Subdirectories that
            contain no files contribute no manifest entries and no bytes.
    """
    total_bytes = 0
    manifest: list[dict[str, object]] = []
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            file_path = Path(dirpath) / filename
            size = file_path.stat().st_size
            total_bytes += size
            manifest.append(
                {"path": file_path.relative_to(path).as_posix(), "size": size}
            )
    return total_bytes, manifest


def classify_export_directories(
    conn: psycopg.Connection,
    export_root: str,
    plan: str | None = None,
    include_orphaned: bool = False,
) -> dict[str, object]:
    """Classify and size export-root child directories for the dry-run preview.

    Enumerates the immediate child directories of export_root (or, when
    `plan` is given, considers only the single directory matching `plan`),
    resolves each candidate name against the plan catalog (including
    soft-deleted plans) by exact name match, and assigns exactly one
    classification: LIVE when the resolved plan has no deletion timestamp,
    SOFT_DELETED_ORPHANED_ELIGIBLE when the resolved plan has a deletion
    timestamp, ORPHANED_UNRESOLVABLE when no plan row matches the directory
    name at all, or BOUNDARY_REFUSED when the candidate name is rejected by
    resolve_export_subdirectory.

    BOUNDARY_REFUSED and ORPHANED_UNRESOLVABLE are distinct and must stay
    distinct: resolve_export_subdirectory judges only the name against the
    export-root boundary and never touches the disk, so a refusal means an
    unsafe name, while existence is a separate is_dir() check below and a
    missing plan row is a separate catalog lookup.

    A directory's contents never influence its classification: an export
    archive present in the tree is sized and listed as an ordinary file and
    does not make the directory eligible, ineligible, or special in any way.

    When `plan` is given: if it parses as a UUID and matches a plan row
    (including soft-deleted), that plan's name is used as the target
    directory name; otherwise `plan` itself is treated as the target
    directory name directly. When the target directory does not exist on
    disk, classified_directories is empty and preview_totals are all zero
    (not an error: there is genuinely nothing exported under that name).

    Args:
        conn: Open psycopg 3 database connection used to list the plan
            catalog (including soft-deleted plans).
        export_root: Configured export root directory to enumerate.
        plan: Optional plan name or UUID narrowing enumeration to a single
            directory; when None, every child directory of export_root is
            enumerated.
        include_orphaned: When True, directories classified
            ORPHANED_UNRESOLVABLE are included in the eligible-for-removal
            set and its aggregate totals; when False they are classified
            and reported but excluded from eligible-for-removal.

    Returns:
        dict[str, object]: {"classified_directories": list[dict], "preview_totals": dict}.
            Each classified_directories entry is a dict with keys
            "directory_name" (str), "classification" (one of LIVE,
            SOFT_DELETED_ORPHANED_ELIGIBLE, ORPHANED_UNRESOLVABLE,
            BOUNDARY_REFUSED), "plan_name" (str | None), "plan_uuid"
            (str | None), "byte_count" (int), "file_manifest" (list[dict]),
            and "eligible_for_removal" (bool: True only for
            SOFT_DELETED_ORPHANED_ELIGIBLE, or for ORPHANED_UNRESOLVABLE
            when include_orphaned is True; always False for LIVE and
            BOUNDARY_REFUSED). preview_totals is a dict with keys
            "eligible_directory_count", "eligible_file_count", and
            "eligible_byte_count", summed over entries with
            eligible_for_removal True.
    """
    all_plans = list_plans(conn, show_deleted=True)
    plans_by_name: dict[str, Plan] = {p.name: p for p in all_plans}
    plans_by_uuid: dict[uuid.UUID, Plan] = {p.uuid: p for p in all_plans}

    root_path = Path(export_root)
    if plan is not None:
        try:
            plan_as_uuid = uuid.UUID(plan)
        except ValueError:
            target_name = plan
        else:
            matched_by_uuid = plans_by_uuid.get(plan_as_uuid)
            target_name = matched_by_uuid.name if matched_by_uuid is not None else plan
        candidate_names = [target_name]
    else:
        if not root_path.is_dir():
            candidate_names = []
        else:
            candidate_names = sorted(
                entry.name for entry in root_path.iterdir() if entry.is_dir()
            )

    classified_directories: list[dict[str, object]] = []
    for name in candidate_names:
        resolved_path = resolve_export_subdirectory(export_root, name)
        if resolved_path is None:
            classified_directories.append(
                {
                    "directory_name": name,
                    "classification": BOUNDARY_REFUSED,
                    "plan_name": None,
                    "plan_uuid": None,
                    "byte_count": 0,
                    "file_manifest": [],
                    "eligible_for_removal": False,
                }
            )
            continue
        if not resolved_path.is_dir():
            continue

        matched_plan = plans_by_name.get(name)
        if matched_plan is None:
            classification = ORPHANED_UNRESOLVABLE
            plan_uuid_str: str | None = None
        elif matched_plan.deleted_at is not None:
            classification = SOFT_DELETED_ORPHANED_ELIGIBLE
            plan_uuid_str = str(matched_plan.uuid)
        else:
            classification = LIVE
            plan_uuid_str = str(matched_plan.uuid)

        byte_count, file_manifest = _directory_size_and_manifest(resolved_path)
        eligible = classification == SOFT_DELETED_ORPHANED_ELIGIBLE or (
            classification == ORPHANED_UNRESOLVABLE and include_orphaned
        )
        classified_directories.append(
            {
                "directory_name": name,
                "classification": classification,
                "plan_name": matched_plan.name if matched_plan is not None else None,
                "plan_uuid": plan_uuid_str,
                "byte_count": byte_count,
                "file_manifest": file_manifest,
                "eligible_for_removal": eligible,
            }
        )

    eligible_entries = [d for d in classified_directories if d["eligible_for_removal"]]
    preview_totals = {
        "eligible_directory_count": len(eligible_entries),
        "eligible_file_count": sum(len(d["file_manifest"]) for d in eligible_entries),
        "eligible_byte_count": sum(d["byte_count"] for d in eligible_entries),
    }
    return {"classified_directories": classified_directories, "preview_totals": preview_totals}


def remove_eligible_export_directories(
    export_root: str,
    eligible_directories: list[dict[str, object]],
    dry_run: bool,
) -> dict[str, object]:
    """Physically remove every eligible export directory from disk, or preview.

    Removal is whole-directory and therefore archive-inclusive: an export
    archive (.tar.gz) inside an eligible directory is removed together with
    the rest of that plan's export tree by the same recursive removal, with
    no separate step and no exemption. Its bytes and its file count are
    already part of the entry's byte_count and file_manifest and are
    therefore reported inside bytes_freed and files_removed, not separately.

    resolve_export_subdirectory is re-applied per directory as a
    defense-in-depth boundary check independent of the earlier classification
    pass. It judges the name only and never touches the disk, so a directory
    that vanished between classification and removal is caught by the
    is_dir() check below, not by the boundary check.

    Args:
        export_root: Configured export root directory; the sole boundary
            within which any directory may be removed.
        eligible_directories: The subset of classify_export_directories'
            classified_directories entries with eligible_for_removal True,
            each carrying "directory_name", "classification", "plan_name",
            "plan_uuid", "byte_count", and "file_manifest".
        dry_run: When True, no removal is performed and removal_outcomes is
            empty. When False, every entry is re-validated against
            resolve_export_subdirectory and, when valid, recursively
            removed with shutil.rmtree.

    Returns:
        dict[str, object]: {"removal_outcomes": list[dict], "removal_totals": dict}.
            Each removal_outcomes entry is a dict with keys
            "directory_name", "plan_name", "plan_uuid", "bytes_freed" (int),
            "files_removed" (int), "removed" (bool), and "failure_reason"
            (str | None, present with a non-None value only when removed is
            False). removal_totals is a dict with keys
            "directories_removed", "files_removed", and "total_bytes_freed",
            summed over entries with removed True.
    """
    removal_outcomes: list[dict[str, object]] = []
    if not dry_run:
        for entry in eligible_directories:
            name = entry["directory_name"]
            resolved_path = resolve_export_subdirectory(export_root, name)
            if resolved_path is None:
                removal_outcomes.append(
                    {
                        "directory_name": name,
                        "plan_name": entry.get("plan_name"),
                        "plan_uuid": entry.get("plan_uuid"),
                        "bytes_freed": 0,
                        "files_removed": 0,
                        "removed": False,
                        "failure_reason": "export root boundary validation refused this directory",
                    }
                )
                continue
            try:
                if not resolved_path.is_dir():
                    raise FileNotFoundError(f"directory vanished before removal: {resolved_path}")
                shutil.rmtree(resolved_path)
            except OSError as exc:
                removal_outcomes.append(
                    {
                        "directory_name": name,
                        "plan_name": entry.get("plan_name"),
                        "plan_uuid": entry.get("plan_uuid"),
                        "bytes_freed": 0,
                        "files_removed": 0,
                        "removed": False,
                        "failure_reason": str(exc),
                    }
                )
                continue
            removal_outcomes.append(
                {
                    "directory_name": name,
                    "plan_name": entry.get("plan_name"),
                    "plan_uuid": entry.get("plan_uuid"),
                    "bytes_freed": entry["byte_count"],
                    "files_removed": len(entry["file_manifest"]),
                    "removed": True,
                    "failure_reason": None,
                }
            )

    removed_entries = [o for o in removal_outcomes if o["removed"]]
    removal_totals = {
        "directories_removed": len(removed_entries),
        "files_removed": sum(o["files_removed"] for o in removed_entries),
        "total_bytes_freed": sum(o["bytes_freed"] for o in removed_entries),
    }
    return {"removal_outcomes": removal_outcomes, "removal_totals": removal_totals}


_ORPHANED_DIRECTORY_NAMESPACE = uuid.UUID("6f1a8e2a-6e5b-4b8a-9c0e-6a2f0f6c9b41")


def record_export_cleanup_audit(
    conn: psycopg.Connection,
    classified_directory: dict[str, object],
    dry_run: bool,
    removal_outcome: dict[str, object] | None,
    changed_by: str,
) -> dict[str, object]:
    """Write one runtime audit entry for one classified export directory.

    Args:
        conn: Open psycopg 3 database connection used to insert the audit
            row via record_runtime_change.
        classified_directory: One classify_export_directories entry:
            "directory_name", "classification", "plan_name", "plan_uuid",
            "byte_count", "file_manifest".
        dry_run: Whether the invocation that produced classified_directory
            was a dry run or a real run.
        removal_outcome: The remove_eligible_export_directories outcome for
            this directory when the invocation was a real run and the
            directory was eligible for removal ("removed", "bytes_freed",
            "files_removed", "failure_reason"); None for dry runs or
            directories not eligible for removal.
        changed_by: Actor identifier recorded on the audit entry.

    Returns:
        dict[str, object]: The written audit entry's to_payload() dict:
            "uuid", "plan_uuid", "entity_type", "entity_id", "action",
            "changed_by", "change_reason", "changed_fields", "created_at".
    """
    plan_uuid_str = classified_directory.get("plan_uuid")
    if plan_uuid_str is not None:
        entity_type = "plan"
        target_uuid = uuid.UUID(plan_uuid_str)
        plan_uuid = target_uuid
    else:
        entity_type = "export_directory"
        target_uuid = uuid.uuid5(
            _ORPHANED_DIRECTORY_NAMESPACE, classified_directory["directory_name"]
        )
        plan_uuid = None

    if not dry_run and removal_outcome is not None and removal_outcome["removed"]:
        action = "hard_delete"
        changed_fields = {
            "dry_run": False,
            "classification": classified_directory["classification"],
            "bytes_freed": removal_outcome["bytes_freed"],
            "files_removed": removal_outcome["files_removed"],
        }
    elif not dry_run and removal_outcome is not None:
        action = "update"
        changed_fields = {
            "dry_run": False,
            "removed": False,
            "failure_reason": removal_outcome["failure_reason"],
            "bytes_freed": 0,
        }
    else:
        action = "update"
        changed_fields = {
            "dry_run": True,
            "classification": classified_directory["classification"],
            "byte_count": classified_directory["byte_count"],
            "file_count": len(classified_directory["file_manifest"]),
            "bytes_freed": 0,
        }

    record = record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type=entity_type,
        entity_id=target_uuid,
        action=action,
        changed_by=changed_by,
        changed_fields=changed_fields,
    )
    return record.to_payload()
