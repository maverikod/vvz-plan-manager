"""Command: surface the TODO-derived portion of the unified runtime work queue (C-029, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.work_queue import build_unified_queue
from plan_manager.runtime.work_item import WorkKind, ResourceAvailability


class TodoQueueCommand(Command):
    name: ClassVar[str] = "todo_queue"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Surface the TODO-derived portion of the unified runtime work queue."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "available_models": {"type": "array", "items": {"type": "string"}, "description": "Model identifiers currently available (bare model name and/or provider/model form)."},
                "runtime_available": {"type": "boolean", "description": "Whether the runtime executor is currently available (default true)."},
                "vast_available": {"type": "boolean", "description": "Whether the Vast runtime is currently available (default true)."},
                "locked_files": {"type": "array", "items": {"type": "string"}, "description": "Project-relative file paths currently locked."},
                "locked_projects": {"type": "array", "items": {"type": "string"}, "description": "Project-id strings currently locked."},
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "available_models": {"description": "Model identifiers currently available.", "type": "array", "required": False},
            "runtime_available": {"description": "Whether the runtime executor is currently available (default true).", "type": "boolean", "required": False},
            "vast_available": {"description": "Whether the Vast runtime is currently available (default true).", "type": "boolean", "required": False},
            "locked_files": {"description": "Project-relative file paths currently locked.", "type": "array", "required": False},
            "locked_projects": {"description": "Project-id strings currently locked.", "type": "array", "required": False},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The ordered list of TODO-derived WorkItem payloads."}},
            [{"description": "Fetch the TODO-derived queue with default availability.", "command": {}}],
            best_practices=[
                "Only TODOs with status in open, ready, in_progress, blocked are ever surfaced — resolved/closed/cancelled items never appear here, and there is no override to include them.",
                "The queue is computed by building the FULL unified runtime queue (AS-ready items, bugs, fixes, propagations, verifications, reviews, escalations) and then filtering to work_kind==todo — ordering and pausing reflect cross-kind priority, not a todo-only recomputation.",
                "runtime_available and vast_available both default to True when omitted; pass explicit false to simulate unavailability rather than omitting the flag.",
                "available_models/locked_files/locked_projects default to empty — by default no model is considered available and no locks are held; this command never probes actual runtime state, it only orders against the availability facts you supply.",
                "Read-only: it never mutates plan truth or TODO records, it only reads and orders them.",
            ],
        )

    async def execute(
        self,
        available_models: list[str] | None = None,
        runtime_available: bool | None = None,
        vast_available: bool | None = None,
        locked_files: list[str] | None = None,
        locked_projects: list[str] | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                availability = ResourceAvailability(
                    available_models=frozenset(available_models) if available_models else frozenset(),
                    runtime_available=runtime_available if runtime_available is not None else True,
                    vast_available=vast_available if vast_available is not None else True,
                    locked_files=frozenset(locked_files) if locked_files else frozenset(),
                    locked_projects=frozenset(locked_projects) if locked_projects else frozenset(),
                )
                items = build_unified_queue(conn, as_ready=[], availability=availability)
                todo_items = [it for it in items if it.work_kind == WorkKind.TODO.value]
                return SuccessResult(data={"queue": [it.to_payload() for it in todo_items]})
        except Exception as exc:
            return map_exception(exc)
