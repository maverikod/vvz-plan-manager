"""The single admission collaborator for identity and reference checks.

CR-7 G-002/T-001/A-001 (C-005, C-007). Every identifier and reference
admission check lives behind this one module: the UUID version-4 rule, the
cross-kind duplicate check, batch target-existence, ownership acyclicity and
the recursive reference closure. The four historic cycle error codes
(LINK_CYCLE, PROJECT_DEPENDENCY_CYCLE and the two in-module checks of the
entity base and identity helpers) collapse onto the ONE stable code below;
public wire formats keep their aliases at the command boundary, mapped onto
this code rather than re-implemented.

All checks are batch-local (C-007): they validate only the entities and
references a batch affects, so unrelated historical damage never blocks new
work. References among rows created in the same batch are admissible.

Reads stay cycle-tolerant - a cycle in stored data must never make a read
hang or fail - while enforcement against ownership cycles happens on the
write path. The reference closure is computed by a single recursive SQL
query over the projected edge relation, so it reads one consistent snapshot
instead of per-hop lookups from application code.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable, Mapping, Sequence

import psycopg

from plan_manager.storage.identity import (
    ensure_identity_available,
    resolve_entity_identities_batch,
)
from plan_manager.storage.identity_audit import ensure_v4_entity_uuid

ADMISSION_CYCLE = "ADMISSION_CYCLE"
"""The single stable cycle error code of the admission collaborator."""


class AdmissionCycleError(ValueError):
    """An ownership (or caller-declared acyclic) edge set closed a cycle.

    Carries the one shared code and the concrete cycle path; command
    boundaries that must keep a historic wire code expose it as an alias of
    this verdict, never as a second traversal.
    """

    code = ADMISSION_CYCLE

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = list(cycle)
        super().__init__(f"cycle detected: {' -> '.join(self.cycle)}")


class AdmissionOrderError(ValueError):
    """The declared-acyclic part of a batch could not be ordered."""


# ---------------------------------------------------------------------------
# Identifier rules (C-001) - delegated single implementations.
# ---------------------------------------------------------------------------

ensure_ref = ensure_v4_entity_uuid
"""Mint or validate a version-4 ref: the collaborator's identifier rule.

The one implementation lives in identity_audit; this name is the admission
surface every rerouted caller consumes.
"""

ensure_available = ensure_identity_available
"""Cross-kind duplicate refusal: the registry guard, surfaced here."""


# ---------------------------------------------------------------------------
# Batch target existence (C-007).
# ---------------------------------------------------------------------------


def missing_targets(
    conn: psycopg.Connection,
    refs: Iterable[uuid.UUID],
    *,
    in_batch: Iterable[uuid.UUID] = (),
) -> list[uuid.UUID]:
    """Return every referenced target that resolves nowhere.

    One query over the whole batch. References among rows created in the
    same batch (``in_batch``) are admissible by definition and never
    reported missing. An empty result admits the batch's reference set.
    """
    batch_refs = set(in_batch)
    candidates = [ref for ref in set(refs) if ref not in batch_refs]
    if not candidates:
        return []
    resolved = resolve_entity_identities_batch(conn, candidates)
    return sorted((ref for ref in candidates if ref not in resolved), key=str)


# ---------------------------------------------------------------------------
# Cycle enforcement (write path) and cycle-tolerant reads.
# ---------------------------------------------------------------------------


def ensure_edges_acyclic(edges: Iterable[tuple[str, str]]) -> None:
    """Refuse a directed edge set that contains a cycle - the ONE check.

    This is the collapsed implementation behind every historic cycle code:
    ownership edges are always validated here (an ownership cycle is always
    an error, including under recovery), and any caller-declared acyclic
    graph (blocking links, project dependencies) delegates to the same walk.

    Raises:
        AdmissionCycleError: with the concrete cycle path and the single
            shared code.
    """
    graph: dict[str, list[str]] = {}
    for src, dst in edges:
        graph.setdefault(src, []).append(dst)
        graph.setdefault(dst, [])
    white, gray, black = 0, 1, 2
    color = {node: white for node in graph}

    def visit(node: str, path: list[str]) -> None:
        color[node] = gray
        path.append(node)
        for neighbor in graph.get(node, []):
            if color[neighbor] == gray:
                start = path.index(neighbor)
                raise AdmissionCycleError(path[start:] + [neighbor])
            if color[neighbor] == white:
                visit(neighbor, path)
        path.pop()
        color[node] = black

    for node in list(graph):
        if color[node] == white:
            visit(node, [])


def ensure_owner_acyclic(
    current_owner_edges: Iterable[tuple[str, str]],
    *,
    entity_ref: uuid.UUID | str,
    new_owner_ref: uuid.UUID | str | None,
) -> None:
    """Validate one owner write against the affected ancestry and descendants.

    The caller supplies the ownership edges of the affected neighbourhood
    (child -> owner pairs); the candidate edge is added and the combined set
    must stay acyclic. new_owner_ref=None (detaching to root) never cycles.
    """
    if new_owner_ref is None:
        return
    edges = list(current_owner_edges)
    edges.append((str(entity_ref), str(new_owner_ref)))
    ensure_edges_acyclic(edges)


def reference_closure(
    conn: psycopg.Connection, start_refs: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Everything transitively referenced FROM the start set, one snapshot.

    A single recursive query over the projected edge relation
    (relation_index): UNION deduplication makes the walk cycle-tolerant, so
    a cycle in stored data terminates instead of hanging - reads never fail
    on cyclic data; enforcement lives on the write path.
    """
    if not start_refs:
        return set()
    rows = conn.execute(
        "WITH RECURSIVE walk (target_ref) AS ("
        "    SELECT target_ref FROM relation_index WHERE source_ref = ANY(%s)"
        "    UNION"
        "    SELECT ri.target_ref FROM relation_index ri"
        "    JOIN walk w ON ri.source_ref = w.target_ref"
        ") SELECT target_ref FROM walk",
        (list(start_refs),),
    ).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# Pre-transaction ordering (C-007): order the acyclic work, isolate SCCs.
# ---------------------------------------------------------------------------


def order_batch(
    items: Sequence[str], typed_edges: Iterable[tuple[str, str]]
) -> list[list[str]]:
    """Order a write batch: acyclic dependencies first-to-last, SCCs as units.

    Typed-reference edges may form cycles; a strongly connected group is
    written as ONE unit rather than rejected for being cyclic. The
    condensation of the groups is ordered topologically (prerequisite before
    dependent). An edge naming an item outside the batch is unorderable
    work and raises AdmissionOrderError.

    Returns:
        Groups in write order; singleton groups are ordinary acyclic items.
    """
    item_set = set(items)
    edges = list(typed_edges)
    for src, dst in edges:
        if src not in item_set or dst not in item_set:
            raise AdmissionOrderError(
                f"unorderable edge outside the batch: {src!r} -> {dst!r}"
            )
    # Tarjan's strongly connected components, iterative for deep chains.
    graph: dict[str, list[str]] = {item: [] for item in items}
    for src, dst in edges:
        graph[src].append(dst)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = [0]

    def strongconnect(root: str) -> None:
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, neighbors = work[-1]
            advanced = False
            for neighbor in neighbors:
                if neighbor not in index:
                    index[neighbor] = low[neighbor] = counter[0]
                    counter[0] += 1
                    stack.append(neighbor)
                    on_stack.add(neighbor)
                    work.append((neighbor, iter(graph[neighbor])))
                    advanced = True
                    break
                if neighbor in on_stack:
                    low[node] = min(low[node], index[neighbor])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))

    for item in items:
        if item not in index:
            strongconnect(item)

    # Topological order of the condensation, prerequisites first. An edge
    # src -> dst means "src references dst": dst must be written first.
    component_of = {
        member: idx for idx, component in enumerate(components) for member in component
    }
    indegree = [0] * len(components)
    successors: dict[int, set[int]] = {idx: set() for idx in range(len(components))}
    for src, dst in edges:
        a, b = component_of[src], component_of[dst]
        if a != b and a not in successors[b]:
            successors[b].add(a)
            indegree[a] += 1
    ready = sorted(
        (idx for idx in range(len(components)) if indegree[idx] == 0),
        key=lambda idx: components[idx],
    )
    ordered: list[list[str]] = []
    while ready:
        current = ready.pop(0)
        ordered.append(components[current])
        for follower in sorted(successors[current]):
            indegree[follower] -= 1
            if indegree[follower] == 0:
                ready.append(follower)
    if len(ordered) != len(components):  # pragma: no cover - defensive
        raise AdmissionOrderError("acyclic work could not be ordered")
    return ordered


# ---------------------------------------------------------------------------
# The one validation batch (C-007).
# ---------------------------------------------------------------------------


def admit_write_batch(
    conn: psycopg.Connection,
    *,
    referenced_refs: Iterable[uuid.UUID] = (),
    batch_refs: Iterable[uuid.UUID] = (),
    owner_edges: Iterable[tuple[str, str]] = (),
) -> None:
    """Run the batch's single validation pass before commit.

    One missing-reference query plus one ownership-cycle walk over the
    affected neighbourhood - nothing per-row, nothing historical. Raises
    ValueError naming every missing target, or AdmissionCycleError on an
    ownership cycle; returns None when the batch is admissible.
    """
    missing = missing_targets(conn, referenced_refs, in_batch=batch_refs)
    if missing:
        raise ValueError(
            "missing reference targets: " + ", ".join(str(ref) for ref in missing)
        )
    ensure_edges_acyclic(owner_edges)
