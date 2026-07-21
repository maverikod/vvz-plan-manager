"""Command: dry-run impact of a batch of dependency changes (no mutation)."""
from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_dependency_ops import (
    detect_cycle,
    execution_order_paths,
    parallel_wave_paths,
    plan_changes,
    render_same_file_conflicts,
    same_file_admission,
    simulate,
)
from plan_manager.commands.step_dependency_preview_metadata import (
    get_step_dependency_preview_metadata,
)
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class StepDependencyPreviewCommand(Command):
    """Show the graph impact of a batch of dependency changes without mutating."""

    name: ClassVar[str] = "step_dependency_preview"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Dry-run a batch of dependency changes and report validity, cycle risk, "
        "and the before/after execution order and parallel waves."
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
                    "description": "Ordered dependency changes to simulate.",
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
            },
            "required": ["plan", "changes"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_dependency_preview_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return super().validate_params(params)

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            changes = kwargs["changes"]
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                new_by_uuid = plan_changes(nodes, changes)
                changed_steps = sorted(
                    canonical_step_path(nodes, nodes[u]) for u in new_by_uuid
                )
                cycle = detect_cycle(nodes, new_by_uuid) if new_by_uuid else None
                sim = simulate(nodes, new_by_uuid)
                admission = same_file_admission(nodes, sim)
                introduced_findings = render_same_file_conflicts(sim, admission["introduced"])
                data: dict[str, Any] = {
                    "valid": cycle is None and not admission["introduced"],
                    "would_create_cycle": cycle is not None,
                    "changed_steps": changed_steps,
                    "impact": {
                        "execution_order_before": execution_order_paths(nodes),
                        "execution_order_after": execution_order_paths(sim),
                        "parallel_waves_before": parallel_wave_paths(nodes),
                        "parallel_waves_after": parallel_wave_paths(sim),
                    },
                    "same_file_order": {
                        "before_findings": render_same_file_conflicts(nodes, admission["before_conflicts"]),
                        "after_findings": render_same_file_conflicts(sim, admission["after_conflicts"]),
                        "resolved_pairs": render_same_file_conflicts(nodes, admission["resolved"]),
                        "introduced_pairs": introduced_findings,
                    },
                    "findings": [],
                }
                if cycle is not None:
                    data["findings"].append(
                        {
                            "code": "DEPENDENCY_CYCLE",
                            "path": changed_steps[0] if changed_steps else (cycle[0] if cycle else ""),
                            "message": "Dependency change would create a cycle.",
                            "cycle": cycle,
                        }
                    )
                if introduced_findings:
                    data["findings"].append(
                        {
                            "code": "AS_SAME_FILE_ORDER_AMBIGUOUS",
                            "path": changed_steps[0] if changed_steps else "",
                            "message": (
                                "The change would introduce a new same-file writer "
                                "ambiguity; a pre-existing ambiguity elsewhere is not "
                                "itself invalidating."
                            ),
                            "introduced_pairs": introduced_findings,
                        }
                    )
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
