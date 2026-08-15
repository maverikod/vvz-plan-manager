"""PlanPromptChainCommand: assemble a scoped, deduplicated prompt chain."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_prompt_chain_metadata import (
    get_plan_prompt_chain_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.external_verification import resolve_external_files_for_plan
from plan_manager.verify.gate import run_gate
from plan_manager.verify.finding import Report
from plan_manager.verify.gate_contours import (
    EXECUTION_CONTOUR_PREFIX,
    contours_payload,
    partition_contours,
    semantic_contour,
)
from plan_manager.views.branch import resolve_branch_scope
from plan_manager.views.prompt_chain import (
    assemble_prompt_chain,
    normalize_scope,
    normalize_role,
    normalize_statuses,
    scope_atomic_steps,
)
from plan_manager.views.dependency_graph import load_steps


def _finding_count(report: Report) -> int:
    return sum(len(check.findings) for check in report.checks)


def _execution_findings(report: Report) -> list[dict[str, str]]:
    """Flatten the execution-contour findings of ``report``, in report order."""
    return [
        {
            "code": finding.check_id,
            "path": finding.artifact_path,
            "message": finding.message,
        }
        for check in report.checks
        if check.check_id.startswith(EXECUTION_CONTOUR_PREFIX)
        for finding in check.findings
    ]


def _gate_refusal(
    report: Report, scope_label: str, diagnostic_override: bool
) -> ErrorResult | None:
    """Decide whether this gate report refuses assembly (EIG block G).

    The three-contour refusal matrix, in order:

    - STRUCTURAL contour red -> ALWAYS refuse with ``GATE_RED``. A plan that
      is not a well-formed authoring artifact cannot produce a meaningful
      prompt chain, and no override exists for that.
    - EXECUTION contour red with the structural contour GREEN -> refuse with
      the distinct code ``EXECUTION_RED`` by default, UNLESS the caller
      passed ``diagnostic_override=true``. The plan is well-formed but its
      execution program is unordered, unclosed, or ungrounded; a diagnostic
      consumer may legitimately want the chain anyway, and the payload then
      says so explicitly (never silently).
    - Both green -> no refusal.

    Returns the ErrorResult to return to the caller, or None to proceed.
    """
    partition = partition_contours(report)
    if not partition["structural"]["green"]:
        findings_count = _finding_count(report)
        return domain_error(
            "GATE_RED",
            (
                f"scope {scope_label} refused: mechanical gate not green "
                f"({findings_count} findings)"
            ),
            {
                "scope": scope_label,
                "findings_count": findings_count,
                "contours": contours_payload(partition),
            },
        )
    if partition["execution"]["green"] or diagnostic_override:
        return None
    execution_count = partition["execution"]["findings_count"]
    return domain_error(
        "EXECUTION_RED",
        (
            f"scope {scope_label} refused: execution-integrity contour not "
            f"green ({execution_count} findings); the plan is structurally "
            "valid but its execution program is not"
        ),
        {
            "scope": scope_label,
            "findings_count": execution_count,
            "contours": contours_payload(partition),
            "top_findings": _execution_findings(report)[:5],
        },
    )


def _diagnostic_block(report: Report, diagnostic_override: bool) -> dict[str, Any]:
    """Build the additive payload keys describing this run's contour state.

    ``contours`` is always present. ``diagnostic_override`` and
    ``execution_findings`` appear ONLY when the override actually admitted a
    red execution contour, so the presence of those keys is itself the signal
    that this artifact was produced past a refusal.
    """
    partition = partition_contours(report)
    block: dict[str, Any] = {
        "contours": contours_payload(
            partition,
            semantic_contour(
                "not_evaluated",
                "plan_prompt_chain runs the mechanical gate only; semantic "
                "completeness is measured by plan_score.",
            ),
        )
    }
    if diagnostic_override and not partition["execution"]["green"]:
        findings = _execution_findings(report)
        block["diagnostic_override"] = True
        block["execution_findings"] = {
            "findings_count": partition["execution"]["findings_count"],
            "top_findings": findings[:5],
        }
    return block


class PlanPromptChainCommand(Command):
    """Assemble a deterministic prompt-chain artifact for a plan scope."""

    name: ClassVar[str] = "plan_prompt_chain"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Assemble a paginated page of the deterministic, deduplicated prompt-chain artifact for a gate-green plan scope."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID).",
                },
                "revision": {
                    "type": "string",
                    "description": "Optional revision UUID; defaults to the current plan head.",
                    "default": "head",
                },
                "scope": {
                    "type": "string",
                    "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                    "default": "whole_plan",
                },
                "role": {
                    "type": "string",
                    "description": "Assembly role selector.",
                    "enum": ["coder", "review", "conscience"],
                    "default": "coder",
                },
                "include_statuses": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["frozen", "ready_for_review"],
                    },
                    "description": (
                        "Optional statuses allowed for the GS, TS, and AS chain; "
                        "defaults to ['frozen', 'ready_for_review']."
                    ),
                    "default": ["frozen", "ready_for_review"],
                },
                "diagnostic_override": {
                    "type": "boolean",
                    "description": (
                        "Proceed even when the execution-integrity contour is "
                        "red (EXECUTION_RED) as long as the structural contour "
                        "is green. The returned payload then carries "
                        "diagnostic_override=true and an execution_findings "
                        "summary; a red STRUCTURAL contour is still refused "
                        "with GATE_RED and is never overridable."
                    ),
                    "default": False,
                },
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_prompt_chain_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        normalized = dict(params)
        normalized.setdefault("revision", "head")
        normalized.setdefault("scope", "whole_plan")
        normalized.setdefault("role", "coder")
        normalized.setdefault("include_statuses", ["frozen", "ready_for_review"])
        normalized.setdefault("diagnostic_override", False)
        return normalized

    async def execute(
        self,
        plan: str,
        revision: str | None = None,
        scope: str | None = None,
        role: str = "coder",
        include_statuses: list[str] | None = None,
        diagnostic_override: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                if revision in {None, "", "head"}:
                    requested_revision = p.head_revision_uuid
                else:
                    try:
                        requested_revision = uuid.UUID(revision)
                    except ValueError:
                        return domain_error(
                            "REVISION_NOT_FOUND",
                            f"revision not found for current head: {revision}",
                        )
                    if requested_revision != p.head_revision_uuid:
                        return domain_error(
                            "REVISION_NOT_FOUND",
                            f"revision not found for current head: {revision}",
                            {
                                "current_head_revision": (
                                    str(p.head_revision_uuid)
                                    if p.head_revision_uuid is not None
                                    else None
                                )
                            },
                        )
                try:
                    normalized_scope = normalize_scope(scope)
                except ValueError as exc:
                    return domain_error("INVALID_SCOPE", str(exc), {"scope": scope})
                try:
                    normalized_role = normalize_role(role)
                except ValueError as exc:
                    return domain_error("INVALID_ROLE", str(exc), {"role": role})
                try:
                    statuses = normalize_statuses(include_statuses)
                except ValueError as exc:
                    return domain_error(
                        "INVALID_STATUS_FILTER",
                        str(exc),
                        {"include_statuses": include_statuses},
                    )

                # EIG block G: this gate run is wired to the live CA file
                # probe like every other run_gate caller; it degrades
                # silently to the pre-block-G verdict when no probe resolves.
                external_files, require_verification, _payload = (
                    resolve_external_files_for_plan(conn, p.uuid)
                )
                if normalized_scope.label == "whole_plan":
                    report, _verdict = run_gate(
                        conn,
                        p.uuid,
                        branch=None,
                        external_files=external_files,
                        require_project_verification=require_verification,
                    )
                    refusal = _gate_refusal(
                        report, "whole_plan", diagnostic_override
                    )
                    if refusal is not None:
                        return refusal
                else:
                    nodes = load_steps(conn, p.uuid)
                    try:
                        scope_atomic_steps(nodes, normalized_scope)
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                    # Bug 4f7fbd43: run the mechanical gate ONCE over the
                    # hierarchical BranchScope (depth "gs" for G-NNN, "ts"
                    # for G-NNN/T-NNN) instead of once per atomic step with
                    # a plain Branch, which run_gate no longer accepts
                    # (scope_steps reads branch.depth; Branch has none).
                    try:
                        branch = resolve_branch_scope(
                            conn,
                            p.uuid,
                            normalized_scope.gs_step_id,
                            normalized_scope.ts_step_id,
                        )
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                    report, _verdict = run_gate(
                        conn,
                        p.uuid,
                        branch=branch,
                        external_files=external_files,
                        require_project_verification=require_verification,
                    )
                    refusal = _gate_refusal(
                        report, normalized_scope.label, diagnostic_override
                    )
                    if refusal is not None:
                        return refusal

                try:
                    data = assemble_prompt_chain(
                        conn,
                        p.uuid,
                        p.name,
                        p.head_revision_uuid,
                        normalized_scope,
                        statuses,
                        normalized_role,
                    )
                except ValueError as exc:
                    if str(exc).startswith("cycle detected"):
                        return domain_error("CYCLE_DETECTED", str(exc))
                    raise
                assembly = data.get("assembly", [])
                total = len(assembly)
                page = assembly[pagination.offset : pagination.offset + pagination.limit]
                used_block_keys: dict[str, list[str]] = {}
                for entry in page:
                    for level, ref in entry.get("use", {}).items():
                        refs = ref if isinstance(ref, list) else [ref]
                        bucket = used_block_keys.setdefault(level, [])
                        for r in refs:
                            if r not in bucket:
                                bucket.append(r)
                data = {
                    key: value
                    for key, value in data.items()
                    if key not in {"assembly", "blocks"}
                }
                data["assembly"] = page
                data["used_block_keys"] = {
                    level: sorted(refs) for level, refs in used_block_keys.items()
                }
                data["total"] = total
                data["limit"] = pagination.limit
                data["offset"] = pagination.offset
                data.update(_diagnostic_block(report, diagnostic_override))
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
