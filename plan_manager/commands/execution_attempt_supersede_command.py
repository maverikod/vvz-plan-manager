"""Command: record that a stale execution attempt was replaced by a specific
later attempt, without touching the stale attempt's own status (bug 74479c06
group-4 fix; C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.commands.plan_completion_guard import refuse_if_execution_attempt_plan_completed
from plan_manager.runtime.context import db_connection
from plan_manager.storage.entity_supersede_store import supersede_execution_attempt
from plan_manager.storage.execution_attempt_store import get_execution_attempt


class ExecutionAttemptSupersedeCommand(Command):
    name: ClassVar[str] = "execution_attempt_supersede"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Record that a stale execution attempt was replaced by a specific later attempt. "
        "Never rewrites the stale attempt's own status or outcome fields -- only the forward pointer."
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
                    "description": "Execution attempt identifier (UUID) of the STALE attempt being superseded.",
                    "type": "string",
                    "required": True,
                },
                "superseded_by_uuid": {
                    "description": "Execution attempt identifier (UUID) of the REPLACEMENT attempt; must belong to the same step as attempt_id.",
                    "type": "string",
                    "required": True,
                },
                "changed_by": {
                    "description": "Actor recording this supersede.",
                    "type": "string",
                    "required": True,
                },
            },
            "required": ["attempt_id", "superseded_by_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        return_value = {
            "type": "object",
            "description": (
                "The stale execution attempt record after the write (all UUID fields rendered as strings), "
                "with an additional already_superseded boolean: true when the call was an idempotent no-op "
                "against an already-matching superseded_by_uuid."
            ),
        }
        examples = [
            {
                "description": "Record that a re-run attempt superseded a failed one.",
                "command": {
                    "attempt_id": "22222222-2222-2222-2222-222222222222",
                    "superseded_by_uuid": "33333333-3333-3333-3333-333333333333",
                    "changed_by": "orchestrator",
                },
            },
        ]
        best_practices = [
            "The stale attempt's own status and outcome fields are never rewritten by this command -- only superseded_by_uuid changes; use execution_attempt_report if the outcome itself needs correcting.",
            "superseded_by_uuid must belong to the same step_uuid as attempt_id; a replacement from a different step is refused as EXECUTION_ATTEMPT_LINEAGE_MISMATCH.",
            "Calling again with the SAME superseded_by_uuid already on file is idempotent (already_superseded: true, nothing written); calling with a DIFFERENT value is refused as EXECUTION_ATTEMPT_ALREADY_SUPERSEDED rather than silently overwriting the pointer.",
            "attempt_id and superseded_by_uuid must be different execution attempts; passing the same uuid for both is refused as EXECUTION_ATTEMPT_SELF_SUPERSEDE.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate execution_attempt_supersede parameters beyond the base schema check.

        Raises:
            InvalidParamsError: If attempt_id or superseded_by_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        for field in ("attempt_id", "superseded_by_uuid"):
            value = params.get(field)
            if value is not None:
                try:
                    uuid.UUID(value)
                except ValueError as exc:
                    raise InvalidParamsError(f"{field} is not a valid UUID: {value!r}") from exc
        return params

    async def execute(
        self,
        attempt_id: str,
        superseded_by_uuid: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                stale_uuid = uuid.UUID(attempt_id)
                replacement_uuid = uuid.UUID(superseded_by_uuid)
                existing_attempt = get_execution_attempt(conn, stale_uuid)
                if existing_attempt is None:
                    raise DomainCommandError(
                        "EXECUTION_ATTEMPT_NOT_FOUND", f"execution attempt not found: {attempt_id}"
                    )
                refuse_if_execution_attempt_plan_completed(conn, existing_attempt)
                record, already_superseded = supersede_execution_attempt(
                    conn,
                    stale_uuid,
                    superseded_by_uuid=replacement_uuid,
                    changed_by=changed_by,
                )
                payload = record.to_payload()
                payload["already_superseded"] = already_superseded
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
