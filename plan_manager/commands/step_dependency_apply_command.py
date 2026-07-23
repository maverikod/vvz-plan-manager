"""Command: apply a batch of dependency changes atomically as one revision."""
from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_dependency_apply_metadata import (
    get_step_dependency_apply_metadata,
)
from plan_manager.commands.step_dependency_ops import (
    detect_cycle,
    execution_order_paths,
    head_revision_str,
    parallel_wave_paths,
    persist_changes,
    plan_changes,
    render_same_file_conflicts,
    same_file_admission,
    simulate,
)
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class StepDependencyApplyCommand(Command):
    """Apply a batch of dependency changes atomically (or dry-run)."""

    name: ClassVar[str] = "step_dependency_apply"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Apply a batch of dependency changes as one revision, or dry-run them; "
        "all-or-nothing, cycle-safe."
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
                "changes": {
                    "type": "array",
                    "description": "Ordered dependency changes to apply.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "remove", "set", "clear"]},
                            "step_id": {"type": "string"},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["op", "step_id"],
                        "additionalProperties": False,
                    },
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true (default), validate and report impact without mutating.",
                    "default": True,
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade to admit the mutations under; omit for direct-mode on non-frozen steps.",
                },
            },
            "required": ["plan", "changes"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_dependency_apply_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            changes = kwargs["changes"]
            dry_run = kwargs.get("dry_run", True)
            cascade_uuid = kwargs.get("cascade_uuid")
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                new_by_uuid = plan_changes(nodes, changes)
                changed_steps = sorted(
                    canonical_step_path(nodes, nodes[u]) for u in new_by_uuid
                )
                cycle = detect_cycle(nodes, new_by_uuid) if new_by_uuid else None
                if cycle is not None:
                    raise DomainCommandError(
                        "DEPENDENCY_CYCLE",
                        "Dependency change would create a cycle.",
                        {"cycle": cycle, "changed_steps": changed_steps},
                    )
                sim = simulate(nodes, new_by_uuid)
                admission = same_file_admission(nodes, sim)
                if admission["introduced"]:
                    raise DomainCommandError(
                        "AS_SAME_FILE_ORDER_AMBIGUOUS",
                        "Dependency change would introduce a new same-file writer "
                        "ambiguity; a pre-existing ambiguity elsewhere in the graph "
                        "is not itself a rejection reason.",
                        {
                            "changed_steps": changed_steps,
                            "introduced_pairs": render_same_file_conflicts(
                                sim, admission["introduced"]
                            ),
                        },
                    )
                order_before = execution_order_paths(nodes)
                waves_before = parallel_wave_paths(nodes)
                before_findings = render_same_file_conflicts(nodes, admission["before_conflicts"])
                resolved_findings = render_same_file_conflicts(nodes, admission["resolved"])
                if dry_run or not new_by_uuid:
                    revision = None
                    after_nodes = sim
                    applied = not dry_run
                else:
                    revision = persist_changes(
                        conn, p, new_by_uuid, cascade_uuid,
                        f"step_dependency_apply: {len(new_by_uuid)} step(s)",
                    )
                    after_nodes = load_steps(conn, p.uuid)
                    applied = True
                data = {
                    "applied": applied,
                    "dry_run": bool(dry_run),
                    "valid": True,
                    "would_create_cycle": False,
                    "changed_steps": changed_steps,
                    "impact": {
                        "execution_order_before": order_before,
                        "execution_order_after": execution_order_paths(after_nodes),
                        "parallel_waves_before": waves_before,
                        "parallel_waves_after": parallel_wave_paths(after_nodes),
                    },
                    "same_file_order": {
                        "before_findings": before_findings,
                        "after_findings": render_same_file_conflicts(
                            after_nodes, admission["after_conflicts"]
                        ),
                        "resolved_pairs": resolved_findings,
                        "introduced_pairs": [],
                    },
                    "revision_uuid": str(revision) if revision is not None else head_revision_str(conn, p),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
