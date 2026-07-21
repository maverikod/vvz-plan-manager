"""Command: update a bug fix propagation record's status, assignment, evidence, or linked TODO (C-025, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.bug_propagation_command_metadata import bug_propagation_metadata, BASE_PARAMETERS
from plan_manager.domain.bug_fix_propagation_status_transitions import guard_propagation_transition
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_derived_status_store import recompute_bug_status
from plan_manager.storage.bug_fix_propagation_store import get_bug_fix_propagation, update_bug_fix_propagation
from plan_manager.storage.bug_fix_store import get_bug_fix


class BugPropagationUpdateCommand(Command):
    name: ClassVar[str] = "bug_propagation_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Update a bug fix propagation record's status, assignment, evidence, or linked TODO."
    category: ClassVar[str] = "propagation"
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
                "propagation_id": {"type": "string", "description": "UUID of the bug fix propagation record to update."},
                "changed_by": {"type": "string", "description": "Actor performing this update, recorded as the audited change actor."},
                "status": {"type": "string", "description": "New status (one of the 8 PropagationStatus values)."},
                "assigned_to": {"type": "string", "description": "New assignee for the propagation action."},
                "evidence": {"type": "object", "description": "Evidence payload supporting the propagation's current state."},
                "verification_result": {"type": "string", "description": "Verification result recorded for this propagation."},
                "linked_todo_id": {"type": "string", "description": "UUID of the TODO item this propagation links to."},
            },
            "required": ["plan", "propagation_id", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "propagation_id": {"description": "UUID of the bug fix propagation record to update.", "type": "string", "required": True},
            "changed_by": {"description": "Actor performing this update.", "type": "string", "required": True},
            "status": {"description": "New status.", "type": "string", "required": False},
            "assigned_to": {"description": "New assignee for the propagation action.", "type": "string", "required": False},
            "evidence": {"description": "Evidence payload.", "type": "object", "required": False},
            "verification_result": {"description": "Verification result recorded for this propagation.", "type": "string", "required": False},
            "linked_todo_id": {"description": "UUID of the linked TODO item.", "type": "string", "required": False},
        }
        return bug_propagation_metadata(
            cls,
            params,
            {"success": {"description": "The updated bug fix propagation record payload, with every UUID field rendered as a string."}},
            [{
                "description": "Mark a propagation in progress.",
                "command": {
                    "plan": "plan_manager",
                    "propagation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "changed_by": "agent-1",
                    "status": "in_progress",
                },
            }],
            best_practices=[
                "Move status to in_progress before finishing; started_at is recorded automatically on the first such transition.",
                "Attach evidence when moving a propagation toward done or verified.",
                "Use verification_result to record the outcome once a propagation reaches verified.",
                "Set linked_todo_id when a generated TODO tracks this propagation's work.",
            ],
        )

    async def execute(
        self,
        plan: str,
        propagation_id: str,
        changed_by: str,
        status: str | None = None,
        assigned_to: str | None = None,
        evidence: dict[str, Any] | None = None,
        verification_result: str | None = None,
        linked_todo_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                propagation_uuid = uuid.UUID(propagation_id)
                existing = get_bug_fix_propagation(conn, propagation_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_PROPAGATION_NOT_FOUND", f"bug propagation not found: {propagation_id}")
                if status is not None:
                    guard_propagation_transition(existing.status, status)
                record = update_bug_fix_propagation(
                    conn,
                    propagation_uuid,
                    changed_by=changed_by,
                    status=status,
                    assigned_to=assigned_to,
                    evidence=evidence,
                    verification_result=verification_result,
                    linked_todo_uuid=uuid.UUID(linked_todo_id) if linked_todo_id is not None else None,
                )
                fix_record = get_bug_fix(conn, existing.bug_fix_uuid)
                if fix_record is not None:
                    recompute_bug_status(conn, fix_record.bug_uuid, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
