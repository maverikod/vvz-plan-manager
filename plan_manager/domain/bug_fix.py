"""Bug fix domain: one concrete fix attempt for a bug; a bug may have several (C-024).

Fixing the source does not automatically fix dependent projects.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError


class BugFixType(str, Enum):
    CODE = "code"
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    DATA = "data"
    DEPENDENCY_UPDATE = "dependency_update"
    DOCUMENTATION = "documentation"
    TEST = "test"
    WORKAROUND = "workaround"
    DEPLOYMENT = "deployment"
    PLAN_CASCADE = "plan_cascade"


class BugFixStatus(str, Enum):
    PROPOSED = "proposed"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    FAILED = "failed"
    PARTIAL = "partial"
    REVERTED = "reverted"
    REJECTED = "rejected"
    VERIFIED = "verified"


BUG_FIX_TYPES: frozenset[str] = frozenset(t.value for t in BugFixType)
BUG_FIX_STATUSES: frozenset[str] = frozenset(s.value for s in BugFixStatus)


@dataclass(frozen=True)
class BugFix:
    fix_uuid: uuid.UUID
    bug_uuid: uuid.UUID
    status: str
    fix_type: str
    summary: str
    implementation_notes: str | None
    source_project_id: uuid.UUID | None
    branch: str | None
    commit_hash: str | None
    pull_request: str | None
    changed_files: list[Any] | None
    tests: list[Any] | None
    author: str
    reviewer: str | None
    started_at: str | None
    implemented_at: str | None
    verified_at: str | None
    verification_method: str | None
    expected_result: str | None
    actual_result: str | None
    passed: bool | None
    revert_info: dict[str, Any] | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.fix_uuid),
            "bug_uuid": str(self.bug_uuid),
            "status": self.status,
            "fix_type": self.fix_type,
            "summary": self.summary,
            "implementation_notes": self.implementation_notes,
            "source_project_id": str(self.source_project_id) if self.source_project_id is not None else None,
            "branch": self.branch,
            "commit_hash": self.commit_hash,
            "pull_request": self.pull_request,
            "changed_files": self.changed_files,
            "tests": self.tests,
            "author": self.author,
            "reviewer": self.reviewer,
            "started_at": self.started_at,
            "implemented_at": self.implemented_at,
            "verified_at": self.verified_at,
            "verification_method": self.verification_method,
            "expected_result": self.expected_result,
            "actual_result": self.actual_result,
            "passed": self.passed,
            "revert_info": self.revert_info,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_fix_type(value: str) -> str:
    if value in BUG_FIX_TYPES:
        return value
    raise RuntimeValidationError(f"invalid bug fix type: {value!r}")


def validate_fix_status(value: str) -> str:
    if value in BUG_FIX_STATUSES:
        return value
    raise RuntimeValidationError(f"invalid bug fix status: {value!r}")
