"""Command: add one dependency edge to a step's top-level depends_on."""
from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_dependency_add_metadata import (
    get_step_dependency_add_metadata,
)
from plan_manager.commands.step_dependency_ops import (
    detect_cycle,
    head_revision_str,
    persist_changes,
    render_depends,
    resolve_dependency_bare,
    resolve_target,
)
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class StepDependencyAddCommand(Command):
    """Add one sibling dependency edge to a step, idempotently."""

    name: ClassVar[str] = "step_dependency_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Add one sibling dependency to a step's top-level depends_on; idempotent, "
        "cycle-safe, and admitted under the step mutation regime."
    )
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
                "step_id": {
                    "type": "string",
                    "description": "Step that receives the dependency (canonical path, bare id, or UUID).",
                },
                "depends_on": {
                    "type": "string",
                    "description": "Sibling step that must run before step_id (canonical path, bare id, or UUID).",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade to admit the mutation under; omit for direct-mode on a non-frozen step.",
                },
            },
            "required": ["plan", "step_id", "depends_on"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_dependency_add_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            step_id = kwargs["step_id"]
            depends_on = kwargs["depends_on"]
            cascade_uuid = kwargs.get("cascade_uuid")
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_target(nodes, step_id)
                bare = resolve_dependency_bare(nodes, target, depends_on)
                current = list(target.depends_on)
                already_present = bare in current
                if already_present:
                    new = current
                    revision = None
                else:
                    new = current + [bare]
                    cycle = detect_cycle(nodes, {target.uuid: new})
                    if cycle:
                        raise DomainCommandError(
                            "DEPENDENCY_CYCLE",
                            "Dependency change would create a cycle.",
                            {"path": canonical_step_path(nodes, target), "cycle": cycle},
                        )
                    revision = persist_changes(
                        conn, p, {target.uuid: new}, cascade_uuid,
                        f"step_dependency_add: {target.step_id} -> {bare}",
                    )
                data = {
                    "step": canonical_step_path(nodes, target),
                    "depends_on": render_depends(nodes, target, new),
                    "added": render_depends(nodes, target, [bare])[0],
                    "already_present": already_present,
                    "revision_uuid": str(revision) if revision is not None else head_revision_str(conn, p),
                }
                return SuccessResult(data=data)
        except DomainCommandError as exc:
            return domain_error(exc.code, exc.message, exc.details)
        except Exception as exc:
            return map_exception(exc)
