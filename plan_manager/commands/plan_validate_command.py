"""Command PlanValidateCommand: run the mechanical gate (C-012) as a pure read."""
from __future__ import annotations

import uuid
from typing import Any, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.cascade.record import get_open_cascade
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_validate_metadata import get_plan_validate_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.ca_files_probe import ExternalFilesProbe, list_project_files_probe
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.storage.version_store import get_ref
from plan_manager.verify.finding import render_text, render_json
from plan_manager.verify.gate import run_gate
from plan_manager.views.branch import resolve_branch_scope


def resolve_external_files(plan: Any) -> tuple[ExternalFilesProbe | None, bool, dict[str, Any]]:
    """Fetch the live CA file inventory of ``plan``'s PRIMARY project (EIG block F).

    plan_validate is the only ``run_gate`` caller wired to the probe in this
    block; step_transition, cascade close, plan_prompt_chain, plan_status and
    the scoring index deliberately stay probe-less (block-G residual), so
    their gate runs keep exactly their pre-block-F behaviour.

    Returns ``(probe, require_project_verification, payload)`` where
    ``payload`` is the additive ``external_verification`` response key:

    - ``{"status": "skipped", "reason": "no_primary_project"}`` when the plan
      has no primary project binding (``plan.primary_project_id``), or that
      binding is not a UUID. No probe is fetched and ``probe`` is None, so
      every block-F check stays silent -- a plan bound to nothing is never
      redded for it.
    - ``{"status": "unavailable", "reason": "ca_unreachable"}`` when the
      probe was attempted but the listing could not be read.
    - ``{"status": "ok", "reason": None}`` when the full inventory was read.

    Never raises: ``list_project_files_probe`` already folds every transport
    failure into an unavailable probe, and a runtime whose configuration is
    not initialized (``app_config`` raising) is treated the same way -- the
    gate must degrade, never fail a read-only validate call. ``getattr`` is
    used for ``primary_project_id`` so a caller-supplied plan projection that
    predates project bindings is a "skipped", not an AttributeError.
    """
    primary = getattr(plan, "primary_project_id", None)
    if not primary:
        return None, False, {"status": "skipped", "reason": "no_primary_project"}
    try:
        project_id = uuid.UUID(str(primary))
        config = app_config()
        probe = list_project_files_probe(
            ca_url=config.code_analysis_url,
            project_id=project_id,
            timeout=config.code_analysis_timeout,
            cert=config.code_analysis_cert,
            key=config.code_analysis_key,
            ca=config.code_analysis_ca,
        )
        require = config.require_project_verification
    except ValueError:
        return None, False, {"status": "skipped", "reason": "no_primary_project"}
    except Exception:
        probe = ExternalFilesProbe(available=False, reason="ca_unreachable")
        require = False
    if probe.available:
        return probe, require, {"status": "ok", "reason": None}
    return probe, require, {"status": "unavailable", "reason": probe.reason}


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
                    "description": (
                        "Validation scope: the whole plan, or one hierarchical branch "
                        "selected by gs_step_id alone (whole GS subtree), gs_step_id + "
                        "ts_step_id (that TS subtree), or all three (one atomic branch)."
                    ),
                },
                "gs_step_id": {
                    "type": "string",
                    "description": (
                        "Global step id (e.g. G-005) of the branch. Required (and "
                        "non-empty) whenever scope is 'branch' -- selects that GS's "
                        "whole subtree unless narrowed by ts_step_id/as_step_id below. "
                        "Must be absent when scope is 'plan'."
                    ),
                },
                "ts_step_id": {
                    "type": "string",
                    "description": (
                        "Tactical step id (e.g. T-009): optional narrowing of the "
                        "gs_step_id subtree to one TS subtree. Requires gs_step_id. "
                        "Required whenever as_step_id is given (skipping this level is "
                        "rejected). Must be absent when scope is 'plan'."
                    ),
                },
                "as_step_id": {
                    "type": "string",
                    "description": (
                        "Atomic step id (e.g. A-101): optional narrowing to exactly "
                        "one atomic branch. Requires both gs_step_id and ts_step_id "
                        "(supplying it without ts_step_id is a rejected skipped-level "
                        "selector). Must be absent when scope is 'plan'."
                    ),
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

        Calls the platform validator first, then enforces the hierarchical
        branch-selector semantics the JSON schema cannot express (bug
        e197b94a): when scope is 'branch', gs_step_id must be present and
        non-empty (it alone selects the whole GS subtree); ts_step_id is
        then optional (present narrows to that TS subtree); as_step_id is
        only valid when ts_step_id is also present (skipping the TS level
        is rejected deterministically). When scope is 'plan', all three
        must be absent.

        :param params: Raw parameter dict as received from the platform.
        :type params: Dict[str, Any]
        :returns: The validated (and platform-normalized) parameter dict.
        :rtype: Dict[str, Any]
        :raises InvalidParamsError: When the scope selector semantics above
            are violated. This is a platform invalid-params failure (JSON-RPC
            -32602), not a domain error code.
        """
        params = super().validate_params(params)
        scope = params.get("scope", "plan")
        gs_step_id = params.get("gs_step_id")
        ts_step_id = params.get("ts_step_id")
        as_step_id = params.get("as_step_id")
        if scope == "branch":
            if not gs_step_id:
                raise InvalidParamsError(
                    "gs_step_id is required and must be non-empty when scope is "
                    "'branch' (it selects the whole GS subtree unless narrowed by "
                    "ts_step_id/as_step_id)"
                )
            if as_step_id and not ts_step_id:
                raise InvalidParamsError(
                    "as_step_id requires ts_step_id when scope is 'branch' "
                    "(skipping the TS level is not allowed)"
                )
        elif scope == "plan":
            if gs_step_id or ts_step_id or as_step_id:
                raise InvalidParamsError(
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
            tip_revision_uuid, cascade_uuid, format, report,
            external_verification} on success (external_verification reports
            whether the CA-backed existence checks could run for this plan --
            see resolve_external_files)
            (tip_revision_uuid/cascade_uuid are populated when the plan has
            an open cascade, null otherwise -- revision_uuid always names
            the last COMMITTED head, a label, not the scanned data: the
            gate always evaluates live state, per bugs 3de7a081/a8c43201);
            an ErrorResult with code STEP_NOT_FOUND when scope is 'branch'
            and the branch scope cannot be resolved (missing step, or a
            ts_step_id/as_step_id that does not belong to its addressed
            parent); otherwise an ErrorResult produced by map_exception for
            any exception raised while resolving the plan or running the
            gate (in particular PLAN_NOT_FOUND when the plan does not
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
                        branch = resolve_branch_scope(
                            conn, p.uuid, gs_step_id, ts_step_id, as_step_id
                        )
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                external_files, require_verification, external_payload = (
                    resolve_external_files(p)
                )
                report, verdict = run_gate(
                    conn,
                    p.uuid,
                    branch=branch,
                    fail_fast=fail_fast,
                    external_files=external_files,
                    require_project_verification=require_verification,
                )
                rendered = (
                    render_text(report)
                    if output_format == "text"
                    else render_json(report)
                )
                open_cascade = get_open_cascade(conn, p.uuid)
                if open_cascade is None:
                    tip_revision_uuid = None
                    cascade_uuid = None
                else:
                    cascade_uuid = str(open_cascade.uuid)
                    tip_revision_uuid = str(
                        get_ref(conn, p.uuid, open_cascade.name)
                    )
                data = {
                    "green": report.green,
                    "scope": verdict.scope,
                    "revision_uuid": (
                        str(verdict.revision_uuid) if verdict.revision_uuid else None
                    ),
                    "tip_revision_uuid": tip_revision_uuid,
                    "cascade_uuid": cascade_uuid,
                    "format": output_format,
                    "report": rendered,
                    "external_verification": external_payload,
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
