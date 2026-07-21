"""Command: compile one common block and per-child specific deltas."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import (
    ContextRevision,
    common_context,
    resolve_context_revision,
    specific_delta,
    store_context_block,
)


class ContextBundleCommand(Command):
    name: ClassVar[str] = "context_bundle"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compile a common context block and child-specific deltas."
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
                "node": {"type": "string", "description": "Parent node path, UUID, local step id, or 'plan'."},
                "child_level": {"type": "integer", "description": "Level of children being authored: 3, 4, or 5."},
                "children": {"type": "array", "description": "Children array; each item has ref and concepts."},
                "shared_concepts": {"type": "array", "items": {"type": "string"}, "description": "Optional shared concept scope."},
                "revision": {"type": "string", "description": "Optional current head revision UUID."},
                "cascade_uuid": {"type": "string", "description": "Optional open cascade UUID."},
            },
            "required": ["plan", "node", "child_level", "children"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "node": {"description": "Parent node path, UUID, local step id, or 'plan'.", "type": "string", "required": True},
            "child_level": {"description": "Level of children being authored: 3, 4, or 5.", "type": "integer", "required": True},
            "children": {"description": "Children array; each item has ref and concepts.", "type": "array", "required": True},
            "shared_concepts": {"description": "Optional common scope.", "type": "array", "required": False},
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "Bundle payload containing the stored common block and ordered child delta blocks."}},
            [{"description": "Compile common and specific context for tactical children.", "command": {"plan": "plan_manager", "node": "G-002", "child_level": 4, "children": [{"ref": "session-core", "concepts": ["C-010"]}]}}],
        )

    async def execute(
        self,
        plan: str,
        node: str,
        child_level: int,
        children: list[dict[str, Any]],
        shared_concepts: list[str] | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                context_revision = resolve_context_revision(conn, p, revision, cascade_uuid)
                node_path, scope, content = common_context(conn, p.uuid, node, child_level, shared_concepts)
                common = store_context_block(conn, p.uuid, context_revision, node_path, child_level, "common", scope, content)
                child_payloads = []
                inherited_revision = ContextRevision(common.revision_uuid, common.cascade_uuid)
                for child in children:
                    child_scope, delta = specific_delta(conn, p.uuid, common, list(child.get("concepts", [])))
                    record = store_context_block(
                        conn,
                        p.uuid,
                        inherited_revision,
                        node_path,
                        child_level,
                        "specific",
                        child_scope,
                        delta,
                        common.block_id,
                    )
                    payload = record.to_payload()
                    payload["ref"] = child.get("ref")
                    child_payloads.append(payload)
                common_payload = common.to_payload()
                common_payload["common_block_id"] = common_payload["block_id"]
                return SuccessResult(data={"common": common_payload, "children": child_payloads})
        except Exception as exc:
            return map_exception(exc)
