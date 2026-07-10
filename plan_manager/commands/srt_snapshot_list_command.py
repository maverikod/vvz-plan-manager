"""Command: list the retained history of semantic tree snapshots for a plan."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.srt_command_metadata import BASE_PARAMETERS, srt_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.srt_snapshot_store import list_srt_snapshots


class SrtSnapshotListCommand(Command):
    name: ClassVar[str] = "srt_snapshot_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List the retained history of semantic tree snapshots for a plan (read-only)."
    category: ClassVar[str] = "srt"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {**BASE_PARAMETERS}
        return srt_metadata(
            cls,
            params,
            {"success": {"description": "List of SemanticTreeSnapshot payloads for the plan, ordered oldest first."}},
            [{"description": "List snapshot history for a plan.", "command": {"plan": "plan_manager"}}],
        )

    async def execute(
        self,
        plan: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                records = list_srt_snapshots(conn, p.uuid)
                return SuccessResult(data={"snapshots": [r.to_payload() for r in records]})
        except Exception as exc:
            return map_exception(exc)
