"""Command: plan_status — read-only dashboard for one plan."""

from typing import ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_status_metadata import get_plan_status_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate import run_gate
from plan_manager.views.dependency_graph import load_steps


class PlanStatusCommand(Command):
    """Return the read-only dashboard for one resolved plan."""

    name: ClassVar[str] = "plan_status"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return the dashboard for one plan: counts, gate, and scoring."
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the machine-readable input schema for plan_status.

        Returns:
            dict: JSON-schema-like dict with required "plan" (string:
                uuid or name).
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier: either the plan UUID or its unique name.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for plan_status.

        Returns:
            dict: Metadata dictionary from get_plan_status_metadata(cls).
        """
        return get_plan_status_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate plan_status parameters (schema layer only).

        Args:
            params: Raw parameters as received by the adapter.

        Returns:
            dict: The parameters unchanged (after base validation); plan
                resolution failures are raised by resolve_plan in
                execute.
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        """Assemble the plan dashboard: counts, gate verdict, and scoring.

        Args:
            **kwargs: Validated parameters: "plan" (str, uuid or name).

        Returns:
            SuccessResult | ErrorResult: On success, data has "plan",
                "counts_by_level", "status_distribution", "gate", and
                "scoring". On failure, an ErrorResult produced by
                map_exception (e.g. PLAN_NOT_FOUND or
                EMBEDDINGS_UNAVAILABLE).
        """
        plan = kwargs["plan"]
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                counts_by_level: dict[int, int] = {3: 0, 4: 0, 5: 0}
                status_distribution: dict[str, int] = {}
                for step in nodes.values():
                    if step.level in counts_by_level:
                        counts_by_level[step.level] += 1
                    status_distribution[step.status] = (
                        status_distribution.get(step.status, 0) + 1
                    )
                report, verdict = run_gate(conn, p.uuid)
                gate_part = {
                    "green": report.green,
                    "scope": verdict.scope,
                    "revision_uuid": (
                        str(verdict.revision_uuid)
                        if verdict.revision_uuid is not None
                        else None
                    ),
                }
                if report.green:
                    scoring_part = {
                        "deferred": "plan_score",
                        "reason": (
                            "SemanticIndex scoring is queue-bound and is not "
                            "computed synchronously by plan_status."
                        ),
                    }
                else:
                    findings = [
                        finding
                        for check in report.checks
                        for finding in check.findings
                    ]
                    gate_part["findings_count"] = len(findings)
                    gate_part["top_findings"] = [
                        {
                            "code": finding.check_id,
                            "path": finding.artifact_path,
                            "message": finding.message,
                        }
                        for finding in findings[:5]
                    ]
                    scoring_part = {"refused": "GATE_RED"}
                return SuccessResult(
                    data={
                        "plan": {
                            "uuid": str(p.uuid),
                            "name": p.name,
                            "status": p.status,
                        },
                        "projects": {
                            "count": len(p.project_ids),
                            "project_ids": p.project_ids,
                            "primary_project_id": p.primary_project_id,
                        },
                        "counts_by_level": counts_by_level,
                        "status_distribution": status_distribution,
                        "gate": gate_part,
                        "scoring": scoring_part,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
