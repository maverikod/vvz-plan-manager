"""Runtime comment domain: append-oriented notes with kinds, anchor snapshot, and supersede history (C-014)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError


class CommentKind(str, Enum):
    """Kind vocabulary for RuntimeComment: 12 distinct comment/note types."""

    COMMENT = "comment"
    OBSERVATION = "observation"
    WARNING = "warning"
    BLOCKER = "blocker"
    DECISION = "decision"
    REVIEW = "review"
    QUESTION = "question"
    ANSWER = "answer"
    EVIDENCE = "evidence"
    ESCALATION = "escalation"
    EXECUTION_NOTE = "execution_note"
    VERIFICATION_NOTE = "verification_note"


COMMENT_KINDS: frozenset[str] = frozenset(k.value for k in CommentKind)


class CommentAnchorType(str, Enum):
    """Anchor target kinds for RuntimeComment: 11 distinct subject types (no 'none')."""

    PLAN = "plan"
    REVISION = "revision"
    STEP = "step"
    PROJECT = "project"
    FILE = "file"
    TODO = "todo"
    BUG = "bug"
    BUG_FIX = "bug_fix"
    EXECUTION_ATTEMPT = "execution_attempt"
    REVIEW_RESULT = "review_result"
    ESCALATION = "escalation"


COMMENT_ANCHOR_TYPES: frozenset[str] = frozenset(t.value for t in CommentAnchorType)


@dataclass(frozen=True)
class RuntimeComment:
    """
    Domain record for a runtime comment (C-014).

    Append-oriented, immutable record representing a comment/note attached to one of
    11 anchor target kinds. Editing creates a new superseding record; history is never lost.
    A comment is never a field of another object — it is always a separate persisted entity
    referencing its subject via anchor identifiers.
    """

    comment_uuid: uuid.UUID
    primary_anchor_type: str
    anchor_project_id: uuid.UUID | None
    anchor_file_path: str | None
    anchor_plan_uuid: uuid.UUID | None
    anchor_revision_uuid: uuid.UUID | None
    anchor_step_uuid: uuid.UUID | None
    anchor_step_path: str | None
    anchor_ref_id: uuid.UUID | None
    kind: str
    visibility: str
    author: str
    body: str
    resolved: bool | None
    supersedes_comment_uuid: uuid.UUID | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """
        Serialize to a payload dict.

        UUID fields are rendered as strings (or None); string and bool fields pass through as-is.
        Timestamps are already ISO-format strings.
        """
        return {
            "comment_uuid": str(self.comment_uuid) if self.comment_uuid is not None else None,
            "primary_anchor_type": self.primary_anchor_type,
            "anchor_project_id": str(self.anchor_project_id) if self.anchor_project_id is not None else None,
            "anchor_file_path": self.anchor_file_path,
            "anchor_plan_uuid": str(self.anchor_plan_uuid) if self.anchor_plan_uuid is not None else None,
            "anchor_revision_uuid": str(self.anchor_revision_uuid) if self.anchor_revision_uuid is not None else None,
            "anchor_step_uuid": str(self.anchor_step_uuid) if self.anchor_step_uuid is not None else None,
            "anchor_step_path": self.anchor_step_path,
            "anchor_ref_id": str(self.anchor_ref_id) if self.anchor_ref_id is not None else None,
            "kind": self.kind,
            "visibility": self.visibility,
            "author": self.author,
            "body": self.body,
            "resolved": self.resolved,
            "supersedes_comment_uuid": str(self.supersedes_comment_uuid) if self.supersedes_comment_uuid is not None else None,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_comment_kind(value: str) -> str:
    """
    Validate that a string is a valid CommentKind.

    Args:
        value: the candidate kind string.

    Returns:
        value unchanged if it is in COMMENT_KINDS.

    Raises:
        RuntimeValidationError: if value is not in COMMENT_KINDS.
    """
    if value in COMMENT_KINDS:
        return value
    raise RuntimeValidationError(f"Invalid comment kind: {value!r}; expected one of {sorted(COMMENT_KINDS)}")


def validate_comment_anchor_type(value: str) -> str:
    """
    Validate that a string is a valid CommentAnchorType.

    Args:
        value: the candidate anchor type string.

    Returns:
        value unchanged if it is in COMMENT_ANCHOR_TYPES.

    Raises:
        RuntimeValidationError: if value is not in COMMENT_ANCHOR_TYPES.
    """
    if value in COMMENT_ANCHOR_TYPES:
        return value
    raise RuntimeValidationError(f"Invalid comment anchor type: {value!r}; expected one of {sorted(COMMENT_ANCHOR_TYPES)}")
