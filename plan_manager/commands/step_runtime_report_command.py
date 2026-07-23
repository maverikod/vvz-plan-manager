"""Command: report runtime parameters for one step."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_runtime_report_metadata import (
    get_step_runtime_report_metadata,
)
from plan_manager.domain.step_runtime import report_runtime_record
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.step_runtime_scope import resolve_step_by_id


class StepRuntimeReportCommand(Command):
    """Merge runtime parameters for one step without changing definitions."""

    name: ClassVar[str] = "step_runtime_report"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Merge runtime parameters for one plan step."
    category: ClassVar[str] = "step"
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
                "step_id": {"type": "string", "description": "Step to merge runtime into, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID."},
                "payload": {
                    "type": "object",
                    "description": "Partial RuntimeRecord payload.",
                },
            },
            "required": ["plan", "step_id", "payload"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_runtime_report_metadata(cls)

    async def execute(
        self,
        plan: str,
        step_id: str,
        payload: dict[str, Any],
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                step = resolve_step_by_id(nodes, step_id)
                runtime = report_runtime_record(conn, p.uuid, step.uuid, payload)
                return SuccessResult(data={"step_id": step.step_id, "runtime": runtime})
        except Exception as exc:
            return map_exception(exc)
