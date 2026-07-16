"""Files-to-writers report view (FilesWriterReport, C-004).

Read-only projection over a plan's level-5 (atomic) step dependency graph
(C-009): for every distinct target_file among a set of scoped atomic steps,
lists the writing atomic steps in priority order together with each
writer's operation kind, and flags an ordering conflict whenever two
writers of the same target_file have no directed path between them in the
full plan's dependency graph edges.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import parent_path

def reachable_from(
    start_uuid: uuid.UUID,
    edges: set[tuple[uuid.UUID, uuid.UUID]],
) -> set[uuid.UUID]:
    """Compute every node reachable from one node by following edges forward.

    Args:
        start_uuid: The node uuid to start the traversal from.
        edges: The full dependency-graph edge set as returned by
            build_edges(nodes): each edge is a 2-tuple
            (prerequisite_uuid, dependent_uuid); traversal follows edges
            only in this prerequisite -> dependent direction.

    Returns:
        The set of node uuids reachable from start_uuid by following one or
        more edges forward. start_uuid itself is included only if a cycle
        routes back to it; otherwise it is excluded.
    """
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for prereq_uuid, dependent_uuid in edges:
        adjacency.setdefault(prereq_uuid, []).append(dependent_uuid)

    visited: set[uuid.UUID] = set()
    frontier: list[uuid.UUID] = list(adjacency.get(start_uuid, []))
    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        frontier.extend(adjacency.get(current, []))
    return visited

def has_ordering_path(
    first_uuid: uuid.UUID,
    second_uuid: uuid.UUID,
    edges: set[tuple[uuid.UUID, uuid.UUID]],
) -> bool:
    """Return whether a directed path exists between two nodes in either direction.

    Args:
        first_uuid: Uuid of the first writer atomic step.
        second_uuid: Uuid of the second writer atomic step.
        edges: The full dependency-graph edge set as returned by
            build_edges(nodes).

    Returns:
        True when second_uuid is reachable from first_uuid via
        reachable_from(first_uuid, edges), or first_uuid is reachable from
        second_uuid via reachable_from(second_uuid, edges). False when
        neither direction reaches the other node.
    """
    if second_uuid in reachable_from(first_uuid, edges):
        return True
    return first_uuid in reachable_from(second_uuid, edges)

def build_files_report(
    nodes: dict[uuid.UUID, Step],
    scoped_atomic_steps: list[Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
) -> list[dict]:
    """Build the target_file -> writer-steps matrix for a plan scope (C-004).

    Args:
        nodes: Every step of the plan, keyed by uuid, as returned by
            load_steps(conn, plan_uuid); used to resolve each writer's
            canonical branch path via parent_path(nodes, step).
        scoped_atomic_steps: The level-5 (atomic) steps in scope, as
            returned by scope_atomic_steps(nodes, scope); each entry's
            fields dict must supply "target_file" (str), "operation"
            (str), and "priority" (int).
        edges: The full plan dependency-graph edge set as returned by
            build_edges(nodes): each edge is
            (prerequisite_uuid, dependent_uuid), combining declared
            depends_on edges and same-file/same-parent priority-chain
            edges. Passed as the full-plan edge set (not restricted to
            scoped_atomic_steps) so ordering established outside the
            scope is still honored.

    Returns:
        A list of file-entry dicts, one per distinct target_file value
        among scoped_atomic_steps, sorted ascending by target_file. Each
        file-entry dict has exactly these keys:
            "target_file": the target file path (str).
            "writers": list of {"step": str, "priority": int,
                "operation": str} dicts, one per atomic step in
                scoped_atomic_steps that declares this target_file, sorted
                ascending by fields["priority"]. "step" is
                f"{parent_path(nodes, step)}/{step.step_id}" (the writer's
                canonical branch path); "priority" and "operation" are
                copied from fields["priority"] and fields["operation"].
            "ordering_conflict": bool. True when this file has two or
                more writers and at least one unordered pair of writers
                (i, j) has has_ordering_path(i.uuid, j.uuid, edges) ==
                False. False when the file has zero or one writer, or
                every unordered pair of writers has
                has_ordering_path(...) == True.
    """
    groups: dict[str, list[Step]] = {}
    for step in scoped_atomic_steps:
        target_file = step.fields["target_file"]
        groups.setdefault(target_file, []).append(step)

    report: list[dict] = []
    for target_file in sorted(groups.keys()):
        writer_steps = sorted(groups[target_file], key=lambda s: s.fields["priority"])
        writers = [
            {
                "step": f"{parent_path(nodes, step)}/{step.step_id}",
                "priority": step.fields["priority"],
                "operation": step.fields["operation"],
            }
            for step in writer_steps
        ]

        ordering_conflict = False
        for i in range(len(writer_steps)):
            for j in range(i + 1, len(writer_steps)):
                if not has_ordering_path(
                    writer_steps[i].uuid, writer_steps[j].uuid, edges
                ):
                    ordering_conflict = True
                    break
            if ordering_conflict:
                break

        report.append(
            {
                "target_file": target_file,
                "writers": writers,
                "ordering_conflict": ordering_conflict,
            }
        )
    return report
