"""Command: export_cleanup -- purge export artifacts that no longer belong to a live plan (C-008, C-009)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.export_cleanup_metadata import get_export_cleanup_metadata
from plan_manager.exchange.export_cleanup import (
    BOUNDARY_REFUSED,
    classify_export_directories,
    record_export_cleanup_audit,
    remove_eligible_export_directories,
)
from plan_manager.runtime.context import app_config, db_connection


class ExportCleanupCommand(Command):
    name: ClassVar[str] = "export_cleanup"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Purge export artifacts that no longer belong to a live plan: per-plan scope, dry_run=true by default, audited."
    category: ClassVar[str] = "transfer"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for export_cleanup."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Optional plan name or UUID narrowing scope to that plan's export directory; omit to sweep every directory under the export root.",
                },
                "include_orphaned": {
                    "type": "boolean",
                    "description": "When true, directories with no matching plan row at all are also eligible for removal; when false (default) they are reported but never removed.",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true (default), report what would be removed without removing anything. When false, actually remove every eligible directory.",
                    "default": True,
                },
                "changed_by": {
                    "type": "string",
                    "description": "Identity of the acting caller; recorded on every runtime audit entry this invocation writes.",
                },
            },
            "required": ["changed_by"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        changed_by: str,
        plan: str | None = None,
        include_orphaned: bool = False,
        dry_run: bool = True,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Classify, and optionally remove, export directories under the configured export root."""
        try:
            with db_connection() as conn:
                export_root = app_config().export_root
                result = classify_export_directories(
                    conn, export_root, plan=plan, include_orphaned=include_orphaned
                )
                classified_directories = result["classified_directories"]

                if plan is not None:
                    for entry in classified_directories:
                        if entry["classification"] == BOUNDARY_REFUSED:
                            raise DomainCommandError(
                                "EXPORT_PATH_INVALID",
                                f"export directory name escapes the export root: {plan}",
                                {"plan": plan},
                            )

                eligible_directories = [
                    entry for entry in classified_directories if entry["eligible_for_removal"]
                ]

                if dry_run:
                    for entry in classified_directories:
                        if entry["classification"] == BOUNDARY_REFUSED:
                            continue
                        record_export_cleanup_audit(
                            conn, entry, dry_run=True, removal_outcome=None, changed_by=changed_by
                        )
                    return SuccessResult(
                        data={
                            "dry_run": True,
                            "classified_directories": classified_directories,
                            "preview_totals": result["preview_totals"],
                        }
                    )

                removal_result = remove_eligible_export_directories(
                    export_root, eligible_directories, dry_run=False
                )
                outcomes_by_name = {
                    outcome["directory_name"]: outcome
                    for outcome in removal_result["removal_outcomes"]
                }
                for entry in classified_directories:
                    if entry["classification"] == BOUNDARY_REFUSED:
                        continue
                    outcome = outcomes_by_name.get(entry["directory_name"])
                    if entry["eligible_for_removal"]:
                        record_export_cleanup_audit(
                            conn, entry, dry_run=False, removal_outcome=outcome, changed_by=changed_by
                        )
                    else:
                        record_export_cleanup_audit(
                            conn, entry, dry_run=True, removal_outcome=None, changed_by=changed_by
                        )
                return SuccessResult(
                    data={
                        "dry_run": False,
                        "removal_outcomes": removal_result["removal_outcomes"],
                        "removal_totals": removal_result["removal_totals"],
                    }
                )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for export_cleanup."""
        return get_export_cleanup_metadata(cls)
