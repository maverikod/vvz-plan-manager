"""Unified work queue item model: the normalized descriptor of one pending work unit (C-027)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkKind(str, Enum):
    AS_READY = "as_ready"
    TODO = "todo"
    BUG_INVESTIGATION = "bug_investigation"
    BUG_FIX = "bug_fix"
    PROPAGATION = "propagation"
    VERIFICATION = "verification"
    REVIEW = "review"
    ESCALATION = "escalation"


WORK_KINDS: frozenset[str] = frozenset(k.value for k in WorkKind)

# Bug-severity ordering rank used by the queue; non-bug items rank last. Pinned exactly.
SEVERITY_RANK: dict[str, int] = {"blocker": 0, "critical": 1, "major": 2, "minor": 3, "trivial": 4}
NON_BUG_SEVERITY_RANK = 5  # rank used when bug_severity is None


@dataclass(frozen=True)
class WorkItem:
    work_kind: str                      # a WorkKind value
    source_uuid: uuid.UUID              # the runtime record uuid (or the AS step_uuid for as_ready) = back-reference
    title: str
    priority_nice: int                  # C-007 nice value already validated by the source; lower = higher priority
    ready: bool                         # dependency readiness (launchable dep-wise)
    requires_runtime: bool              # True for as_ready (executes on runtime incl. Vast/Qwen); False otherwise
    is_blocker: bool = False            # blocker bug (severity=="blocker"); pausing signal
    bug_severity: str | None = None     # BugSeverity value for bug-derived items; None otherwise
    execution_wave: int | None = None   # earlier wave first; None sorts last
    due_at: str | None = None           # ISO timestamp; earliest first; None sorts last
    created_at: str = ""                # ISO timestamp; age ordering (oldest first)
    plan_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None
    step_path: str | None = None
    assigned_provider: str | None = None
    assigned_model: str | None = None   # availability of the assigned model together with ResourceAvailability
    lock_keys: frozenset[str] = field(default_factory=frozenset)  # file paths / project-id strings this item needs unlocked
    paused: bool = False                # set by the ordering layer; never mutates plan truth
    paused_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "work_kind": self.work_kind,
            "source_uuid": str(self.source_uuid),
            "title": self.title,
            "priority_nice": self.priority_nice,
            "ready": self.ready,
            "requires_runtime": self.requires_runtime,
            "is_blocker": self.is_blocker,
            "bug_severity": self.bug_severity,
            "execution_wave": self.execution_wave,
            "due_at": self.due_at,
            "created_at": self.created_at,
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "step_uuid": str(self.step_uuid) if self.step_uuid is not None else None,
            "step_path": self.step_path,
            "assigned_provider": self.assigned_provider,
            "assigned_model": self.assigned_model,
            "lock_keys": sorted(self.lock_keys),
            "paused": self.paused,
            "paused_reason": self.paused_reason,
        }


@dataclass(frozen=True)
class AsReadyItem:
    """Caller-supplied descriptor of an atomic step already determined ready by the existing plan dependency /
    graph_order machinery. This layer does NOT recompute plan readiness (that is frozen-plan-truth / graph
    territory); it only INCLUDES ready AS in the queue and orders them (C-027)."""
    plan_uuid: uuid.UUID
    step_uuid: uuid.UUID
    step_path: str
    priority_nice: int
    created_at: str
    execution_wave: int | None = None
    assigned_provider: str | None = None
    assigned_model: str | None = None
    ready: bool = True
    lock_keys: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ResourceAvailability:
    """Runtime-environment facts supplied by the caller; the queue orders against them, it does not probe them."""
    available_models: frozenset[str] = field(default_factory=frozenset)  # entries "<provider>/<model>" AND/OR bare "<model>"
    runtime_available: bool = True
    vast_available: bool = True
    locked_files: frozenset[str] = field(default_factory=frozenset)      # project-relative file paths currently locked
    locked_projects: frozenset[str] = field(default_factory=frozenset)   # project-id strings currently locked
