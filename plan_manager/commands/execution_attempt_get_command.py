"""Command: retrieve a single execution attempt by identifier (C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import get_execution_attempt


class ExecutionAttemptGetCommand(Command):
    name: ClassVar[str] = "execution_attempt_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single execution attempt by identifier."
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
                    "description": "Execution attempt identifier (UUID) to retrieve.",
                    "type": "string",
                    "required": True,
                },
            },
            "required": ["attempt_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        return_value = {
            "type": "object",
            "description": "The execution attempt record, with all UUID fields rendered as strings.",
        }
        examples = [
            {
                "description": "Retrieve an execution attempt by identifier.",
                "command": {"attempt_id": "22222222-2222-2222-2222-222222222222"},
            },
        ]
        best_practices = [
            "attempt_id must be an existing execution_attempt UUID; unknown ids return EXECUTION_ATTEMPT_NOT_FOUND instead of null.",
            "Use execution_attempt_list first to discover an attempt_id when it is not already known.",
            "Call again after execution_attempt_report to see the attempt's latest status and fields.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        attempt_id: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                attempt = get_execution_attempt(conn, validate_uuid(attempt_id))
                if attempt is None:
                    raise DomainCommandError(
                        "EXECUTION_ATTEMPT_NOT_FOUND",
                        f"execution attempt not found: {attempt_id}",
                    )
                return SuccessResult(data=attempt.to_payload())
        except Exception as exc:
            return map_exception(exc)
