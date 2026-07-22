"""Command: compile and store a standalone context block."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import (
    compile_context,
    resolve_context_revision,
    store_context_block,
)


class ContextCompileCommand(Command):
    name: ClassVar[str] = "context_compile"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compile a typed context block directly from concept ids."
    category: ClassVar[str] = "context"
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
                "concepts": {"type": "array", "items": {"type": "string"}, "description": "MRS concept ids to compile."},
                "child_level": {"type": "integer", "description": "Target child level: 3, 4, or 5. Defaults to 5."},
                "include": {"type": "object", "description": "Optional include flags for standards, field_schema, authoring_template, and step_definition_of (a step reference: UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID)."},
                "revision": {"type": "string", "description": "Optional current head revision UUID."},
                "cascade_uuid": {"type": "string", "description": "Optional open cascade UUID."},
            },
            "required": ["plan", "concepts"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "concepts": {"description": "MRS concept ids to compile.", "type": "array", "required": True},
            "child_level": {"description": "Target child level: 3, 4, or 5. Defaults to 5.", "type": "integer", "required": False},
            "include": {"description": "Optional include flags for baked blocks and step_definition_of (a step reference: UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID).", "type": "object", "required": False},
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "Stored compiled context block with block_id, hash, revision/cascade identity, scope_concepts, and blocks."}},
            [{"description": "Compile atomic authoring context for two concepts.", "command": {"plan": "plan_manager", "concepts": ["C-001", "C-002"], "child_level": 5}}],
        )

    async def execute(
        self,
        plan: str,
        concepts: list[str],
        child_level: int = 5,
        include: dict[str, Any] | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                context_revision = resolve_context_revision(conn, p, revision, cascade_uuid)
                content, scope = compile_context(conn, p.uuid, concepts, child_level, include, "plan")
                record = store_context_block(conn, p.uuid, context_revision, "plan", child_level, "compile", scope, content)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
