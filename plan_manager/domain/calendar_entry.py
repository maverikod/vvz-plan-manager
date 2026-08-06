"""Calendar-entry runtime domain for work scheduled by calendar day."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any
import uuid

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class CalendarEntryStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


CALENDAR_ENTRY_STATUSES: frozenset[str] = frozenset(item.value for item in CalendarEntryStatus)
ACTIVE_CALENDAR_ENTRY_STATUSES: frozenset[str] = frozenset(
    {CalendarEntryStatus.PLANNED.value, CalendarEntryStatus.IN_PROGRESS.value}
)


def validate_calendar_status(value: str) -> str:
    """Validate one calendar-entry status value."""
    if value not in CALENDAR_ENTRY_STATUSES:
        raise RuntimeValidationError(
            f"invalid calendar_entry status: {value!r}; expected one of {sorted(CALENDAR_ENTRY_STATUSES)}"
        )
    return value


def validate_calendar_date(value: str) -> str:
    """Validate one ISO-8601 calendar date string."""
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeValidationError(f"invalid calendar date: {value!r}") from exc
    return value


def validate_calendar_range(start_date: str, end_date: str) -> None:
    """Validate that the inclusive range is well-formed."""
    start = date.fromisoformat(validate_calendar_date(start_date))
    end = date.fromisoformat(validate_calendar_date(end_date))
    if end < start:
        raise RuntimeValidationError(
            f"calendar_entry end_date {end_date!r} precedes start_date {start_date!r}"
        )


@dataclass(frozen=True)
class CalendarEntry(DataclassEntity):
    """Persisted calendar work entry."""

    ENTITY_TYPE = "calendar_entry"
    ENTITY_ID_FIELD = "calendar_entry_uuid"
    TABLE_NAME = "calendar_entry"
    # CR-7 G-003 (C-002, C-006): ownership declaration and completed descriptor.
    OWNER_GAP = (
        "primary anchor is a discriminated family (anchor_type), not one column; "
        "the owner column materializes in the G-007 anchor collapse"
    )
    ID_COLUMN = "uuid"
    # Column order follows the calendar_entry CREATE TABLE in migration
    # 0025_wish_and_calendar_entries.sql.
    COLUMNS = (
        "uuid",
        "title",
        "description",
        "status",
        "start_date",
        "end_date",
        "created_by",
        "assigned_to",
        "wish_uuid",
        "created_at",
        "updated_at",
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
    # create_calendar_entry supplies all three explicitly in Python. Omitting
    # them would make crud_create reject the store's own payload, because
    # INSERT_COLUMNS is the whitelist it validates against. deleted_at is
    # excluded so a create cannot mark a row deleted at birth.
    INSERT_COLUMNS = (
        "uuid",
        "title",
        "description",
        "status",
        "start_date",
        "end_date",
        "created_by",
        "assigned_to",
        "wish_uuid",
        "created_at",
        "updated_at",
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
        "status",
        "start_date",
        "end_date",
        "assigned_to",
        "wish_uuid",
        "updated_at",
        "primary_anchor_type",
        "anchor_project_id",
        "anchor_file_path",
        "anchor_plan_uuid",
        "anchor_revision_uuid",
        "anchor_step_uuid",
        "anchor_step_path",
        "anchor_ref_id",
    )
    SUMMARY_FIELDS = (
        "uuid",
        "calendar_entry_uuid",
        "title",
        "status",
        "start_date",
        "end_date",
        "assigned_to",
        "wish_uuid",
        "updated_at",
    )

    calendar_entry_uuid: uuid.UUID
    title: str
    description: str
    status: str
    start_date: str
    end_date: str
    created_by: str
    assigned_to: str | None
    wish_uuid: uuid.UUID | None
    created_at: str
    updated_at: str
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
        """Render the calendar entry as JSON-safe payload."""
        return {
            "uuid": str(self.calendar_entry_uuid),
            "calendar_entry_uuid": str(self.calendar_entry_uuid),
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "wish_uuid": str(self.wish_uuid) if self.wish_uuid is not None else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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

