"""Shared logic for the step dependency command family (C-005/C-009).

Step dependencies are the real top-level ``depends_on`` column, never
``fields.depends_on``. The dependency graph (C-009) resolves each entry as a
*sibling* reference: a step_id at the same level under the same parent. So a
dependency is only valid between siblings (GS->GS, TS->TS under one GS,
AS->AS under one TS); a cross-level or cross-parent reference is refused with
INVALID_DEPENDENCY_SCOPE. This module centralizes reference resolution, scope
and self-dependency checks, cycle detection, and the admission+revision write
path so every step_dependency_* command shares one implementation.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import step_snapshot
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.domain.step import STEP_ID_PATTERNS, Step
from plan_manager.domain.step_store import get_step, update_step_depends_on
from plan_manager.storage.version_store import get_ref, record_revision
from plan_manager.verify.verdict import current_head_revision
from plan_manager.views.dependency_graph import (
    build_edges,
    load_steps,
    topological_order,
    waves,
)


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
    """Resolve a dependency reference to the bare sibling step_id it names.

    Accepts a UUID, canonical path, or bare step_id. Enforces that the named
    step is a sibling of ``target`` (same parent, same level) and is not the
    target itself.

    Raises:
        DomainCommandError: DEPENDENCY_STEP_NOT_FOUND when the reference does
            not resolve, AMBIGUOUS_STEP_ID when a bare id is ambiguous,
            SELF_DEPENDENCY when it resolves to the target, and
            INVALID_DEPENDENCY_SCOPE when it is not a sibling of the target.
    """
    dep = resolve_step_ref(nodes, ref, not_found_code="DEPENDENCY_STEP_NOT_FOUND")
    if dep.uuid == target.uuid:
        raise DomainCommandError(
            "SELF_DEPENDENCY",
            f"a step cannot depend on itself: {canonical_step_path(nodes, target)}",
            {"step": canonical_step_path(nodes, target)},
        )
    if dep.parent_step_uuid != target.parent_step_uuid or dep.level != target.level:
        raise DomainCommandError(
            "INVALID_DEPENDENCY_SCOPE",
            "a dependency must reference a sibling step (same parent and level); "
            "cross-level and cross-parent dependencies are not allowed in the MVP",
            {
                "step": canonical_step_path(nodes, target),
                "dependency": canonical_step_path(nodes, dep),
            },
        )
    return dep.step_id


def _resolve_for_remove(
    nodes: dict[uuid.UUID, Step], target: Step, ref: str
) -> str:
    """Like resolve_dependency_bare but tolerant of a dangling bare id.

    Removal must stay usable even when the referenced sibling no longer
    exists: a bare id matching the target level's pattern is returned as-is
    so a stale entry can still be cleared.
    """
    try:
        return resolve_dependency_bare(nodes, target, ref)
    except DomainCommandError as exc:
        if exc.code == "DEPENDENCY_STEP_NOT_FOUND" and STEP_ID_PATTERNS[
            target.level
        ].match(ref):
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
            bare = _resolve_for_remove(nodes, target, r)
            new = [d for d in new if d != bare]
        return new
    raise DomainCommandError(
        "INVALID_DEPENDENCY_SCOPE", f"unknown dependency operation: {op!r}"
    )


# ---------------------------------------------------------------------------
# Rendering (bare step_id -> canonical path) and dependents
# ---------------------------------------------------------------------------


def render_depends(
    nodes: dict[uuid.UUID, Step], target: Step, bares: list[str]
) -> list[str]:
    """Render bare sibling ids as canonical paths for command output."""
    out: list[str] = []
    for bare in bares:
        sibling = _find_sibling(nodes, target, bare)
        out.append(canonical_step_path(nodes, sibling) if sibling else bare)
    return out


def dependents_paths(nodes: dict[uuid.UUID, Step], target: Step) -> list[str]:
    """Canonical paths of sibling steps that depend on ``target``."""
    result: list[str] = []
    for step in nodes.values():
        if (
            step.uuid != target.uuid
            and step.parent_step_uuid == target.parent_step_uuid
            and step.level == target.level
            and target.step_id in step.depends_on
        ):
            result.append(canonical_step_path(nodes, step))
    return sorted(result)


# ---------------------------------------------------------------------------
# Cycle detection and execution-order projection over a simulated graph
# ---------------------------------------------------------------------------


def simulate(
    nodes: dict[uuid.UUID, Step], new_by_uuid: dict[uuid.UUID, list[str]]
) -> dict[uuid.UUID, Step]:
    """Return a copy of ``nodes`` with the given depends_on lists applied."""
    sim = dict(nodes)
    for step_uuid, deps in new_by_uuid.items():
        sim[step_uuid] = dataclasses.replace(nodes[step_uuid], depends_on=list(deps))
    return sim


def detect_cycle(
    nodes: dict[uuid.UUID, Step], new_by_uuid: dict[uuid.UUID, list[str]]
) -> list[str] | None:
    """Return the residual cycle paths a change would create, or None."""
    sim = simulate(nodes, new_by_uuid)
    _order, residual = topological_order(sim, build_edges(sim))
    if residual:
        return sorted(canonical_step_path(sim, sim[u]) for u in residual)
    return None


def execution_order_paths(nodes: dict[uuid.UUID, Step]) -> list[str]:
    """Topological execution order rendered as canonical paths (empty on cycle)."""
    order, residual = topological_order(nodes, build_edges(nodes))
    if residual:
        return []
    return [canonical_step_path(nodes, nodes[u]) for u in order]


def parallel_wave_paths(nodes: dict[uuid.UUID, Step]) -> list[list[str]]:
    """Parallel waves rendered as canonical paths (empty list on cycle)."""
    try:
        w = waves(nodes, build_edges(nodes))
    except ValueError:
        return []
    return [[canonical_step_path(nodes, nodes[u]) for u in wave] for wave in w]


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
    return record_revision(conn, plan.uuid, "api", message, changes, parent, ref_name)


def head_revision_str(conn, plan) -> str | None:
    """Current head revision as a string, for no-op idempotent responses."""
    head = current_head_revision(conn, plan.uuid)
    return str(head) if head else None
