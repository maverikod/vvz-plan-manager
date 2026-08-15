"""Shared logic for the step dependency command family (C-005/C-009).

Step dependencies are the real top-level ``depends_on`` column, never
``fields.depends_on``. The dependency graph (C-009) resolves each entry as a
*sibling* reference: a step_id at the same level under the same parent. So a
dependency is only valid between siblings (GS->GS, TS->TS under one GS,
AS->AS under one TS); a cross-level or cross-parent reference is refused with
INVALID_DEPENDENCY_SCOPE. This module centralizes reference resolution, scope
and self-dependency checks, batch change planning, and the admission+revision
write path so every step_dependency_* command shares one implementation.

The rendering/formatting and simulation helpers (bare-ref rendering,
dependents lookup, cycle detection, before/after execution-order/wave
projection, same-file admission) live in the sibling module
``step_dependency_sim`` and are re-exported below unchanged so every
step_dependency_* command keeps importing them from here.
"""

from __future__ import annotations

import uuid
from typing import Any

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import step_snapshot
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_dependency_sim import (
    SameFileConflict,
    dependents_paths,
    detect_cycle,
    execution_order_paths,
    parallel_wave_paths,
    render_depends,
    render_same_file_conflicts,
    same_file_admission,
    same_file_conflicts,
    simulate,
)
from plan_manager.commands.step_ref import (
    canonical_step_path,
    canonical_step_paths,
    resolve_step_ref,
)
from plan_manager.domain.step import STEP_ID_PATTERNS, Step
from plan_manager.domain.step_store import get_step, update_step_depends_on
from plan_manager.storage.version_store import get_ref, record_revision
from plan_manager.verify.verdict import current_head_revision
from plan_manager.views.dependency_graph import load_steps

__all__ = [
    "SameFileConflict",
    "dependents_paths",
    "detect_cycle",
    "execution_order_paths",
    "parallel_wave_paths",
    "render_depends",
    "render_same_file_conflicts",
    "same_file_admission",
    "same_file_conflicts",
    "simulate",
    "resolve_target",
    "resolve_dependency_bare",
    "compute_op_list",
    "plan_changes",
    "persist_changes",
    "head_revision_str",
]


# ---------------------------------------------------------------------------
# Reference resolution and scope checks
# ---------------------------------------------------------------------------


def resolve_target(nodes: dict[uuid.UUID, Step], ref: str) -> Step:
    """Resolve the step that receives (or owns) the dependency edit."""
    return resolve_step_ref(nodes, ref)


def _find_sibling(nodes: dict[uuid.UUID, Step], target: Step, bare: str) -> Step | None:
    for step in nodes.values():
        if (
            step.parent_step_uuid == target.parent_step_uuid
            and step.level == target.level
            and step.step_id == bare
        ):
            return step
    return None


def resolve_dependency_bare(
    nodes: dict[uuid.UUID, Step], target: Step, ref: str
) -> str:
    """Resolve a dependency reference to its stored depends_on representation.

    Accepts a UUID, canonical path, or bare step_id. Legacy sibling
    dependencies keep storing the bare sibling ``step_id``. Explicit
    cross-branch atomic dependencies are stored as canonical step paths.

    Raises:
        DomainCommandError: DEPENDENCY_STEP_NOT_FOUND when the reference does
            not resolve, AMBIGUOUS_STEP_ID when a bare id is ambiguous,
            SELF_DEPENDENCY when it resolves to the target, and
            INVALID_DEPENDENCY_SCOPE when it is outside the supported scope.
    """
    dep = resolve_step_ref(nodes, ref, not_found_code="DEPENDENCY_STEP_NOT_FOUND")
    if dep.uuid == target.uuid:
        raise DomainCommandError(
            "SELF_DEPENDENCY",
            f"a step cannot depend on itself: {canonical_step_path(nodes, target)}",
            {"step": canonical_step_path(nodes, target)},
        )
    if dep.parent_step_uuid == target.parent_step_uuid and dep.level == target.level:
        return dep.step_id
    if dep.level == target.level == 5:
        return canonical_step_path(nodes, dep)
    if dep.level != target.level:
        raise DomainCommandError(
            "INVALID_DEPENDENCY_SCOPE",
            "a dependency must stay on the same step level; only atomic "
            "steps admit cross-branch dependencies outside one parent scope",
            {
                "step": canonical_step_path(nodes, target),
                "dependency": canonical_step_path(nodes, dep),
            },
        )
    raise DomainCommandError(
        "INVALID_DEPENDENCY_SCOPE",
        "a non-sibling dependency is allowed only between atomic steps; "
        "global and tactical steps remain sibling-scoped",
        {
            "step": canonical_step_path(nodes, target),
            "dependency": canonical_step_path(nodes, dep),
        },
    )


def _resolve_for_remove(
    nodes: dict[uuid.UUID, Step], target: Step, ref: str, current: list[str]
) -> str:
    """Like resolve_dependency_bare but tolerant of a dangling bare id.

    Removal must stay usable even when the referenced sibling no longer
    exists: a stale stored reference already present in ``current`` is returned
    as-is so it can still be cleared.
    """
    try:
        return resolve_dependency_bare(nodes, target, ref)
    except DomainCommandError as exc:
        if exc.code == "DEPENDENCY_STEP_NOT_FOUND" and ref in current:
            return ref
        if exc.code == "DEPENDENCY_STEP_NOT_FOUND" and STEP_ID_PATTERNS[target.level].match(ref):
            return ref
        raise


def _dedup_preserve(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def compute_op_list(
    nodes: dict[uuid.UUID, Step],
    target: Step,
    current: list[str],
    op: str,
    refs: list[str],
) -> list[str]:
    """Return the new bare depends_on list after applying one operation."""
    if op == "clear":
        return []
    if op == "set":
        return _dedup_preserve(
            [resolve_dependency_bare(nodes, target, r) for r in refs]
        )
    if op == "add":
        new = list(current)
        for r in refs:
            bare = resolve_dependency_bare(nodes, target, r)
            if bare not in new:
                new.append(bare)
        return new
    if op == "remove":
        new = list(current)
        for r in refs:
            bare = _resolve_for_remove(nodes, target, r, new)
            new = [d for d in new if d != bare]
        return new
    raise DomainCommandError(
        "INVALID_DEPENDENCY_SCOPE", f"unknown dependency operation: {op!r}"
    )


# ---------------------------------------------------------------------------
# Batch change planning
# ---------------------------------------------------------------------------


def plan_changes(
    nodes: dict[uuid.UUID, Step], changes: list[dict[str, Any]]
) -> dict[uuid.UUID, list[str]]:
    """Fold a list of {op, step_id, depends_on?} into per-step new lists.

    Operations compose in order on a working copy, so several edits to one
    step accumulate. Returns only the steps whose list actually changes.
    """
    working: dict[uuid.UUID, list[str]] = {}
    for change in changes:
        op = change["op"]
        target = resolve_target(nodes, change["step_id"])
        refs = change.get("depends_on") or []
        if not isinstance(refs, list):
            raise DomainCommandError(
                "INVALID_DEPENDENCY_SCOPE",
                "depends_on must be an array of step references for this op",
                {"op": op},
            )
        current = working.get(target.uuid, list(target.depends_on))
        working[target.uuid] = compute_op_list(nodes, target, current, op, refs)
    return {
        step_uuid: deps
        for step_uuid, deps in working.items()
        if deps != list(nodes[step_uuid].depends_on)
    }


# ---------------------------------------------------------------------------
# Admission + revision write (one revision for the whole change set)
# ---------------------------------------------------------------------------


def persist_changes(
    conn,
    plan,
    new_by_uuid: dict[uuid.UUID, list[str]],
    cascade_uuid: str | None,
    message: str,
) -> uuid.UUID:
    """Admit and write the dependency change set as one revision.

    Mirrors the step_update admission regime: every target must be directly
    mutable (draft/ready_for_review, not frozen at or below) for direct mode,
    or admitted under the given open cascade. A depends_on edit is sibling
    ordering metadata and does not invalidate any descendant, so no
    needs_review propagation is applied.

    Raises:
        DomainCommandError: CASCADE_CONFLICT, FROZEN_ARTIFACT, or
            CASCADE_REQUIRED per the admission rule (C-016/C-007).
    """
    parsed = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
    nodes = load_steps(conn, plan.uuid)
    rec = None
    for target_uuid in new_by_uuid:
        try:
            rec = check_admission(conn, plan.uuid, "step", target_uuid, parsed)
        except CascadeError as exc:
            if cascade_uuid is not None:
                raise DomainCommandError("CASCADE_CONFLICT", str(exc))
            if frozen_at_or_below(nodes, target_uuid):
                raise DomainCommandError("FROZEN_ARTIFACT", str(exc))
            raise DomainCommandError("CASCADE_REQUIRED", str(exc))
    for target_uuid, deps in new_by_uuid.items():
        update_step_depends_on(conn, target_uuid, deps)
    changes = []
    for target_uuid in new_by_uuid:
        patched = get_step(conn, target_uuid)
        changes.append((target_uuid, step_snapshot(patched, patched.status)))
    if rec is not None:
        parent = get_ref(conn, plan.uuid, rec.name)
        ref_name = rec.name
    else:
        parent = plan.head_revision_uuid
        ref_name = None
    # Bug fa15d288: the change set is exactly the steps whose depends_on was
    # rewritten; no other step's context can depend on it.
    return record_revision(
        conn, plan.uuid, "api", message, changes, parent, ref_name,
        carry_forward_paths=canonical_step_paths(nodes, list(new_by_uuid)),
        cascade_uuid=rec.uuid if rec is not None else None,
    )


def head_revision_str(conn, plan) -> str | None:
    """Current head revision as a string, for no-op idempotent responses."""
    head = current_head_revision(conn, plan.uuid)
    return str(head) if head else None
