"""Rendering and simulation helpers for the step dependency command family.

Split out of ``step_dependency_ops.py`` (which had grown past the 400-line
cap) to keep that module scoped to the reference-resolution/scope-check and
admission+revision-write *engine* the preview/apply commands drive. This
sibling module holds everything that only *reads* an already-resolved node
set and either renders it for output or simulates a candidate change: bare
depends_on -> canonical-path rendering, dependents lookup, cycle detection,
before/after execution-order/parallel-wave projection, and the monotone
same-file writer-order admission rule (bug 64107707). None of it mutates the
database or its arguments.

Every name here is re-exported by ``step_dependency_ops`` (import-only, no
re-definition) so the seven step_dependency_* command modules keep importing
from ``plan_manager.commands.step_dependency_ops`` unchanged.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import (
    build_edges,
    resolve_dependency_target,
    topological_order,
    waves,
)
from plan_manager.views.same_file_order import (
    diff_same_file_conflicts,
    same_file_order_conflicts,
)

SameFileConflict = tuple[uuid.UUID, uuid.UUID, str]


# ---------------------------------------------------------------------------
# Rendering (bare step_id -> canonical path) and dependents
# ---------------------------------------------------------------------------


def render_depends(
    nodes: dict[uuid.UUID, Step], target: Step, bares: list[str]
) -> list[str]:
    """Render stored dependency refs as canonical paths for command output."""
    out: list[str] = []
    for stored_ref in bares:
        dep = resolve_dependency_target(nodes, target, stored_ref)
        out.append(canonical_step_path(nodes, dep) if dep is not None else stored_ref)
    return out


def dependents_paths(nodes: dict[uuid.UUID, Step], target: Step) -> list[str]:
    """Canonical paths of steps that depend on ``target``."""
    result: list[str] = []
    for step in nodes.values():
        if step.uuid == target.uuid:
            continue
        if any(
            (dep := resolve_dependency_target(nodes, step, stored_ref)) is not None
            and dep.uuid == target.uuid
            for stored_ref in step.depends_on
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
    """Return the residual cycle paths a change would create, or None.

    Cycle detection is orthogonal to same-file writer ambiguity (bug
    64107707): edges are built with ``strict_same_file_order=False`` so an
    unrelated pre-existing (or still-unresolved) same-file ambiguity never
    raises here and never masks the actual cycle-or-not verdict. Same-file
    admission is evaluated separately by ``same_file_admission``.
    """
    sim = simulate(nodes, new_by_uuid)
    _order, residual = topological_order(sim, build_edges(sim, strict_same_file_order=False))
    if residual:
        return sorted(canonical_step_path(sim, sim[u]) for u in residual)
    return None


def execution_order_paths(nodes: dict[uuid.UUID, Step]) -> list[str]:
    """Topological execution order rendered as canonical paths (empty on cycle).

    Built with ``strict_same_file_order=False`` (bug 64107707): an ambiguous
    same-file pair does not prevent computing *a* valid topological order (Kahn's
    algorithm still linearizes it via the deterministic tie-break; only a true
    cycle makes the order uncomputable). Callers that need the audited,
    gated order use ``graph_order`` instead.
    """
    order, residual = topological_order(nodes, build_edges(nodes, strict_same_file_order=False))
    if residual:
        return []
    return [canonical_step_path(nodes, nodes[u]) for u in order]


def parallel_wave_paths(nodes: dict[uuid.UUID, Step]) -> list[list[str]]:
    """Parallel waves rendered as canonical paths (empty list on cycle).

    Built with ``strict_same_file_order=False`` (bug 64107707); see
    ``execution_order_paths`` for why ambiguity alone does not block this.
    """
    try:
        w = waves(nodes, build_edges(nodes, strict_same_file_order=False))
    except ValueError:
        return []
    return [[canonical_step_path(nodes, nodes[u]) for u in wave] for wave in w]


# ---------------------------------------------------------------------------
# Same-file writer-order admission (bug 64107707): monotone rule, never
# short-circuited by a pre-existing before-state ambiguity.
# ---------------------------------------------------------------------------


def same_file_conflicts(nodes: dict[uuid.UUID, Step]) -> list[SameFileConflict]:
    """Same-file writer-order conflicts of one node set, never raising."""
    return same_file_order_conflicts(nodes, build_edges(nodes, strict_same_file_order=False))


def same_file_admission(
    before_nodes: dict[uuid.UUID, Step], after_nodes: dict[uuid.UUID, Step]
) -> dict[str, list[SameFileConflict]]:
    """Evaluate the monotone same-file-order admission rule for a candidate.

    Same-file writer ambiguity is reported, never gated, on its own: a
    mutation is refused only when it introduces a NEW ambiguous pair absent
    from the before-state (see ``introduced``). A pre-existing ambiguity that
    survives the candidate unchanged is a finding, never a rejection reason.
    """
    before_conflicts = same_file_conflicts(before_nodes)
    after_conflicts = same_file_conflicts(after_nodes)
    introduced, resolved, remaining = diff_same_file_conflicts(before_conflicts, after_conflicts)
    return {
        "before_conflicts": before_conflicts,
        "after_conflicts": after_conflicts,
        "introduced": introduced,
        "resolved": resolved,
        "remaining": remaining,
    }


def render_same_file_conflicts(
    nodes: dict[uuid.UUID, Step], conflicts: list[SameFileConflict]
) -> list[dict[str, Any]]:
    """Render same-file conflict tuples as {target_file, writers} findings, sorted."""
    out: list[dict[str, Any]] = []
    for first_uuid, second_uuid, target_file in conflicts:
        writers = sorted(
            [canonical_step_path(nodes, nodes[first_uuid]), canonical_step_path(nodes, nodes[second_uuid])]
        )
        out.append({"target_file": target_file, "writers": writers})
    out.sort(key=lambda finding: (finding["target_file"], finding["writers"]))
    return out
