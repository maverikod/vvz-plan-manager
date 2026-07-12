"""Command: record the outcome of an execution attempt run (C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import report_execution_attempt


ATTEMPT_STATUS_VALUES = [
    "queued", "running", "succeeded", "failed", "cancelled", "timed_out",
    "needs_review", "needs_escalation",
]


class ExecutionAttemptReportCommand(Command):
    name: ClassVar[str] = "execution_attempt_report"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Record the outcome of an execution attempt run. Never a confirmation of "
        "correctness -- acceptance is recorded separately by a review result."
    )
    category: ClassVar[str] = "execution"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "attempt_id": {
                    "description": "Execution attempt identifier (UUID) to report against.",
                    "type": "string",
                    "required": True,
                },
                "changed_by": {
                    "description": "Actor recording this report.",
                    "type": "string",
                    "required": True,
                },
                "status": {
                    "description": "Optional new execution attempt status.",
                    "type": "string",
                    "enum": ATTEMPT_STATUS_VALUES,
                    "required": False,
                },
                "used_provider": {
                    "description": "Optional model provider actually used for the run.",
                    "type": "string",
                    "required": False,
                },
                "used_model": {
                    "description": "Optional model actually used for the run.",
                    "type": "string",
                    "required": False,
                },
                "result_summary": {
                    "description": "Optional prose summary of the run's result.",
                    "type": "string",
                    "required": False,
                },
                "changed_files": {
                    "description": "Optional list of files changed by the run.",
                    "type": "array",
                    "required": False,
                },
                "command_test_results": {
                    "description": "Optional object recording command/test results from the run.",
                    "type": "object",
                    "required": False,
                },
                "resource_accounting": {
                    "description": "Optional object recording token/runtime/GPU accounting for the run.",
                    "type": "object",
                    "required": False,
                },
                "error": {
                    "description": "Optional error text recorded for the run.",
                    "type": "string",
                    "required": False,
                },
                "escalation_reason": {
                    "description": "Optional reason recorded when the run needs escalation.",
                    "type": "string",
                    "required": False,
                },
                "input_context_hash": {
                    "description": "Optional hash of the input context supplied to the run.",
                    "type": "string",
                    "required": False,
                },
            },
            "required": ["attempt_id", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        return_value = {
            "type": "object",
            "description": "The updated execution attempt record, with all UUID fields rendered as strings.",
        }
        examples = [
            {
                "description": "Report a successful run outcome for an execution attempt.",
                "command": {
                    "attempt_id": "22222222-2222-2222-2222-222222222222",
                    "changed_by": "orchestrator",
                    "status": "succeeded",
                    "result_summary": "Implemented the atomic step and tests pass.",
                },
            },
        ]
        best_practices = [
            "This command records run outcome only; acceptance/correctness is recorded separately by a review result, never here.",
            "Only the fields you pass are updated; omit fields you have no new value for instead of resending old values.",
            "Setting status to a terminal value (succeeded/failed/cancelled/timed_out) auto-stamps finished_at.",
            "Set escalation_reason whenever you report status='needs_escalation' so reviewers know why.",
            "changed_by is the actor filing this report and may differ from the attempt's created_by.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        attempt_id: str,
        changed_by: str,
        status: str | None = None,
        used_provider: str | None = None,
        used_model: str | None = None,
        result_summary: str | None = None,
        changed_files: list[Any] | None = None,
        command_test_results: dict[str, Any] | None = None,
        resource_accounting: dict[str, Any] | None = None,
        error: str | None = None,
        escalation_reason: str | None = None,
        input_context_hash: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                attempt = report_execution_attempt(
                    conn,
                    uuid.UUID(attempt_id),
                    changed_by=changed_by,
                    status=status,
                    used_provider=used_provider,
                    used_model=used_model,
                    result_summary=result_summary,
                    changed_files=changed_files,
                    command_test_results=command_test_results,
                    resource_accounting=resource_accounting,
                    error=error,
                    escalation_reason=escalation_reason,
                    input_context_hash=input_context_hash,
                )
                return SuccessResult(data=attempt.to_payload())
        except Exception as exc:
            return map_exception(exc)
