"""PlanPromptChainCommand: assemble a scoped, deduplicated prompt chain."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_prompt_chain_metadata import (
    get_plan_prompt_chain_metadata,
)
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate import run_gate
from plan_manager.verify.finding import Report
from plan_manager.views.prompt_chain import (
    assemble_prompt_chain,
    branch_for_atomic,
    normalize_scope,
    normalize_statuses,
    scope_atomic_steps,
)
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.views.dependency_graph import load_steps


def _finding_count(report: Report) -> int:
    return sum(len(check.findings) for check in report.checks)


class PlanPromptChainCommand(Command):
    """Assemble a deterministic prompt-chain artifact for a plan scope."""

    name: ClassVar[str] = "plan_prompt_chain"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Assemble a deterministic, deduplicated prompt-chain artifact for a "
        "gate-green plan scope."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

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
                    "description": "Optional revision UUID; must equal the current plan head.",
                },
                "scope": {
                    "type": "string",
                    "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                },
                "include_statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional statuses allowed for the GS, TS, and AS chain; "
                        "defaults to ['frozen', 'ready_for_review']."
                    ),
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_plan_prompt_chain_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        revision: str | None = None,
        scope: str | None = None,
        include_statuses: list[str] | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if revision is not None:
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
                    return domain_error("STEP_NOT_FOUND", str(exc))
                try:
                    statuses = normalize_statuses(include_statuses)
                except ValueError as exc:
                    return domain_error("INVALID_TRANSITION", str(exc))

                if normalized_scope.label == "whole_plan":
                    report, _verdict = run_gate(conn, p.uuid, branch=None)
                    if not report.green:
                        findings_count = _finding_count(report)
                        return domain_error(
                            "GATE_RED",
                            (
                                "scope whole_plan refused: mechanical gate not green "
                                f"({findings_count} findings)"
                            ),
                            {
                                "scope": "whole_plan",
                                "findings_count": findings_count,
                            },
                        )
                else:
                    nodes = load_steps(conn, p.uuid)
                    paragraphs = list_paragraphs(conn, p.uuid)
                    try:
                        scoped_atomic = scope_atomic_steps(nodes, normalized_scope)
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                    if not scoped_atomic:
                        return domain_error(
                            "STEP_NOT_FOUND",
                            f"no atomic steps found for scope {normalized_scope.label!r}",
                        )
                    for atomic in scoped_atomic:
                        branch = branch_for_atomic(nodes, paragraphs, p.uuid, atomic)
                        report, _verdict = run_gate(conn, p.uuid, branch=branch)
                        if not report.green:
                            findings_count = _finding_count(report)
                            return domain_error(
                                "GATE_RED",
                                (
                                    f"scope {normalized_scope.label} refused: "
                                    "mechanical gate not green "
                                    f"({findings_count} findings)"
                                ),
                                {
                                    "scope": normalized_scope.label,
                                    "findings_count": findings_count,
                                },
                            )

                try:
                    data = assemble_prompt_chain(
                        conn,
                        p.uuid,
                        p.name,
                        p.head_revision_uuid,
                        normalized_scope,
                        statuses,
                    )
                except ValueError as exc:
                    if str(exc) == "cycle detected":
                        return domain_error("CYCLE_DETECTED", str(exc))
                    raise
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
