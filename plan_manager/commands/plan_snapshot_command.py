"""PlanSnapshotCommand: export the effective working plan state."""

from typing import Any, ClassVar, Dict, Type

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_snapshot_metadata import get_plan_snapshot_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.exchange.exporter import export_working_snapshot
from plan_manager.exchange.importer import validate_layout
from plan_manager.runtime.context import app_config, db_connection


class PlanSnapshotCommand(Command):
    """Render an importable snapshot of the plan's live working state."""

    name: ClassVar[str] = "plan_snapshot"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Export an importable snapshot of a plan's live working state."
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[Type[SuccessResult]] = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for plan_snapshot."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier resolved against the catalog.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return extended documentation metadata for plan_snapshot."""
        return get_plan_snapshot_metadata(cls)

    async def execute(
        self,
        plan: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Export and validate the resolved plan's working-state snapshot."""
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                summary = export_working_snapshot(conn, p.uuid, app_config().export_root)
            issues = validate_layout(summary["root"])
            if issues:
                return domain_error(
                    "IMPORT_INVALID",
                    "snapshot layout validation failed",
                    {"issues": issues},
                )
            return SuccessResult(
                data={
                    "root": summary["root"],
                    "files": summary["files"],
                    "based_on_revision": summary["based_on_revision"],
                    "cascade_uuid": summary["cascade_uuid"],
                    "snapshot_revision": summary["snapshot_revision"],
                    "importable": True,
                }
            )
        except Exception as exc:
            return map_exception(exc)
