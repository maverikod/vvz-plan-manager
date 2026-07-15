"""TODO work item domain: kinds, statuses, and the runtime TodoItem record (C-005)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck


class TodoKind(str, Enum):
    TASK = "task"
    FOLLOWUP = "followup"
    CLEANUP = "cleanup"
    QUESTION = "question"
    RISK = "risk"
    INVESTIGATION = "investigation"
    REVIEW = "review"
    UPDATE = "update"
    MIGRATION = "migration"
    REBUILD = "rebuild"
    TEST_RERUN = "test_rerun"
    DOCUMENTATION = "documentation"


class TodoStatus(str, Enum):
    OPEN = "open"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


TODO_KINDS: frozenset[str] = frozenset(k.value for k in TodoKind)
TODO_STATUSES: frozenset[str] = frozenset(s.value for s in TodoStatus)


@dataclass(frozen=True)
class TodoItem(DataclassEntity):
    ENTITY_TYPE = "todo"
    ENTITY_ID_FIELD = "todo_uuid"
    TABLE_NAME = "todo_item"
    HARD_DELETE_REFERENCE_CHECKS = (
        ReferenceCheck("todo_link", "from_todo_uuid", "todo_uuid", live_column="deleted_at"),
        ReferenceCheck("todo_link", "to_todo_uuid", "todo_uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "todo_uuid", "todo_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix_propagation", "linked_todo_uuid", "todo_uuid", live_column="deleted_at"),
    )

    todo_uuid: uuid.UUID
    title: str
    description: str
    kind: str
    status: str
    priority_nice: int
    created_by: str
    assigned_to: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    resolved_at: str | None
    due_at: str | None
    primary_anchor_type: str
    anchor_project_id: uuid.UUID | None
    anchor_file_path: str | None
    anchor_plan_uuid: uuid.UUID | None
    anchor_revision_uuid: uuid.UUID | None
    anchor_step_uuid: uuid.UUID | None
    anchor_step_path: str | None
    anchor_ref_id: uuid.UUID | None
    blocking_reason: str | None
    execution_result: str | None
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this TodoItem as a JSON-safe dict: every uuid.UUID field becomes str (or stays None); timestamp fields are already ISO strings and pass through unchanged."""
        return {
            "uuid": str(self.todo_uuid),
            "todo_uuid": str(self.todo_uuid),
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "status": self.status,
            "priority_nice": self.priority_nice,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "resolved_at": self.resolved_at,
            "due_at": self.due_at,
            "primary_anchor_type": self.primary_anchor_type,
            "anchor_project_id": str(self.anchor_project_id) if self.anchor_project_id is not None else None,
            "anchor_file_path": self.anchor_file_path,
            "anchor_plan_uuid": str(self.anchor_plan_uuid) if self.anchor_plan_uuid is not None else None,
            "anchor_revision_uuid": str(self.anchor_revision_uuid) if self.anchor_revision_uuid is not None else None,
            "anchor_step_uuid": str(self.anchor_step_uuid) if self.anchor_step_uuid is not None else None,
            "anchor_step_path": self.anchor_step_path,
            "anchor_ref_id": str(self.anchor_ref_id) if self.anchor_ref_id is not None else None,
            "blocking_reason": self.blocking_reason,
            "execution_result": self.execution_result,
            "deleted_at": self.deleted_at,
        }
