"""Domain error registry for plan_manager commands (C-026)."""

import psycopg
from mcp_proxy_adapter.commands.result import ErrorResult

from plan_manager.cascade.close import CommitRefusedError
from plan_manager.cascade.record import CascadeError
from plan_manager.domain.runtime_validation import FrozenTruthMutationError, RuntimeValidationError
from plan_manager.domain.status_model import StatusTransitionError
from plan_manager.scoring.embedding import EmbeddingUnavailable
from plan_manager.scoring.index import ScoreRefusedError
from plan_manager.storage.version_store import VersionStoreError


DOMAIN_CODES: frozenset[str] = frozenset({
    "PLAN_NOT_FOUND",
    "STEP_NOT_FOUND",
    "NODE_NOT_FOUND",
    "AMBIGUOUS_STEP_ID",
    "AMBIGUOUS_PARENT_STEP_ID",
    "CONCEPT_NOT_FOUND",
    "CONCEPT_OUT_OF_SCOPE",
    "COMMON_BLOCK_NOT_FOUND",
    "RELATION_NOT_FOUND",
    "PARAGRAPH_NOT_FOUND",
    "REVISION_NOT_FOUND",
    "SNAPSHOT_NOT_FOUND",
    "CASCADE_REQUIRED",
    "CASCADE_CONFLICT",
    "FROZEN_ARTIFACT",
    "INVALID_STEP_FIELD_SHAPE",
    "INVALID_LEVEL",
    "INVALID_SCOPE",
    "INVALID_ROLE",
    "INVALID_STATUS_FILTER",
    "INVALID_TRANSITION",
    "DUPLICATE_ID",
    "CYCLE_DETECTED",
    "GATE_RED",
    "VERDICT_STALE",
    "EMBEDDINGS_UNAVAILABLE",
    "DEPENDENCY_STEP_NOT_FOUND",
    "SELF_DEPENDENCY",
    "DEPENDENCY_CYCLE",
    "INVALID_DEPENDENCY_SCOPE",
    "IMPORT_INVALID",
    "INVALID_PROJECT_ID",
    "PROJECT_NOT_BOUND_TO_PLAN",
    "PROJECT_ALREADY_BOUND_TO_PLAN",
    "PROJECT_NOT_ATTACHED_TO_PLAN",
    "PRIMARY_PROJECT_NOT_BOUND",
    "DUPLICATE_PROJECT_BINDING",
    "TODO_NOT_FOUND",
    "TODO_LINK_NOT_FOUND",
    "COMMENT_NOT_FOUND",
    "MODEL_BINDING_NOT_FOUND",
    "EXECUTION_ATTEMPT_NOT_FOUND",
    "REVIEW_RESULT_NOT_FOUND",
    "ESCALATION_NOT_FOUND",
    "SELF_CERTIFICATION_FORBIDDEN",
    "BUG_NOT_FOUND",
    "BUG_IMPACT_NOT_FOUND",
    "BUG_FIX_NOT_FOUND",
    "BUG_PROPAGATION_NOT_FOUND",
    "PROJECT_DEPENDENCY_NOT_FOUND",
    "RUNTIME_VALIDATION_ERROR",
    "FROZEN_TRUTH_WRITE",
    "INVALID_ANCHOR",
    "ANCHOR_NOT_FOUND",
    "INVALID_NICE_PRIORITY",
    "DUPLICATE_LINK",
    "LINK_CYCLE",
    "INVALID_VISIBILITY",
    "INVALID_BINDING_SCOPE",
    "INVALID_RUNTIME_ROLE",
    "INVALID_RUNTIME_STATUS_TRANSITION",
    "PROJECT_DEPENDENCY_CYCLE",
    "DUPLICATE_PROJECT_DEPENDENCY",
    "INVALID_FILTER",
    "INVALID_PAGINATION",
})


class DomainCommandError(Exception):
    """Domain-level command error carrying a stable code from DOMAIN_CODES."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        if code not in DOMAIN_CODES:
            raise ValueError(f"unknown domain error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}


def domain_error(code: str, message: str, details: dict | None = None) -> ErrorResult:
    """Build an adapter-compatible ErrorResult for a stable domain error code."""
    if code not in DOMAIN_CODES:
        raise ValueError(f"unknown domain error code: {code}")
    payload = {"domain_code": code}
    if details:
        payload.update(details)
    return ErrorResult(message=message, code=-32000, details=payload)


def map_exception(exc: Exception) -> ErrorResult:
    """Deterministically map a wrapped-operation exception to a domain error."""
    if isinstance(exc, DomainCommandError):
        return domain_error(exc.code, exc.message, exc.details)
    if isinstance(exc, CommitRefusedError):
        return domain_error("GATE_RED", str(exc), {})
    if isinstance(exc, ScoreRefusedError):
        return domain_error("GATE_RED", str(exc), {})
    if isinstance(exc, StatusTransitionError):
        return domain_error("INVALID_TRANSITION", str(exc), {})
    if isinstance(exc, VersionStoreError):
        return domain_error("REVISION_NOT_FOUND", str(exc), {})
    if isinstance(exc, CascadeError):
        return domain_error("CASCADE_CONFLICT", str(exc), {})
    if isinstance(exc, EmbeddingUnavailable):
        return domain_error("EMBEDDINGS_UNAVAILABLE", str(exc), {})
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return domain_error("DUPLICATE_ID", str(exc), {})
    if isinstance(exc, FrozenTruthMutationError):
        return domain_error("FROZEN_TRUTH_WRITE", str(exc), {})
    if isinstance(exc, RuntimeValidationError):
        return domain_error("RUNTIME_VALIDATION_ERROR", str(exc), {})
    raise exc
