"""Unified work queue ordering and the pause-not-mutate invariant (C-027)."""
from __future__ import annotations
import dataclasses
from typing import Any

from plan_manager.runtime.work_item import (
    WorkItem, ResourceAvailability, WorkKind, SEVERITY_RANK, NON_BUG_SEVERITY_RANK,
)

# A high-priority TODO (nice <= this) anchored to a step is a pausing signal for that step's ready AS.
HIGH_PRIORITY_NICE_THRESHOLD = -10
WAVE_SENTINEL = 1_000_000        # used when execution_wave is None (sorts last)
DUE_SENTINEL = "9999-12-31T23:59:59+00:00"  # used when due_at is None (sorts last)


def severity_rank(bug_severity: str | None) -> int:
    # Return SEVERITY_RANK for the given severity; unknown or None severity ranks last among bugs.
    return SEVERITY_RANK.get(bug_severity, NON_BUG_SEVERITY_RANK)


def model_available(item: WorkItem, availability: ResourceAvailability) -> bool:
    # True if item.assigned_model is None; else True iff item.assigned_model is in availability.available_models
    # OR f"{item.assigned_provider}/{item.assigned_model}" is in availability.available_models.
    if item.assigned_model is None:
        return True
    if item.assigned_model in availability.available_models:
        return True
    return f"{item.assigned_provider}/{item.assigned_model}" in availability.available_models


def is_launchable(item: WorkItem, availability: ResourceAvailability) -> bool:
    # Launchable now iff: item.ready AND (not item.paused) AND model_available(item, availability)
    # AND (not item.requires_runtime OR (availability.runtime_available AND availability.vast_available))
    # AND item.lock_keys is disjoint from (availability.locked_files | availability.locked_projects).
    if not item.ready:
        return False
    if item.paused:
        return False
    if not model_available(item, availability):
        return False
    if item.requires_runtime and not (availability.runtime_available and availability.vast_available):
        return False
    locked = availability.locked_files | availability.locked_projects
    if not item.lock_keys.isdisjoint(locked):
        return False
    return True


def order_key(item: WorkItem, availability: ResourceAvailability) -> tuple[Any, ...]:
    # Ascending total order. This tuple is pinned EXACTLY.
    return (
        0 if is_launchable(item, availability) else 1,     # launchable first
        0 if item.is_blocker else 1,                        # blocker status next
        severity_rank(item.bug_severity),                   # bug severity
        item.priority_nice,                                 # nice (-20 first)
        item.execution_wave if item.execution_wave is not None else WAVE_SENTINEL,  # execution wave
        item.due_at if item.due_at is not None else DUE_SENTINEL,                    # due date (ISO str compare)
        item.created_at,                                    # age (oldest ISO first)
        str(item.source_uuid),                              # deterministic tie-break
    )


def order_queue(items: list[WorkItem], availability: ResourceAvailability) -> list[WorkItem]:
    # Stable, deterministic, pure.
    return sorted(items, key=lambda it: order_key(it, availability))


def pause_dependent_as(items: list[WorkItem]) -> list[WorkItem]:
    # A blocker bug OR a high-priority TODO anchored to a step may PAUSE that step's ready AS, but MUST NOT
    # change plan execution dependencies. Pure list transform, NO DB, NO mutation of plan truth.
    pausing_step_uuids = {
        it.step_uuid
        for it in items
        if it.step_uuid is not None
        and (
            (it.work_kind == WorkKind.BUG_INVESTIGATION.value and it.is_blocker)
            or (it.work_kind == WorkKind.TODO.value and it.priority_nice <= HIGH_PRIORITY_NICE_THRESHOLD)
        )
    }
    result: list[WorkItem] = []
    for item in items:
        if item.work_kind == WorkKind.AS_READY.value and item.step_uuid in pausing_step_uuids:
            result.append(
                dataclasses.replace(
                    item,
                    paused=True,
                    paused_reason="paused by blocker bug or high-priority todo on the same step",
                )
            )
        else:
            result.append(item)
    return result
