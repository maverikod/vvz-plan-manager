"""Command: compute the semantic diff between two semantic tree snapshots (read-only)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.srt_command_metadata import BASE_PARAMETERS, srt_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.scoring.srt_diff import compute_semantic_diff
from plan_manager.storage.srt_snapshot_store import get_srt_snapshot


class SrtDiffCommand(Command):
    name: ClassVar[str] = "srt_diff"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compute the semantic diff between two semantic tree snapshots (read-only)."
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
                "base_snapshot_uuid": {"type": "string", "description": "UUID of the earlier snapshot (comparison baseline)."},
                "target_snapshot_uuid": {"type": "string", "description": "UUID of the later snapshot compared against the base."},
            },
            "required": ["plan", "base_snapshot_uuid", "target_snapshot_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "base_snapshot_uuid": {"description": "UUID of the earlier snapshot (comparison baseline).", "type": "string", "required": True},
            "target_snapshot_uuid": {"description": "UUID of the later snapshot compared against the base.", "type": "string", "required": True},
        }
        return srt_metadata(
            cls,
            params,
            {"success": {"description": "SemanticDiff payload: root_score_delta, improved_nodes, degraded_nodes, new_loss, resolved_loss, new_leakage, resolved_leakage, child_contribution_changes."}},
            [{"description": "Diff two snapshots for a plan.", "command": {"plan": "plan_manager", "base_snapshot_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "target_snapshot_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef"}}],
        )

    async def execute(
        self,
        plan: str,
        base_snapshot_uuid: str,
        target_snapshot_uuid: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                base_record = get_srt_snapshot(conn, uuid.UUID(base_snapshot_uuid))
                if base_record is None:
                    raise DomainCommandError("SNAPSHOT_NOT_FOUND", f"snapshot not found: {base_snapshot_uuid}")
                target_record = get_srt_snapshot(conn, uuid.UUID(target_snapshot_uuid))
                if target_record is None:
                    raise DomainCommandError("SNAPSHOT_NOT_FOUND", f"snapshot not found: {target_snapshot_uuid}")
                result = compute_semantic_diff(base_record.tree_content, target_record.tree_content)
                return SuccessResult(data=result.to_payload())
        except Exception as exc:
            return map_exception(exc)
