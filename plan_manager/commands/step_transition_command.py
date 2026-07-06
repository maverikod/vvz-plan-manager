"""Command: lifecycle transition for one step or a scope of steps."""

from __future__ import annotations

import re
import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.commands.step_transition_metadata import get_step_transition_metadata
from plan_manager.domain.status_model import validate_transition
from plan_manager.domain.step import Step
from plan_manager.cascade.write import step_snapshot
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import get_ref, record_revision
from plan_manager.verify.gate import run_gate
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import load_steps


_GS_RE = re.compile(r"^G-\d{3}$")
_TS_RE = re.compile(r"^G-\d{3}/T-\d{3}$")
_TARGET_STATUSES = ("draft", "ready_for_review", "frozen")


class StepTransitionCommand(Command):
    """Transition one step or a whole scope through the authoring lifecycle."""

    name: ClassVar[str] = "step_transition"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition one step or a scope of steps through the authoring lifecycle."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
                },
                "to_status": {
                    "type": "string",
                    "description": "Target authoring lifecycle status.",
                    "enum": list(_TARGET_STATUSES),
                },
                "step_id": {
                    "type": "string",
                    "description": "Single step to transition, as UUID, canonical path, or unambiguous local step id.",
                },
                "scope": {
                    "type": "string",
                    "description": "Bulk transition scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                },
                "require_green": {
                    "type": "boolean",
                    "description": "When true, freezing requires a green mechanical gate before mutation.",
                    "default": True,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Report the transition set without mutating rows or recording a revision.",
                    "default": False,
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier required when reopening frozen steps.",
                },
            },
            "required": ["plan", "to_status"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        if params.get("step_id") and params.get("scope"):
            raise ValueError("step_id and scope are mutually exclusive")
        scope = params.get("scope")
        if scope is not None and not _valid_scope(scope):
            raise ValueError("scope must be whole_plan, G-NNN, or G-NNN/T-NNN")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(
        self,
        plan: str,
        to_status: str,
        step_id: str | None = None,
        scope: str | None = None,
        require_green: bool = True,
        dry_run: bool = False,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                selected, scope_label = _select_steps(nodes, step_id, scope)
                gate = _unchecked_gate(scope_label, p.head_revision_uuid)
                if to_status == "frozen" and require_green:
                    gate = _run_transition_gate(conn, p.uuid, nodes, selected, scope_label)
                    if not gate["green"]:
                        return domain_error(
                            "GATE_RED",
                            "mechanical gate is red for transition scope",
                            {"gate": gate},
                        )

                transitioned, skipped = _plan_transitions(nodes, selected, to_status)
                if any(item["from"] == "frozen" and item["to"] != "frozen" for item in transitioned):
                    if cascade_uuid is None:
                        return domain_error(
                            "CASCADE_REQUIRED",
                            "cascade_uuid is required to reopen frozen steps",
                        )
                    parsed_cascade_uuid = uuid.UUID(cascade_uuid)
                    try:
                        cascade = check_admission(
                            conn, p.uuid, "step", selected[0].uuid, parsed_cascade_uuid
                        )
                    except CascadeError as exc:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                else:
                    parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid else None
                    cascade = None
                    if parsed_cascade_uuid is not None:
                        try:
                            cascade = check_admission(
                                conn, p.uuid, "step", selected[0].uuid, parsed_cascade_uuid
                            )
                        except CascadeError as exc:
                            return domain_error("CASCADE_CONFLICT", str(exc))

                revision_uuid: uuid.UUID | None = None
                if transitioned and not dry_run:
                    for item in transitioned:
                        conn.execute(
                            "UPDATE step SET status = %s WHERE uuid = %s",
                            (item["to"], uuid.UUID(item["uuid"])),
                        )
                    changes = [
                        (
                            uuid.UUID(item["uuid"]),
                            step_snapshot(nodes[uuid.UUID(item["uuid"])], item["to"]),
                        )
                        for item in transitioned
                    ]
                    if cascade is not None:
                        parent = get_ref(conn, p.uuid, cascade.name)
                        revision_uuid = record_revision(
                            conn,
                            p.uuid,
                            "api",
                            f"step_transition: {scope_label} -> {to_status}",
                            changes,
                            parent,
                            ref_name=cascade.name,
                        )
                    else:
                        revision_uuid = record_revision(
                            conn,
                            p.uuid,
                            "api",
                            f"step_transition: {scope_label} -> {to_status}",
                            changes,
                            p.head_revision_uuid,
                            ref_name=None,
                        )

                return SuccessResult(
                    data={
                        "transitioned": transitioned,
                        "skipped": skipped,
                        "gate": gate,
                        "revision_uuid": str(revision_uuid) if revision_uuid else None,
                        "dry_run": dry_run,
                    }
                )
        except DomainCommandError as exc:
            return domain_error(exc.code, exc.message, exc.details)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_step_transition_metadata(cls)


def _valid_scope(scope: str) -> bool:
    return scope == "whole_plan" or bool(_GS_RE.match(scope) or _TS_RE.match(scope))


def _select_steps(
    nodes: dict[uuid.UUID, Step],
    step_id: str | None,
    scope: str | None,
) -> tuple[list[Step], str]:
    if step_id is not None:
        step = resolve_step_ref(nodes, step_id)
        return [step], canonical_step_path(nodes, step)

    scope_label = scope or "whole_plan"
    if not _valid_scope(scope_label):
        raise DomainCommandError("INVALID_SCOPE", "scope must be whole_plan, G-NNN, or G-NNN/T-NNN")
    if scope_label == "whole_plan":
        selected = list(nodes.values())
    else:
        selected = [
            step
            for step in nodes.values()
            if canonical_step_path(nodes, step) == scope_label
            or canonical_step_path(nodes, step).startswith(f"{scope_label}/")
        ]
    if not selected:
        raise DomainCommandError("STEP_NOT_FOUND", f"scope not found: {scope_label}")
    return sorted(selected, key=lambda step: (step.level, canonical_step_path(nodes, step))), scope_label


def _transition_path(current: str, target: str, is_atomic_step: bool) -> list[tuple[str, str]]:
    if current == target:
        return []
    if current == "draft" and target == "frozen":
        validate_transition("draft", "ready_for_review", is_atomic_step=is_atomic_step, via_cascade=False)
        validate_transition("ready_for_review", "frozen", is_atomic_step=is_atomic_step, via_cascade=False)
        return [("draft", "ready_for_review"), ("ready_for_review", "frozen")]
    if current == "frozen" and target == "draft":
        return [("frozen", "draft")]
    validate_transition(current, target, is_atomic_step=is_atomic_step, via_cascade=False)
    return [(current, target)]


def _plan_transitions(
    nodes: dict[uuid.UUID, Step],
    selected: list[Step],
    to_status: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transitioned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    illegal: list[dict[str, Any]] = []
    for step in selected:
        path = canonical_step_path(nodes, step)
        if step.status == to_status:
            skipped.append(
                {
                    "uuid": str(step.uuid),
                    "step_id": step.step_id,
                    "path": path,
                    "from": step.status,
                    "reason": "already_at_target",
                }
            )
            continue
        try:
            _transition_path(step.status, to_status, is_atomic_step=(step.level == 5))
        except Exception as exc:
            illegal.append(
                {
                    "uuid": str(step.uuid),
                    "step_id": step.step_id,
                    "path": path,
                    "from": step.status,
                    "to": to_status,
                    "reason": str(exc),
                }
            )
            continue
        transitioned.append(
            {
                "uuid": str(step.uuid),
                "step_id": step.step_id,
                "path": path,
                "from": step.status,
                "to": to_status,
            }
        )
    if illegal:
        raise DomainCommandError(
            "INVALID_TRANSITION",
            "illegal status transition in selected scope",
            {"illegal": illegal},
        )
    return transitioned, skipped


def _unchecked_gate(scope_label: str, head_revision_uuid: uuid.UUID | None) -> dict[str, Any]:
    return {
        "green": None,
        "scope": scope_label,
        "revision_uuid": str(head_revision_uuid) if head_revision_uuid else None,
        "required": False,
        "checked": False,
    }


def _run_transition_gate(
    conn: Any,
    plan_uuid: uuid.UUID,
    nodes: dict[uuid.UUID, Step],
    selected: list[Step],
    scope_label: str,
) -> dict[str, Any]:
    if scope_label == "whole_plan":
        report, verdict = run_gate(conn, plan_uuid)
        return {
            "green": report.green,
            "scope": scope_label,
            "revision_uuid": str(verdict.revision_uuid) if verdict.revision_uuid else None,
            "required": True,
            "checked": True,
            "finding_count": _finding_count(report),
        }

    atomics = [step for step in selected if step.level == 5]
    if not atomics:
        return {
            "green": False,
            "scope": scope_label,
            "revision_uuid": None,
            "required": True,
            "checked": True,
            "finding_count": 1,
            "reason": "scope contains no atomic steps",
        }

    green = True
    finding_count = 0
    revision_uuid = None
    for atomic in atomics:
        ts = nodes.get(atomic.parent_step_uuid)
        gs = nodes.get(ts.parent_step_uuid) if ts is not None else None
        if ts is None or gs is None:
            green = False
            finding_count += 1
            continue
        report, verdict = run_gate(
            conn,
            plan_uuid,
            branch=Branch(plan_uuid=plan_uuid, gs=gs, ts=ts, atomic=atomic, hrs_slice=[]),
        )
        green = green and report.green
        finding_count += _finding_count(report)
        revision_uuid = verdict.revision_uuid
    return {
        "green": green,
        "scope": scope_label,
        "revision_uuid": str(revision_uuid) if revision_uuid else None,
        "required": True,
        "checked": True,
        "finding_count": finding_count,
        "branch_count": len(atomics),
    }


def _finding_count(report: Any) -> int:
    return sum(len(check.findings) for check in report.checks)
