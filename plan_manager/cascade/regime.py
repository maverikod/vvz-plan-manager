"""Mutation admission regime for CascadeChange (C-016).

Classifies mutation requests by target kind and artifact status per the
status model (C-007), admitting a request directly against the plan head
or only within the plan's open cascade.
"""

import uuid

import psycopg

from plan_manager.cascade.record import CascadeError, CascadeRecord, get_open_cascade
from plan_manager.domain.step_store import Step
from plan_manager.views.dependency_graph import impact_set, load_steps

MRS_ENTITY_KINDS: frozenset[str] = frozenset({"concept", "relation"})
DIRECT_STATUSES: frozenset[str] = frozenset({"draft", "ready_for_review"})


def frozen_at_or_below(nodes: dict[uuid.UUID, Step], origin_uuid: uuid.UUID) -> bool:
    """Return True iff the step at `origin_uuid`, or any step in its
    transitive impact set (its children and their children, recursively,
    as returned by `impact_set`), has status "frozen".

    Args:
        nodes: mapping of step uuid to Step, as returned by `load_steps`.
        origin_uuid: uuid of the step to check.

    Returns:
        True if `nodes[origin_uuid].status == "frozen"` or any step
        reachable via `impact_set(nodes, origin_uuid)` has status
        "frozen"; False otherwise.

    Raises:
        CascadeError: if `origin_uuid` is not a key of `nodes`.
    """
    if origin_uuid not in nodes:
        raise CascadeError(f"step {origin_uuid} not found among the loaded nodes")
    if nodes[origin_uuid].status == "frozen":
        return True
    for child_uuid in impact_set(nodes, origin_uuid):
        if nodes[child_uuid].status == "frozen":
            return True
    return False


def frozen_ancestor(nodes: dict[uuid.UUID, Step], origin_uuid: uuid.UUID) -> bool:
    """Return True iff any STRICT ancestor of the step at `origin_uuid` (its
    parent, grandparent, and so on up the parent_step_uuid chain, excluding
    the step itself) has status "frozen".

    This closes the gap left by `frozen_at_or_below`, which only inspects
    `origin_uuid` itself and its DESCENDANTS: neither function alone detects
    a step whose ANCESTOR (not itself, not a descendant) is frozen while the
    step's own subtree is not.

    Args:
        nodes: mapping of step uuid to Step, as returned by `load_steps`.
        origin_uuid: uuid of the step whose ancestor chain to check.

    Returns:
        True if any ancestor of `nodes[origin_uuid]` has status "frozen";
        False when no ancestor is frozen, including when the step has no
        parent (a level-3 global step).

    Raises:
        CascadeError: if `origin_uuid` is not a key of `nodes`.
    """
    if origin_uuid not in nodes:
        raise CascadeError(f"step {origin_uuid} not found among the loaded nodes")
    parent_uuid = nodes[origin_uuid].parent_step_uuid
    while parent_uuid is not None:
        parent = nodes.get(parent_uuid)
        if parent is None:
            break
        if parent.status == "frozen":
            return True
        parent_uuid = parent.parent_step_uuid
    return False


def check_admission(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    target_kind: str,
    target_uuid: uuid.UUID | None,
    cascade_uuid: uuid.UUID | None,
) -> CascadeRecord | None:
    """Classify a mutation request under the admission rule (C-016, C-007).

    Args:
        conn: open database connection.
        plan_uuid: identity of the plan the request targets.
        target_kind: one of "concept", "relation", "step", "paragraph".
        target_uuid: identity of the targeted step when `target_kind` is
            "step"; ignored (may be None) for the other three kinds.
        cascade_uuid: identity of the cascade the request claims to run
            inside, or None for a request claiming direct admission.

    Returns:
        The plan's open CascadeRecord when the request is admitted as
        cascade-scoped (cascade_uuid was given and matches the plan's
        open cascade). None when the request is admitted directly
        against the plan head.

    Raises:
        CascadeError: for every rejection case:
            - `target_kind` is not one of "concept", "relation", "step",
              "paragraph".
            - `cascade_uuid` is not None but does not match the plan's
              open cascade (including when the plan has no open
              cascade).
            - `cascade_uuid` is None and the plan already has an open
              cascade (direct mutation rejected while a cascade is
              open).
            - `cascade_uuid` is None and `target_kind` is "concept" or
              "relation" (MRS entities are cascade-only).
            - `cascade_uuid` is None, `target_kind` is "step", and
              `target_uuid` is None.
            - `cascade_uuid` is None, `target_kind` is "step", and
              `target_uuid` is not found among the plan's steps.
            - `cascade_uuid` is None, `target_kind` is "step", and the
              target step's status is not in DIRECT_STATUSES, or the
              target step is frozen_at_or_below, or the target step has
              a frozen_ancestor (an ancestor step, strictly above the
              target, with status "frozen").
            - `cascade_uuid` is None, `target_kind` is "paragraph", and
              any step of the plan has status "frozen".
    """
    if target_kind not in {"concept", "relation", "step", "paragraph"}:
        raise CascadeError(f"unknown target kind: {target_kind!r}")
    if cascade_uuid is not None:
        rec = get_open_cascade(conn, plan_uuid)
        if rec is None or rec.uuid != cascade_uuid:
            raise CascadeError("cascade id does not match the open cascade")
        return rec
    if get_open_cascade(conn, plan_uuid) is not None:
        raise CascadeError("plan has an open cascade; direct mutation rejected")
    if target_kind in MRS_ENTITY_KINDS:
        raise CascadeError("MRS entities are cascade-only")
    if target_kind == "step":
        if target_uuid is None:
            raise CascadeError("a step mutation requires a target_uuid")
        nodes = load_steps(conn, plan_uuid)
        if target_uuid not in nodes:
            raise CascadeError(f"step {target_uuid} not found in plan {plan_uuid}")
        if (
            nodes[target_uuid].status not in DIRECT_STATUSES
            or frozen_at_or_below(nodes, target_uuid)
            or frozen_ancestor(nodes, target_uuid)
        ):
            raise CascadeError(f"step {target_uuid} is not directly mutable")
        return None
    nodes = load_steps(conn, plan_uuid)
    if any(step.status == "frozen" for step in nodes.values()):
        raise CascadeError("plan has a frozen step; direct paragraph mutation rejected")
    return None
