"""ExportArchiveCommand: pack a plan's export tree into one archive (C-016).

Nothing on the plan_manager surface enumerates an export -- plan_export reports a
COUNT of files written, not their names -- so a caller cannot fetch a whole export
tree without guessing filenames. This command packs the already-produced tree into
ONE gzip-compressed tar inside the plan's own export directory and returns its
plan-relative name, size and sha256, so the shipped export_read command serves the
whole delivery back under one known name, under one digest, with no new transfer
machinery. plan_export is not modified.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.export_archive_metadata import get_export_archive_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.exchange.archiver import (
    ExportArchiveBoundaryError,
    ExportArchiveTreeMissingError,
    create_export_archive,
)
from plan_manager.runtime.context import app_config, db_connection


class ExportArchiveCommand(Command):
    """Pack a plan's produced export tree into one archive under its export directory."""

    name: ClassVar[str] = "export_archive"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Pack a plan's produced export tree into one archive under its export "
        "directory and report its name, size and sha256."
    )
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for export_archive."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier (UUID or catalog name) whose produced export "
                        "tree is packed into an archive under its export directory."
                    ),
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for export_archive."""
        return get_export_archive_metadata(cls)

    async def execute(
        self,
        plan: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Archive the resolved plan's produced export tree.

        Args:
            plan: Plan identifier resolved against the catalog.
            context: Unused platform context.

        Returns:
            SuccessResult with data {"plan": str, "archive": str, "size_bytes": int,
            "sha256": str, "file_count": int} on success, or ErrorResult with a
            domain code (PLAN_NOT_FOUND, EXPORT_PATH_INVALID,
            EXPORT_FILE_NOT_FOUND) on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)

            try:
                report = create_export_archive(app_config().export_root, p.name)
            except ExportArchiveBoundaryError:
                return domain_error(
                    "EXPORT_PATH_INVALID",
                    "plan export directory does not resolve inside the export root",
                    {"plan": p.name},
                )
            except ExportArchiveTreeMissingError:
                return domain_error(
                    "EXPORT_FILE_NOT_FOUND",
                    "no export tree to archive for this plan",
                    {"plan": p.name},
                )

            return SuccessResult(
                data={
                    "plan": p.name,
                    "archive": report["archive"],
                    "size_bytes": report["size_bytes"],
                    "sha256": report["sha256"],
                    "file_count": report["file_count"],
                }
            )
        except Exception as exc:
            return map_exception(exc)
