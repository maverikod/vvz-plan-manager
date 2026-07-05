"""Command PlanValidateCommand: run the mechanical gate (C-012) as a pure read."""
from __future__ import annotations

from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_validate_metadata import get_plan_validate_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.verify.finding import render_text, render_json
from plan_manager.verify.gate import run_gate
from plan_manager.views.branch import resolve_branch


class PlanValidateCommand(Command):
    """Run the mechanical gate (C-012) over a plan or one branch and report findings."""

    name = "plan_validate"
    version = "1.0.0"
    descr = "Run the mechanical gate over a plan or one branch and report PASS/FAIL findings."
    category = "verification"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for this command.

        :returns: A JSON-schema-shaped dict with keys type, properties,
            required, additionalProperties.
        :rtype: Dict[str, Any]
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to validate.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["plan", "branch"],
                    "default": "plan",
                    "description": "Validation scope: the whole plan or one branch named by its three step ids.",
                },
                "gs_step_id": {
                    "type": "string",
                    "description": "Global step id (e.g. G-005) of the branch. Required when scope is 'branch'.",
                },
                "ts_step_id": {
                    "type": "string",
                    "description": "Tactical step id (e.g. T-009) of the branch. Required when scope is 'branch'.",
                },
                "as_step_id": {
                    "type": "string",
                    "description": "Atomic step id (e.g. A-101) of the branch. Required when scope is 'branch'.",
                },
                "fail_fast": {
                    "type": "boolean",
                    "default": False,
                    "description": "Stop at the first failing check group boundary instead of running all check groups.",
                },
                "format": {
                    "type": "string",
                    "enum": ["text", "json"],
                    "default": "json",
                    "description": "Output format of the rendered report: PASS/FAIL text or machine-checkable JSON.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for this command.

        :returns: The dict produced by get_plan_validate_metadata(cls).
        :rtype: Dict[str, Any]
        """
        return get_plan_validate_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the parameters for this command.

        Calls the platform validator first, then enforces the scope
        selector semantics that the JSON schema cannot express: when scope
        is 'branch', gs_step_id, ts_step_id, and as_step_id must all be
        present and non-empty; when scope is 'plan', all three must be
        absent.

        :param params: Raw parameter dict as received from the platform.
        :type params: Dict[str, Any]
        :returns: The validated (and platform-normalized) parameter dict.
        :rtype: Dict[str, Any]
        :raises ValueError: When the scope selector semantics above are
            violated. This is a platform invalid-params failure, not a
            domain error code.
        """
        params = super().validate_params(params)
        scope = params.get("scope", "plan")
        gs_step_id = params.get("gs_step_id")
        ts_step_id = params.get("ts_step_id")
        as_step_id = params.get("as_step_id")
        if scope == "branch":
            if not gs_step_id or not ts_step_id or not as_step_id:
                raise ValueError(
                    "gs_step_id, ts_step_id, and as_step_id are all required "
                    "and must be non-empty when scope is 'branch'"
                )
        elif scope == "plan":
            if gs_step_id or ts_step_id or as_step_id:
                raise ValueError(
                    "gs_step_id, ts_step_id, and as_step_id must be absent "
                    "when scope is 'plan'"
                )
        return params

    async def execute(self, **kwargs: Any):
        """Run the mechanical gate over the requested scope and return the report.

        :param kwargs: Validated parameters: plan (str, plan identifier),
            scope (str, 'plan' or 'branch', default 'plan'), gs_step_id
            (str | None), ts_step_id (str | None), as_step_id (str | None),
            fail_fast (bool, default False), format (str, 'text' or
            'json', default 'json').
        :type kwargs: Any
        :returns: A SuccessResult with data {green, scope, revision_uuid,
            format, report} on success; an ErrorResult with code
            STEP_NOT_FOUND when scope is 'branch' and the branch cannot be
            resolved; otherwise an ErrorResult produced by map_exception
            for any exception raised while resolving the plan or running
            the gate (in particular PLAN_NOT_FOUND when the plan does not
            resolve).
        :rtype: SuccessResult | ErrorResult
        """
        plan = kwargs["plan"]
        scope = kwargs.get("scope", "plan")
        gs_step_id = kwargs.get("gs_step_id")
        ts_step_id = kwargs.get("ts_step_id")
        as_step_id = kwargs.get("as_step_id")
        fail_fast = kwargs.get("fail_fast", False)
        output_format = kwargs.get("format", "json")
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                branch = None
                if scope == "branch":
                    try:
                        branch = resolve_branch(
                            conn, p.uuid, gs_step_id, ts_step_id, as_step_id
                        )
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                report, verdict = run_gate(
                    conn, p.uuid, branch=branch, fail_fast=fail_fast
                )
                rendered = (
                    render_text(report)
                    if output_format == "text"
                    else render_json(report)
                )
                data = {
                    "green": report.green,
                    "scope": verdict.scope,
                    "revision_uuid": (
                        str(verdict.revision_uuid) if verdict.revision_uuid else None
                    ),
                    "format": output_format,
                    "report": rendered,
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
