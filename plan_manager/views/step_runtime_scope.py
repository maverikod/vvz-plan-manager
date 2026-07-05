"""Step runtime scope helpers."""

from __future__ import annotations

import re
import uuid

from plan_manager.domain.step import Step
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.views.dependency_graph import parent_path


_GLOBAL_SCOPE_RE = re.compile(r"^G-\d{3}$")
_TACTICAL_SCOPE_RE = re.compile(r"^(G-\d{3})/(T-\d{3})$")


def resolve_step_by_id(nodes: dict[uuid.UUID, Step], step_id: str) -> Step | None:
    """Resolve one step ref using the command step-reference contract."""
    return resolve_step_ref(nodes, step_id)


def scoped_steps(nodes: dict[uuid.UUID, Step], scope: str | None) -> list[Step]:
    """Return steps within whole-plan, G-NNN, or G-NNN/T-NNN scope."""
    if scope is None or scope == "" or scope == "whole_plan":
        result = list(nodes.values())
    elif _GLOBAL_SCOPE_RE.match(scope):
        gs = next(
            (step for step in nodes.values() if step.level == 3 and step.step_id == scope),
            None,
        )
        if gs is None:
            raise ValueError(f"scope not found: {scope}")
        result = [
            step
            for step in nodes.values()
            if step.uuid == gs.uuid
            or (
                step.level in (4, 5)
                and parent_path(nodes, step).split("/")[0] == scope
            )
        ]
    else:
        tactical = _TACTICAL_SCOPE_RE.match(scope)
        if tactical is None:
            raise ValueError("scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'")
        gs_step_id, ts_step_id = tactical.group(1), tactical.group(2)
        ts = next(
            (
                step
                for step in nodes.values()
                if step.level == 4
                and step.step_id == ts_step_id
                and parent_path(nodes, step) == gs_step_id
            ),
            None,
        )
        if ts is None:
            raise ValueError(f"scope not found: {scope}")
        result = [
            step
            for step in nodes.values()
            if step.uuid == ts.uuid
            or (step.level == 5 and parent_path(nodes, step) == scope)
        ]
    result.sort(key=lambda step: (step.level, parent_path(nodes, step), step.step_id))
    return result
