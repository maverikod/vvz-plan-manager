"""Whole-plan same-file writer ordering helpers."""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step

Edge = tuple[uuid.UUID, uuid.UUID]


class SameFileOrderAmbiguousError(ValueError):
    """Raised when same-file atomic writers have no deterministic order."""

    def __init__(self, conflicts: list[tuple[uuid.UUID, uuid.UUID, str]]) -> None:
        self.conflicts = conflicts
        details = "; ".join(f"{target_file}: {first} <> {second}" for first, second, target_file in conflicts)
        super().__init__(f"ambiguous same-file writer order: {details}")


def reachable(edges: set[Edge], start_uuid: uuid.UUID, target_uuid: uuid.UUID) -> bool:
    """Return whether target is reachable from start."""
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for prerequisite, dependent in edges:
        adjacency.setdefault(prerequisite, []).append(dependent)
    seen: set[uuid.UUID] = set()
    pending = list(adjacency.get(start_uuid, []))
    while pending:
        current = pending.pop()
        if current == target_uuid:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency.get(current, []))
    return False


def ancestors(nodes: dict[uuid.UUID, Step], node_uuid: uuid.UUID) -> list[uuid.UUID]:
    """Return node plus every resolvable parent up to its GS root."""
    result = [node_uuid]
    current = nodes[node_uuid]
    while current.parent_step_uuid is not None and current.parent_step_uuid in nodes:
        result.append(current.parent_step_uuid)
        current = nodes[current.parent_step_uuid]
    return result


def branch_order(
    nodes: dict[uuid.UUID, Step],
    edges: set[Edge],
    first_uuid: uuid.UUID,
    second_uuid: uuid.UUID,
) -> int:
    """Return -1 for first-before-second, 1 for reverse, 0 if ambiguous."""
    first_ancestors = ancestors(nodes, first_uuid)
    second_ancestors = ancestors(nodes, second_uuid)
    first_before = any(
        reachable(edges, left, right)
        for left in first_ancestors
        for right in second_ancestors
        if left != right
    )
    second_before = any(
        reachable(edges, right, left)
        for left in first_ancestors
        for right in second_ancestors
        if left != right
    )
    if first_before and not second_before:
        return -1
    if second_before and not first_before:
        return 1
    return 0


def derive_cross_branch_edges(
    nodes: dict[uuid.UUID, Step],
    edges: set[Edge],
    by_file: dict[str, list[uuid.UUID]],
) -> None:
    """Add atom edges only where ancestor dependencies define one direction."""
    for group_uuids in by_file.values():
        for index, first_uuid in enumerate(group_uuids):
            for second_uuid in group_uuids[index + 1 :]:
                if nodes[first_uuid].parent_step_uuid == nodes[second_uuid].parent_step_uuid:
                    continue
                if reachable(edges, first_uuid, second_uuid) or reachable(edges, second_uuid, first_uuid):
                    continue
                direction = branch_order(nodes, edges, first_uuid, second_uuid)
                if direction < 0:
                    edges.add((first_uuid, second_uuid))
                elif direction > 0:
                    edges.add((second_uuid, first_uuid))


def same_file_order_conflicts(
    nodes: dict[uuid.UUID, Step],
    edges: set[Edge],
) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    """Return same-file atomic pairs with no path in either direction."""
    by_file: dict[str, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            by_file.setdefault(target_file, []).append(node_uuid)
    conflicts: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    for target_file, group in sorted(by_file.items()):
        for index, first_uuid in enumerate(group):
            for second_uuid in group[index + 1 :]:
                if not (
                    reachable(edges, first_uuid, second_uuid)
                    or reachable(edges, second_uuid, first_uuid)
                ):
                    conflicts.append((first_uuid, second_uuid, target_file))
    return conflicts


def _conflict_key(conflict: tuple[uuid.UUID, uuid.UUID, str]) -> tuple[str, frozenset[uuid.UUID]]:
    first, second, target_file = conflict
    return (target_file, frozenset((first, second)))


def diff_same_file_conflicts(
    before_conflicts: list[tuple[uuid.UUID, uuid.UUID, str]],
    after_conflicts: list[tuple[uuid.UUID, uuid.UUID, str]],
) -> tuple[
    list[tuple[uuid.UUID, uuid.UUID, str]],
    list[tuple[uuid.UUID, uuid.UUID, str]],
    list[tuple[uuid.UUID, uuid.UUID, str]],
]:
    """Diff two same-file-conflict snapshots into (introduced, resolved, remaining).

    Pairs are compared by an order-independent key (target_file, frozenset of the
    two step uuids), never by tuple position: ``same_file_order_conflicts`` orders
    each pair by ``nodes.items()`` iteration order, which is insertion order and is
    NOT guaranteed identical between a before-state node dict and an independently
    reloaded after-state node dict (e.g. a fresh ``load_steps`` row fetch has no
    ORDER BY), so a naive tuple-equality diff could mistake a flipped pair for a
    different one.

    Returns:
        introduced: pairs present after but absent before (new ambiguity).
        resolved: pairs present before but absent after (no longer ambiguous).
        remaining: pairs present in both (pre-existing ambiguity that persists).
    """
    before_by_key = {_conflict_key(c): c for c in before_conflicts}
    after_by_key = {_conflict_key(c): c for c in after_conflicts}
    introduced = [after_by_key[k] for k in after_by_key if k not in before_by_key]
    resolved = [before_by_key[k] for k in before_by_key if k not in after_by_key]
    remaining = [after_by_key[k] for k in after_by_key if k in before_by_key]
    return introduced, resolved, remaining
