"""Wish runtime domain: feature desires tracked separately from todos and bugs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck


class WishKind(str, Enum):
    FEATURE = "feature"
    UX = "ux"
    AUTOMATION = "automation"
    INTEGRATION = "integration"
    REPORTING = "reporting"
    TOOLING = "tooling"
    OTHER = "other"


class WishStatus(str, Enum):
    PROPOSED = "proposed"
    TRIAGED = "triaged"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


WISH_KINDS: frozenset[str] = frozenset(item.value for item in WishKind)
WISH_STATUSES: frozenset[str] = frozenset(item.value for item in WishStatus)
ACTIVE_WISH_STATUSES: frozenset[str] = frozenset(
    {
        WishStatus.PROPOSED.value,
        WishStatus.TRIAGED.value,
        WishStatus.PLANNED.value,
        WishStatus.IN_PROGRESS.value,
    }
)


@dataclass(frozen=True)
class WishItem(DataclassEntity):
    """Persisted runtime wish item."""

    ENTITY_TYPE = "wish"
    ENTITY_ID_FIELD = "wish_uuid"
    TABLE_NAME = "wish_item"
    # CR-7 G-003 (C-002, C-006): ownership declaration and completed descriptor.
    OWNER_GAP = (
        "primary anchor is a discriminated family (anchor_type), not one column; "
        "the owner column materializes in the G-007 anchor collapse"
    )
    ID_COLUMN = "uuid"
    # Column order follows the wish_item CREATE TABLE in migration
    # 0025_wish_and_calendar_entries.sql.
    COLUMNS = (
        "uuid",
        "title",
        "description",
        "kind",
        "status",
        "priority_nice",
        "created_by",
        "assigned_to",
        "target_release",
        "rationale",
        "created_at",
        "updated_at",
        "decided_at",
        "delivered_at",
        "primary_anchor_type",
        "anchor_project_id",
        "anchor_file_path",
        "anchor_plan_uuid",
        "anchor_revision_uuid",
        "anchor_step_uuid",
        "anchor_step_path",
        "anchor_ref_id",
        "deleted_at",
    )
    # Every column except deleted_at. uuid, created_at and updated_at ARE
    # insertable and must stay here: none of them carries a DB default, and
    # create_wish supplies all three explicitly in Python. Omitting them would
    # make crud_create reject the store's own payload, because INSERT_COLUMNS
    # is the whitelist crud_create validates against. deleted_at is excluded
    # so a create cannot mark a row deleted at birth.
    INSERT_COLUMNS = (
        "uuid",
        "title",
        "description",
        "kind",
        "status",
        "priority_nice",
        "created_by",
        "assigned_to",
        "target_release",
        "rationale",
        "created_at",
        "updated_at",
        "decided_at",
        "delivered_at",
        "primary_anchor_type",
        "anchor_project_id",
        "anchor_file_path",
        "anchor_plan_uuid",
        "anchor_revision_uuid",
        "anchor_step_uuid",
        "anchor_step_path",
        "anchor_ref_id",
    )
    # Immutable after creation: uuid, created_at, created_by. deleted_at is
    # absent on purpose — soft deletion runs through crud_soft_delete, which
    # writes the soft-delete column directly and never consults this tuple.
    UPDATE_COLUMNS = (
        "title",
        "description",
        "kind",
        "status",
        "priority_nice",
        "assigned_to",
        "target_release",
        "rationale",
        "updated_at",
        "decided_at",
        "delivered_at",
    )
    SUMMARY_FIELDS = (
        "uuid",
        "wish_uuid",
        "title",
        "status",
        "kind",
        "priority_nice",
        "assigned_to",
        "updated_at",
    )
    # The text-bearing content columns of wish_item, per its CREATE TABLE in
    # migration 0025_wish_and_calendar_entries.sql (both text NOT NULL). Declaring
    # them here is what makes crud_search's substring and regex modes available
    # for this entity; an entity with no SEARCH_COLUMNS refuses a search rather
    # than silently returning every row.
    SEARCH_COLUMNS = ("title", "description")
    HARD_DELETE_REFERENCE_CHECKS = (
        ReferenceCheck("calendar_entry", "wish_uuid", "uuid", live_column="deleted_at"),
    )

    wish_uuid: uuid.UUID
    title: str
    description: str
    kind: str
    status: str
    priority_nice: int
    created_by: str
    assigned_to: str | None
    target_release: str | None
    rationale: str | None
    created_at: str
    updated_at: str
    decided_at: str | None
    delivered_at: str | None
    primary_anchor_type: str
    anchor_project_id: uuid.UUID | None
    anchor_file_path: str | None
    anchor_plan_uuid: uuid.UUID | None
    anchor_revision_uuid: uuid.UUID | None
    anchor_step_uuid: uuid.UUID | None
    anchor_step_path: str | None
    anchor_ref_id: uuid.UUID | None
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the wish item as JSON-safe payload."""
        return {
            "uuid": str(self.wish_uuid),
            "wish_uuid": str(self.wish_uuid),
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "status": self.status,
            "priority_nice": self.priority_nice,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "target_release": self.target_release,
            "rationale": self.rationale,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "decided_at": self.decided_at,
            "delivered_at": self.delivered_at,
            "primary_anchor_type": self.primary_anchor_type,
            "anchor_project_id": str(self.anchor_project_id) if self.anchor_project_id is not None else None,
            "anchor_file_path": self.anchor_file_path,
            "anchor_plan_uuid": str(self.anchor_plan_uuid) if self.anchor_plan_uuid is not None else None,
            "anchor_revision_uuid": str(self.anchor_revision_uuid) if self.anchor_revision_uuid is not None else None,
            "anchor_step_uuid": str(self.anchor_step_uuid) if self.anchor_step_uuid is not None else None,
            "anchor_step_path": self.anchor_step_path,
            "anchor_ref_id": str(self.anchor_ref_id) if self.anchor_ref_id is not None else None,
            "deleted_at": self.deleted_at,
        }

