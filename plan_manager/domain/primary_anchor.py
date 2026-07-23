"""Primary anchor domain: the single primary binding of a runtime entity to its subject (C-006)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg

from plan_manager.domain.plan import refuse_if_completed
from plan_manager.domain.runtime_validation import (
    RuntimeValidationError, validate_uuid, validate_file_reference,
    validate_step_in_plan_revision, check_row_exists,
)

# Anchor validation (todo_create/comment/execution_attempt/review_result/
# escalation/bug anchors of anchor_type "plan" or "step") is the one
# plan-resolution path that does not go through
# plan_manager.commands.resolve.resolve_plan_guarded, since it takes a raw
# anchor_plan_uuid rather than a `plan` (name-or-uuid) command parameter.
# The completion-lock check itself is the single shared
# domain.plan.refuse_if_completed (bug c3950b83); this module has no
# private copy of that logic.
_check_plan_not_completed = refuse_if_completed


class InvalidAnchorError(RuntimeValidationError):
    """Raised when a candidate primary anchor fails validate_anchor's shape checks (missing
    required identifier fields for its anchor_type, or an unrecognized anchor_type); maps to
    INVALID_ANCHOR. Delegated checks (validate_uuid, validate_file_reference, check_row_exists,
    validate_step_in_plan_revision) keep raising the generic RuntimeValidationError."""


class PrimaryAnchorType(str, Enum):
    NONE = "none"
    PROJECT = "project"
    FILE = "file"
    PLAN = "plan"
    REVISION = "revision"
    STEP = "step"
    EXECUTION_ATTEMPT = "execution_attempt"
    REVIEW_RESULT = "review_result"
    BUG = "bug"
    BUG_FIX = "bug_fix"
    TODO = "todo"


ANCHOR_TYPES: frozenset[str] = frozenset(t.value for t in PrimaryAnchorType)


@dataclass(frozen=True)
class PrimaryAnchor:
    anchor_type: str
    project_id: uuid.UUID | None = None
    file_path: str | None = None
    plan_uuid: uuid.UUID | None = None
    revision_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None
    step_path: str | None = None
    ref_id: uuid.UUID | None = None


def validate_anchor(conn: psycopg.Connection, anchor: PrimaryAnchor) -> None:
    if anchor.anchor_type == "none":
        if (anchor.project_id is not None or
            anchor.file_path is not None or
            anchor.plan_uuid is not None or
            anchor.revision_uuid is not None or
            anchor.step_uuid is not None or
            anchor.step_path is not None or
            anchor.ref_id is not None):
            raise InvalidAnchorError("none anchor type must have all identifier fields as None")

    elif anchor.anchor_type == "project":
        if anchor.project_id is None:
            raise InvalidAnchorError("project anchor type requires project_id")
        validate_uuid(anchor.project_id)

    elif anchor.anchor_type == "file":
        if anchor.project_id is None or anchor.file_path is None:
            raise InvalidAnchorError("file anchor type requires project_id and file_path")
        validate_file_reference(anchor.project_id, anchor.file_path)

    elif anchor.anchor_type == "plan":
        if anchor.plan_uuid is None:
            raise InvalidAnchorError("plan anchor type requires plan_uuid")
        check_row_exists(conn, "plan", anchor.plan_uuid, frozenset({"plan"}))
        _check_plan_not_completed(conn, anchor.plan_uuid)

    elif anchor.anchor_type == "revision":
        if anchor.revision_uuid is None:
            raise InvalidAnchorError("revision anchor type requires revision_uuid")
        check_row_exists(conn, "revision", anchor.revision_uuid, frozenset({"revision"}))

    elif anchor.anchor_type == "step":
        if anchor.plan_uuid is None or anchor.step_uuid is None:
            raise InvalidAnchorError("step anchor type requires plan_uuid and step_uuid")
        validate_step_in_plan_revision(conn, anchor.plan_uuid, anchor.revision_uuid, anchor.step_uuid)
        _check_plan_not_completed(conn, anchor.plan_uuid)

    elif anchor.anchor_type in ("execution_attempt", "review_result", "bug", "bug_fix"):
        if anchor.ref_id is None:
            raise InvalidAnchorError(f"{anchor.anchor_type} anchor type requires ref_id")
        validate_uuid(anchor.ref_id)

    elif anchor.anchor_type == "todo":
        if anchor.ref_id is None:
            raise InvalidAnchorError("todo anchor type requires ref_id")
        check_row_exists(conn, "todo_item", anchor.ref_id, frozenset({"todo_item"}))

    else:
        raise InvalidAnchorError(f"unknown anchor type: {anchor.anchor_type}")


def anchor_to_columns(anchor: PrimaryAnchor) -> dict[str, Any]:
    return {
        "primary_anchor_type": anchor.anchor_type,
        "anchor_project_id": anchor.project_id,
        "anchor_file_path": anchor.file_path,
        "anchor_plan_uuid": anchor.plan_uuid,
        "anchor_revision_uuid": anchor.revision_uuid,
        "anchor_step_uuid": anchor.step_uuid,
        "anchor_step_path": anchor.step_path,
        "anchor_ref_id": anchor.ref_id,
    }


def anchor_from_columns(columns: dict[str, Any]) -> PrimaryAnchor:
    return PrimaryAnchor(
        anchor_type=columns["primary_anchor_type"],
        project_id=columns["anchor_project_id"],
        file_path=columns["anchor_file_path"],
        plan_uuid=columns["anchor_plan_uuid"],
        revision_uuid=columns["anchor_revision_uuid"],
        step_uuid=columns["anchor_step_uuid"],
        step_path=columns["anchor_step_path"],
        ref_id=columns["anchor_ref_id"],
    )
