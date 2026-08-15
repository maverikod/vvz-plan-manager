"""Command: lifecycle transition for one step or a scope of steps."""

from __future__ import annotations

import re
import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.cascade.record import CascadeError, get_open_cascade
from plan_manager.cascade.regime import check_admission
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.commands.step_transition_metadata import get_step_transition_metadata
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.plan_status_sync import derive_plan_status, set_plan_status
from plan_manager.domain.status_model import validate_transition
from plan_manager.domain.step import Step
from plan_manager.cascade.write import step_snapshot
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.external_verification import resolve_external_files_for_plan
from plan_manager.storage.runtime_audit_store import record_runtime_change
from plan_manager.storage.version_store import get_ref, record_revision
from plan_manager.verify.gate import run_gate
from plan_manager.verify.gate_contours import (
    contours_payload,
    empty_partition,
    merge_partitions,
    partition_contours,
    structural_partition,
)
from plan_manager.views.branch import BranchScope
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
    # Bug 96329ae5 fast-fail: this command runs on the adapter's synchronous
    # sync-start path (use_queue=False), which returns fast results — including
    # an immediate INVALID_TRANSITION for an illegal request — to the caller
    # directly and only auto-falls-back to the queue when a slow freeze gate
    # exceeds the sync cap. With use_queue=True the adapter enqueued every call
    # unconditionally (no pre-enqueue validation hook exists), so a definitively
    # illegal transition returned a job id that merely completed_with_error.
    use_queue: ClassVar[bool] = False

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
                "changed_by": {
                    "type": "string",
                    "description": "Actor identity recorded in the audit trail; required only when this call performs a scoped frozen-to-draft transition (subtree unfreeze) and dry_run is false.",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason recorded in the audit trail; required only when this call performs a scoped frozen-to-draft transition (subtree unfreeze) and dry_run is false.",
                },
            },
            "required": ["plan", "to_status"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_transition parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If step_id and scope are both supplied, if
                scope does not match whole_plan/G-NNN/G-NNN/T-NNN, or if
                cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        if params.get("step_id") and params.get("scope"):
            raise InvalidParamsError("step_id and scope are mutually exclusive")
        scope = params.get("scope")
        if scope is not None and not _valid_scope(scope):
            raise InvalidParamsError("scope must be whole_plan, G-NNN, or G-NNN/T-NNN")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            try:
                uuid.UUID(cascade_uuid)
            except ValueError as exc:
                raise InvalidParamsError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
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
        changed_by: str | None = None,
        reason: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                selected, scope_label = _select_steps(nodes, step_id, scope)
                # Fast-fail: validate the requested transition against the
                # lifecycle matrix BEFORE running the (expensive) freeze gate.
                # _plan_transitions raises INVALID_TRANSITION (with per-step
                # legal_targets) as soon as any selected step is illegal, so an
                # illegal request never triggers the gate and, on the
                # synchronous sync-start path, is returned to the caller
                # immediately rather than after a queued gate run.
                transitioned, skipped = _plan_transitions(nodes, selected, to_status)
                gate = _unchecked_gate(scope_label, p.head_revision_uuid)
                if to_status == "frozen" and require_green:
                    gate = _run_transition_gate(
                        conn, p.uuid, nodes, selected, scope_label, p.head_revision_uuid
                    )
                    if not gate["green"]:
                        return domain_error(
                            "GATE_RED",
                            "mechanical gate is red for transition scope",
                            {"gate": gate},
                        )
                is_unfreeze = any(
                    item["from"] == "frozen" and item["to"] != "frozen" for item in transitioned
                )
                if is_unfreeze:
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

                if is_unfreeze and not dry_run:
                    if not changed_by or not changed_by.strip():
                        return domain_error(
                            "RUNTIME_VALIDATION_ERROR",
                            "changed_by must be a non-empty string for a subtree unfreeze",
                        )
                    if not reason or not reason.strip():
                        return domain_error(
                            "RUNTIME_VALIDATION_ERROR",
                            "reason must be a non-empty string for a subtree unfreeze",
                        )

                revision_uuid: uuid.UUID | None = None
                if transitioned and not dry_run:
                    if is_unfreeze:
                        record_runtime_change(
                            conn,
                            plan_uuid=p.uuid,
                            entity_type="plan",
                            entity_id=p.uuid,
                            action="subtree_unfreeze",
                            changed_by=changed_by,
                            change_reason=reason,
                            changed_fields={
                                "scope": scope_label,
                                "unfrozen_steps": [
                                    item["step_id"]
                                    for item in transitioned
                                    if item["from"] == "frozen" and item["to"] != "frozen"
                                ],
                                "head_revision_uuid": (
                                    str(p.head_revision_uuid) if p.head_revision_uuid else None
                                ),
                                # Bug 74ba4313: name the admitting cascade so the
                                # unfreeze side of cascade provenance is auditable.
                                "cascade_uuid": (
                                    str(parsed_cascade_uuid) if parsed_cascade_uuid else None
                                ),
                            },
                        )
                    for item in transitioned:
                        conn.execute(
                            "UPDATE step SET status = %s WHERE uuid = %s",
                            (item["to"], uuid.UUID(item["uuid"])),
                        )
                    # Bug 845b43a8: plan.status is a derived projection of the
                    # WHOLE step tree, not just this transition's scope -- a
                    # scoped freeze/unfreeze can complete or break a full
                    # freeze of the plan, so recompute from every step's
                    # post-transition status (nodes.values(), overridden by
                    # this call's own transitioned targets), not just
                    # `selected`. Atomic with the step UPDATEs above: same
                    # conn/transaction, committed together by db_connection().
                    new_status_by_uuid = {item["uuid"]: item["to"] for item in transitioned}
                    aggregate_status = derive_plan_status(
                        new_status_by_uuid.get(str(step.uuid), step.status)
                        for step in nodes.values()
                    )
                    set_plan_status(conn, p.uuid, aggregate_status)
                    changes = [
                        (
                            uuid.UUID(item["uuid"]),
                            step_snapshot(nodes[uuid.UUID(item["uuid"])], item["to"]),
                        )
                        for item in transitioned
                    ]
                    # Bug fa15d288: a transition writes only status, and the
                    # transitioned set already carries each step's canonical
                    # path, so the blocks outside that set survive the bump.
                    changed_paths = [item["path"] for item in transitioned]
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
                            carry_forward_paths=changed_paths,
                            cascade_uuid=cascade.uuid,
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
                            carry_forward_paths=changed_paths,
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


def _legal_targets(current: str, is_atomic_step: bool) -> list[str]:
    """Return the subset of this command's target statuses legally reachable
    from `current` (including the multi-hop draft -> frozen path), so an
    INVALID_TRANSITION result can tell the caller which statuses are admissible.
    """
    reachable: list[str] = []
    for target in _TARGET_STATUSES:
        if target == current:
            continue
        try:
            _transition_path(current, target, is_atomic_step=is_atomic_step)
        except Exception:
            continue
        reachable.append(target)
    return reachable


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
                    "legal_targets": _legal_targets(step.status, is_atomic_step=(step.level == 5)),
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
    # No gate ran, so there is no report to partition: "contours" is null
    # rather than an invented all-green partition (EIG block G).
    return {
        "green": None,
        "scope": scope_label,
        "revision_uuid": str(head_revision_uuid) if head_revision_uuid else None,
        "required": False,
        "checked": False,
        "contours": None,
    }


def _live_working_revision(
    conn: Any, plan_uuid: uuid.UUID, head_revision_uuid: uuid.UUID | None
) -> uuid.UUID | None:
    """Return the plan's live working-tip revision (bug 1ddea076).

    run_gate itself always scans live table rows regardless of who calls
    it -- there is no separate "base" snapshot it can read instead -- so
    the mechanical gate's green/red verdict already reflects the plan's
    current working state. What was wrong is only the label attached to
    that verdict: run_gate reports ``current_head_revision``, which is
    the plan HEAD and never moves while a cascade is open (the cascade's
    BASE), not the cascade ref's current target (the WORKING TIP) that
    plan_validate_command surfaces as ``tip_revision_uuid``. This
    resolves the same tip plan_validate_command does: the open cascade's
    ref target when a cascade is open, otherwise the plan head.

    Args:
        conn: Open database connection.
        plan_uuid: Identity of the plan.
        head_revision_uuid: The plan's head revision, used verbatim when
            no cascade is open.

    Returns:
        The cascade's tip revision uuid when the plan has an open
        cascade, else `head_revision_uuid` unchanged.
    """
    cascade = get_open_cascade(conn, plan_uuid)
    if cascade is None:
        return head_revision_uuid
    return get_ref(conn, plan_uuid, cascade.name)


def _hrs_slice_for(conn: Any, plan_uuid: uuid.UUID, gs: Step) -> list[Any]:
    """Build a branch's hrs_slice exactly as views.branch.resolve_branch_scope
    does, for a scoped freeze gate run (bug 1ddea076).

    Before this fix, ``_run_transition_gate`` handed the mechanical gate a
    BranchScope with ``hrs_slice=[]`` hardcoded, so
    ``check_parse_sanity_counts`` (verify/gate_structure.py) fired a
    spurious "branch hrs_slice is empty" finding on every scoped
    (non-whole_plan) freeze, independent of whether the plan's actual
    repaired state was green -- unlike plan_validate_command, which
    always resolves the real hrs_slice via resolve_branch_scope. That
    divergence, not any revision selection, is why a scope plan_validate
    reported green could still be refused here with GATE_RED.

    Args:
        conn: Open database connection.
        plan_uuid: Identity of the plan.
        gs: The branch's resolved global (level 3) step.

    Returns:
        The list of Paragraph rows bound to gs.fields["source_labels"],
        in document order, matching resolve_branch_scope's hrs_slice.
    """
    source_labels = gs.fields.get("source_labels", [])
    bare = {label[1:-1] for label in source_labels}
    return [
        paragraph
        for paragraph in list_paragraphs(conn, plan_uuid)
        if paragraph.label is not None and paragraph.label in bare
    ]


def _run_transition_gate(
    conn: Any,
    plan_uuid: uuid.UUID,
    nodes: dict[uuid.UUID, Step],
    selected: list[Step],
    scope_label: str,
    head_revision_uuid: uuid.UUID | None = None,
) -> dict[str, Any]:
    # Bug 1ddea076: report and reason about the plan's live WORKING TIP --
    # the same state plan_validate_command evaluates -- not the plan HEAD,
    # which is the cascade's BASE and never moves while a cascade is open.
    live_revision_uuid = _live_working_revision(conn, plan_uuid, head_revision_uuid)
    # EIG block G: the freeze gate is wired to the live CA file probe like
    # every other run_gate caller. Resolved ONCE and reused for every scoped
    # pass below, so a scope with many atomic steps still makes one CA read.
    external_files, require_verification, _payload = resolve_external_files_for_plan(
        conn, plan_uuid
    )

    if scope_label == "whole_plan":
        report, verdict = run_gate(
            conn,
            plan_uuid,
            external_files=external_files,
            require_project_verification=require_verification,
        )
        return {
            "green": report.green,
            "scope": scope_label,
            "revision_uuid": str(live_revision_uuid) if live_revision_uuid else None,
            "required": True,
            "checked": True,
            "finding_count": _finding_count(report),
            "contours": contours_payload(partition_contours(report)),
        }

    atomics = [step for step in selected if step.level == 5]
    if not atomics:
        return {
            "green": False,
            "scope": scope_label,
            "revision_uuid": str(live_revision_uuid) if live_revision_uuid else None,
            "required": True,
            "checked": True,
            "finding_count": 1,
            "reason": "scope contains no atomic steps",
            # An empty scope is refused before any check runs, so neither
            # gate contour has an observation behind it.
            "contours": None,
        }

    green = True
    finding_count = 0
    partition = empty_partition()
    hrs_slices: dict[uuid.UUID, list[Any]] = {}
    for atomic in atomics:
        ts = nodes.get(atomic.parent_step_uuid)
        gs = nodes.get(ts.parent_step_uuid) if ts is not None else None
        if ts is None or gs is None:
            green = False
            finding_count += 1
            # A broken ancestry is a STRUCTURAL defect counted here rather
            # than by any check: the gate cannot even be scoped to it.
            partition = merge_partitions(partition, structural_partition(1))
            continue
        if gs.uuid not in hrs_slices:
            hrs_slices[gs.uuid] = _hrs_slice_for(conn, plan_uuid, gs)
        report, verdict = run_gate(
            conn,
            plan_uuid,
            # Bug 36414056: run_gate takes a BranchScope; the plain Branch view
            # has no ``depth`` and crashed the freeze gate with AttributeError.
            # Bug 1ddea076: hrs_slice must be resolved the same way
            # resolve_branch_scope resolves it for plan_validate_command,
            # not hardcoded empty (see _hrs_slice_for's docstring).
            branch=BranchScope(
                plan_uuid=plan_uuid,
                depth="as",
                gs=gs,
                ts=ts,
                atomic=atomic,
                hrs_slice=hrs_slices[gs.uuid],
            ),
            external_files=external_files,
            require_project_verification=require_verification,
        )
        green = green and report.green
        finding_count += _finding_count(report)
        partition = merge_partitions(partition, partition_contours(report))
    return {
        "green": green,
        "scope": scope_label,
        "revision_uuid": str(live_revision_uuid) if live_revision_uuid else None,
        "required": True,
        "checked": True,
        "finding_count": finding_count,
        "branch_count": len(atomics),
        # Summed across every scoped pass, so the contours describe the whole
        # transitioned scope rather than its last atomic branch.
        "contours": contours_payload(partition),
    }


def _finding_count(report: Any) -> int:
    return sum(len(check.findings) for check in report.checks)
