"""Shared step-path and dependency-reference resolution helpers."""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step


class GraphIntegrityError(ValueError):
    """Raised when a step's parent chain references a missing step."""


def parent_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the canonical parent path of ``step`` within ``nodes``."""
    if step.level == 3:
        return ""
    parent = nodes.get(step.parent_step_uuid)
    if parent is None:
        raise GraphIntegrityError(f"parent of step {step.step_id} not found in nodes")
    if step.level == 4:
        return parent.step_id
    grandparent = nodes.get(parent.parent_step_uuid)
    if grandparent is None:
        raise GraphIntegrityError(f"parent of step {step.step_id} not found in nodes")
    return f"{grandparent.step_id}/{parent.step_id}"


def canonical_step_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the canonical plan-local path of ``step``."""
    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


def resolve_dependency_target(
    nodes: dict[uuid.UUID, Step], dependent: Step, dep_ref: str
) -> Step | None:
    """Resolve one stored/input depends_on reference to its target step."""
    try:
        dep_uuid = uuid.UUID(dep_ref)
    except ValueError:
        dep_uuid = None
    if dep_uuid is not None:
        return nodes.get(dep_uuid)

    if "/" in dep_ref:
        for step in nodes.values():
            if canonical_step_path(nodes, step) == dep_ref:
                return step
        return None

    for candidate in nodes.values():
        if (
            candidate.parent_step_uuid == dependent.parent_step_uuid
            and candidate.level == dependent.level
            and candidate.step_id == dep_ref
        ):
            return candidate
    return None
