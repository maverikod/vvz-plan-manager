"""Bug source anchor: the single primary origin of a defect, separate from what it affects (C-021)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg

from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor


class BugSourceType(str, Enum):
    PROJECT = "project"
    FILE = "file"
    PLAN = "plan"
    REVISION = "revision"
    STEP = "step"
    COMMAND = "command"
    RUNTIME_SERVICE = "runtime_service"
    EXECUTION_ATTEMPT = "execution_attempt"
    UNIDENTIFIED = "unidentified"


BUG_SOURCE_TYPES: frozenset[str] = frozenset(t.value for t in BugSourceType)

# The source types that reuse the G-002 PrimaryAnchor (C-006) validation. Their string values EQUAL
# the matching PrimaryAnchorType values, so validate_bug_source delegates to validate_anchor.
ANCHOR_DELEGATED_TYPES: frozenset[str] = frozenset({"project", "file", "plan", "revision", "step", "execution_attempt"})


@dataclass(frozen=True)
class BugSource:
    """A bug source anchor: the single primary origin of a defect, separate from what it affects.

    A bug has exactly ONE primary source anchor (this class), but MANY impact records.
    The source may be a project, file, plan, revision, step, command, runtime service,
    execution attempt, or unidentified. This design strictly separates WHERE the defect
    originates from WHAT it affects.
    """
    source_type: str
    project_id: uuid.UUID | None = None
    file_path: str | None = None
    plan_uuid: uuid.UUID | None = None
    revision_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None
    step_path: str | None = None
    ref_id: uuid.UUID | None = None
    command: str | None = None
    service: str | None = None


def validate_bug_source(conn: psycopg.Connection, source: BugSource) -> None:
    """Validate a BugSource according to its source type.

    Raises RuntimeValidationError if:
    - source_type is not a valid BugSourceType value
    - for anchor-delegated types (project, file, plan, revision, step, execution_attempt):
      the corresponding PrimaryAnchor fails validation via validate_anchor()
    - for command: command is not a non-empty string, or other identifier fields are not None
    - for runtime_service: service is not a non-empty string, or other identifier fields are not None
    - for unidentified: any identifier field is not None

    Parameters:
        conn: Database connection (passed through to validate_anchor for existence checks)
        source: BugSource to validate

    Raises:
        RuntimeValidationError: on any validation violation
    """
    # Rule 1: Check source_type is valid
    if source.source_type not in BUG_SOURCE_TYPES:
        raise RuntimeValidationError(f"Unknown bug source type: {source.source_type}")

    # Rule 2: Delegate to validate_anchor for anchor-delegated types
    if source.source_type in ANCHOR_DELEGATED_TYPES:
        anchor = PrimaryAnchor(
            anchor_type=source.source_type,
            project_id=source.project_id,
            file_path=source.file_path,
            plan_uuid=source.plan_uuid,
            revision_uuid=source.revision_uuid,
            step_uuid=source.step_uuid,
            step_path=source.step_path,
            ref_id=source.ref_id,
        )
        validate_anchor(conn, anchor)
        return

    # Rule 3: Validate "command" type
    if source.source_type == "command":
        if not source.command or not source.command.strip():
            raise RuntimeValidationError("command source requires a non-empty command string")
        if source.project_id is not None:
            raise RuntimeValidationError("command source must have project_id=None")
        if source.file_path is not None:
            raise RuntimeValidationError("command source must have file_path=None")
        if source.plan_uuid is not None:
            raise RuntimeValidationError("command source must have plan_uuid=None")
        if source.revision_uuid is not None:
            raise RuntimeValidationError("command source must have revision_uuid=None")
        if source.step_uuid is not None:
            raise RuntimeValidationError("command source must have step_uuid=None")
        if source.step_path is not None:
            raise RuntimeValidationError("command source must have step_path=None")
        if source.ref_id is not None:
            raise RuntimeValidationError("command source must have ref_id=None")
        if source.service is not None:
            raise RuntimeValidationError("command source must have service=None")
        return

    # Rule 4: Validate "runtime_service" type
    if source.source_type == "runtime_service":
        if not source.service or not source.service.strip():
            raise RuntimeValidationError("runtime_service source requires a non-empty service string")
        if source.project_id is not None:
            raise RuntimeValidationError("runtime_service source must have project_id=None")
        if source.file_path is not None:
            raise RuntimeValidationError("runtime_service source must have file_path=None")
        if source.plan_uuid is not None:
            raise RuntimeValidationError("runtime_service source must have plan_uuid=None")
        if source.revision_uuid is not None:
            raise RuntimeValidationError("runtime_service source must have revision_uuid=None")
        if source.step_uuid is not None:
            raise RuntimeValidationError("runtime_service source must have step_uuid=None")
        if source.step_path is not None:
            raise RuntimeValidationError("runtime_service source must have step_path=None")
        if source.ref_id is not None:
            raise RuntimeValidationError("runtime_service source must have ref_id=None")
        if source.command is not None:
            raise RuntimeValidationError("runtime_service source must have command=None")
        return

    # Rule 5: Validate "unidentified" type (the only remaining case)
    if source.source_type == "unidentified":
        if source.project_id is not None:
            raise RuntimeValidationError("unidentified source must have project_id=None")
        if source.file_path is not None:
            raise RuntimeValidationError("unidentified source must have file_path=None")
        if source.plan_uuid is not None:
            raise RuntimeValidationError("unidentified source must have plan_uuid=None")
        if source.revision_uuid is not None:
            raise RuntimeValidationError("unidentified source must have revision_uuid=None")
        if source.step_uuid is not None:
            raise RuntimeValidationError("unidentified source must have step_uuid=None")
        if source.step_path is not None:
            raise RuntimeValidationError("unidentified source must have step_path=None")
        if source.ref_id is not None:
            raise RuntimeValidationError("unidentified source must have ref_id=None")
        if source.command is not None:
            raise RuntimeValidationError("unidentified source must have command=None")
        if source.service is not None:
            raise RuntimeValidationError("unidentified source must have service=None")
        return


def bug_source_to_columns(source: BugSource) -> dict[str, Any]:
    """Convert a BugSource to a dictionary of database column name/value pairs.

    Returns a dict with exactly ten keys mapping BugSource fields to the bug_report
    table's source columns. Values are passed through unchanged (UUIDs remain as
    uuid.UUID objects, not strings).

    Parameters:
        source: BugSource to convert

    Returns:
        dict with keys: source_anchor_type, source_project_id, source_file_path,
        source_plan_uuid, source_revision_uuid, source_step_uuid, source_step_path,
        source_ref_id, source_command, source_service
    """
    return {
        "source_anchor_type": source.source_type,
        "source_project_id": source.project_id,
        "source_file_path": source.file_path,
        "source_plan_uuid": source.plan_uuid,
        "source_revision_uuid": source.revision_uuid,
        "source_step_uuid": source.step_uuid,
        "source_step_path": source.step_path,
        "source_ref_id": source.ref_id,
        "source_command": source.command,
        "source_service": source.service,
    }


def bug_source_from_columns(columns: dict[str, Any]) -> BugSource:
    """Construct a BugSource from a dictionary of database column name/value pairs.

    The exact inverse of bug_source_to_columns. Reads all ten expected keys from
    the columns dict (using direct indexing; KeyError is raised if any key is missing).

    Parameters:
        columns: dict with keys: source_anchor_type, source_project_id, source_file_path,
                 source_plan_uuid, source_revision_uuid, source_step_uuid, source_step_path,
                 source_ref_id, source_command, source_service

    Returns:
        Constructed BugSource
    """
    return BugSource(
        source_type=columns["source_anchor_type"],
        project_id=columns["source_project_id"],
        file_path=columns["source_file_path"],
        plan_uuid=columns["source_plan_uuid"],
        revision_uuid=columns["source_revision_uuid"],
        step_uuid=columns["source_step_uuid"],
        step_path=columns["source_step_path"],
        ref_id=columns["source_ref_id"],
        command=columns["source_command"],
        service=columns["source_service"],
    )
