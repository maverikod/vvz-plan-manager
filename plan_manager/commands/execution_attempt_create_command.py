"""Command: create a new execution attempt anchored to a plan/step (C-016 via C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.execution_attempt_command_metadata import execution_attempt_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import create_execution_attempt


ATTEMPT_STATUS_VALUES = [
    "queued", "running", "succeeded", "failed", "cancelled", "timed_out",
    "needs_review", "needs_escalation",
]


class ExecutionAttemptCreateCommand(Command):
    name: ClassVar[str] = "execution_attempt_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new execution attempt anchored to a plan/step."
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
                **BASE_PARAMETERS,
                "step": {
                    "description": "Step identifier (UUID) the execution attempt is anchored to.",
                    "type": "string",
                    "required": True,
                },
                "revision": {
                    "description": "Optional revision identifier (UUID) the execution attempt is anchored to.",
                    "type": "string",
                    "required": False,
                },
                "status": {
                    "description": "Initial execution attempt status.",
                    "type": "string",
                    "enum": ATTEMPT_STATUS_VALUES,
                    "required": True,
                },
                "created_by": {
                    "description": "Actor creating the execution attempt.",
                    "type": "string",
                    "required": True,
                },
                "todo_id": {
                    "description": "Optional todo identifier (UUID) this attempt is linked to.",
                    "type": "string",
                    "required": False,
                },
                "bug_fix_id": {
                    "description": "Optional bug fix identifier (UUID) this attempt is linked to.",
                    "type": "string",
                    "required": False,
                },
                "assigned_binding_id": {
                    "description": "Optional model binding identifier (UUID) assigned to this attempt.",
                    "type": "string",
                    "required": False,
                },
                "assigned_provider": {
                    "description": "Optional assigned model provider name.",
                    "type": "string",
                    "required": False,
                },
                "assigned_model": {
                    "description": "Optional assigned model name.",
                    "type": "string",
                    "required": False,
                },
                "runtime": {
                    "description": "Optional runtime environment identifier.",
                    "type": "string",
                    "required": False,
                },
                "vast_instance_id": {
                    "description": "Optional Vast.ai instance identifier.",
                    "type": "string",
                    "required": False,
                },
                "input_context_hash": {
                    "description": "Optional hash of the input context supplied to the run.",
                    "type": "string",
                    "required": False,
                },
                "parent_attempt_id": {
                    "description": "Optional parent execution attempt identifier (UUID) for retries.",
                    "type": "string",
                    "required": False,
                },
            },
            "required": ["plan", "step", "status", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = dict(cls.get_schema()["properties"])
        return_value = {
            "type": "object",
            "description": "The created execution attempt record, with all UUID fields rendered as strings.",
        }
        examples = [
            {
                "description": "Create a queued execution attempt for a step.",
                "command": {
                    "plan": "my-plan",
                    "step": "11111111-1111-1111-1111-111111111111",
                    "status": "queued",
                    "created_by": "orchestrator",
                },
            },
        ]
        best_practices = [
            "Create with status='queued'; only pass 'running' when the run is starting immediately, since started_at is stamped automatically for that status.",
            "step must belong to the given plan (and revision, if supplied), or the call fails with INVALID_ANCHOR.",
            "Set parent_attempt_id when this attempt retries a prior execution_attempt, to preserve retry lineage.",
            "created_by must be the real creating actor identity, not a placeholder.",
            "Follow up with execution_attempt_report to record the run's outcome; this command only opens the record.",
        ]
        return execution_attempt_metadata(cls, params, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        plan: str,
        step: str,
        status: str,
        created_by: str,
        revision: str | None = None,
        todo_id: str | None = None,
        bug_fix_id: str | None = None,
        assigned_binding_id: str | None = None,
        assigned_provider: str | None = None,
        assigned_model: str | None = None,
        runtime: str | None = None,
        vast_instance_id: str | None = None,
        input_context_hash: str | None = None,
        parent_attempt_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                attempt = create_execution_attempt(
                    conn,
                    plan_uuid=p.uuid,
                    step_uuid=uuid.UUID(step),
                    status=status,
                    created_by=created_by,
                    revision_uuid=uuid.UUID(revision) if revision is not None else None,
                    todo_uuid=uuid.UUID(todo_id) if todo_id is not None else None,
                    bug_fix_uuid=uuid.UUID(bug_fix_id) if bug_fix_id is not None else None,
                    assigned_binding_uuid=uuid.UUID(assigned_binding_id) if assigned_binding_id is not None else None,
                    assigned_provider=assigned_provider,
                    assigned_model=assigned_model,
                    used_provider=None,
                    used_model=None,
                    runtime=runtime,
                    vast_instance_id=vast_instance_id,
                    input_context_hash=input_context_hash,
                    parent_attempt_uuid=uuid.UUID(parent_attempt_id) if parent_attempt_id is not None else None,
                )
                return SuccessResult(data=attempt.to_payload())
        except Exception as exc:
            return map_exception(exc)
