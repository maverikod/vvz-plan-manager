"""Command: list execution attempts filtered by anchor, status, and parent lineage (C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.domain.execution_attempt import ATTEMPT_STATUSES
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import list_execution_attempts


class ExecutionAttemptListCommand(Command):
    name: ClassVar[str] = "execution_attempt_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "List execution attempts filtered by plan, step, status, and parent "
        "attempt lineage."
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
                "plan": {
                    "description": "Optional plan identifier (name or UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "step": {
                    "description": "Optional step identifier (UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "status": {
                    "description": (
                        "Optional execution attempt status to filter by. One of the 8 "
                        "ExecutionAttemptStatus values, in declared order: queued, running, "
                        "succeeded, failed, cancelled, timed_out, needs_review, "
                        "needs_escalation."
                    ),
                    "type": "string",
                    "enum": [
                        "queued",
                        "running",
                        "succeeded",
                        "failed",
                        "cancelled",
                        "timed_out",
                        "needs_review",
                        "needs_escalation",
                    ],
                    "required": False,
                },
                "parent_attempt_id": {
                    "description": "Optional parent execution attempt identifier (UUID) to filter by.",
                    "type": "string",
                    "required": False,
                },
                "include_deleted": {
                    "description": "Include soft-deleted execution attempts. Defaults to false.",
                    "type": "boolean",
                    "required": False,
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        return_value = {
            "type": "array",
            "description": "The matching execution attempt records, with all UUID fields rendered as strings.",
        }
        examples = [
            {
                "description": "List queued execution attempts for a plan.",
                "command": {"plan": "my-plan", "status": "queued"},
            },
        ]
        best_practices = [
            "All filters are optional; omit plan/step/status/parent_attempt_id to list every execution attempt in scope.",
            "Results are ordered by created_at ascending, oldest attempt first.",
            "include_deleted defaults to false; set it true only to audit soft-deleted attempts.",
            "Filter by parent_attempt_id to walk a retry lineage originating from a given attempt.",
            "Combine plan and status to check outstanding queued/running attempts before creating new ones.",
            "No transition matrix is enforced on execution attempt status: execution_attempt_report "
            "accepts any of the 8 ExecutionAttemptStatus values regardless of the attempt's current "
            "status, so this filter reflects whatever status was most recently reported, not a "
            "state-machine-validated progression.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        plan: str | None = None,
        step: str | None = None,
        status: str | None = None,
        parent_attempt_id: str | None = None,
        include_deleted: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_uuid = None
                if plan is not None:
                    p = resolve_plan(conn, plan)
                    plan_uuid = p.uuid
                if status is not None and status not in ATTEMPT_STATUSES:
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        f"'status' must be one of {sorted(ATTEMPT_STATUSES)}; got {status!r}",
                    )
                attempts = list_execution_attempts(
                    conn,
                    plan_uuid=plan_uuid,
                    step_uuid=uuid.UUID(step) if step is not None else None,
                    status=status,
                    parent_attempt_uuid=uuid.UUID(parent_attempt_id) if parent_attempt_id is not None else None,
                    include_deleted=include_deleted,
                )
                return SuccessResult(data=[a.to_payload() for a in attempts])
        except Exception as exc:
            return map_exception(exc)
