"""Command: generate linked TODO items for the pending propagations of a bug fix (C-025, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.bug_propagation_command_metadata import bug_propagation_metadata, BASE_PARAMETERS
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations, update_bug_fix_propagation
from plan_manager.storage.todo_store import create_todo


class BugPropagationGenerateTodosCommand(Command):
    name: ClassVar[str] = "bug_propagation_generate_todos"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Generate linked TODO items for every pending propagation of a bug fix."
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
                "bug_fix_id": {"type": "string", "description": "UUID of the bug fix whose pending propagations receive generated TODO items."},
                "created_by": {"type": "string", "description": "Actor creating the generated TODO items and updating the propagation records."},
            },
            "required": ["plan", "bug_fix_id", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug_fix_id": {"description": "UUID of the bug fix whose pending propagations receive generated TODO items.", "type": "string", "required": True},
            "created_by": {"description": "Actor creating the generated TODO items and updating the propagation records.", "type": "string", "required": True},
        }
        return bug_propagation_metadata(
            cls,
            params,
            {"success": {"description": "List of {propagation_id, todo_id} pairs for every pending propagation that received a generated TODO."}},
            [{
                "description": "Generate TODOs for the pending propagations of a bug fix.",
                "command": {"plan": "plan_manager", "bug_fix_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "created_by": "agent-1"},
            }],
            best_practices=[
                "Run after bug_propagation_create so pending propagations exist to convert into TODOs.",
                "Only propagations with status pending receive a generated TODO; re-run after adding new ones.",
                "Each generated TODO is anchored to the bug_fix and links back to its propagation automatically.",
                "Assign propagations via assigned_to beforehand so generated TODOs inherit the right owner.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_fix_id: str,
        created_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_fix_uuid = uuid.UUID(bug_fix_id)
                pending = list_bug_fix_propagations(conn, bug_fix_uuid=bug_fix_uuid, status="pending")
                generated: list[dict[str, Any]] = []
                for propagation in pending:
                    anchor = PrimaryAnchor(anchor_type="bug_fix", ref_id=propagation.bug_fix_uuid)
                    todo = create_todo(
                        conn,
                        title=f"Propagation action: {propagation.action}",
                        description=(
                            f"Downstream action '{propagation.action}' required for impact "
                            f"{propagation.impact_uuid} following bug fix {propagation.bug_fix_uuid}."
                        ),
                        kind="task",
                        priority_nice=0,
                        created_by=created_by,
                        anchor=anchor,
                        assigned_to=propagation.assigned_to,
                    )
                    updated = update_bug_fix_propagation(
                        conn,
                        propagation.propagation_uuid,
                        changed_by=created_by,
                        linked_todo_uuid=todo.todo_uuid,
                    )
                    generated.append({"propagation_id": str(updated.propagation_uuid), "todo_id": str(todo.todo_uuid)})
                return SuccessResult(data={"generated": generated})
        except Exception as exc:
            return map_exception(exc)
