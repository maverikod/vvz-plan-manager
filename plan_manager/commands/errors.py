"""Domain error registry for plan_manager commands (C-026)."""

import psycopg
from mcp_proxy_adapter.commands.result import ErrorResult

from plan_manager.cascade.close import CommitRefusedError
from plan_manager.cascade.record import CascadeError
from plan_manager.domain.bug_status_transitions import BugStatusTransitionError
from plan_manager.domain.model_binding import InvalidBindingScopeError, InvalidRuntimeRoleError
from plan_manager.domain.primary_anchor import InvalidAnchorError
from plan_manager.domain.runtime_validation import (
    FrozenTruthMutationError, InvalidNicePriorityError, RuntimeValidationError,
)
from plan_manager.domain.status_model import StatusTransitionError
from plan_manager.scoring.embedding import EmbeddingUnavailable
from plan_manager.scoring.index import ScoreRefusedError
from plan_manager.storage.version_store import VersionStoreError
from plan_manager.views.dependency_graph import GraphIntegrityError
from plan_manager.views.prompt_assembly import PromptAssemblyError


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
    "PLAN_NOT_FULLY_FROZEN",
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
    "PROMPT_ASSEMBLY_FAILED",
    "GRAPH_CORRUPTED_CHAIN",
    "EXPORT_FILE_NOT_FOUND",
    "EXPORT_PATH_INVALID",
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
    # Most-specific RuntimeValidationError subclasses must be checked before the generic
    # RuntimeValidationError branch below, so a documented code is reported instead of the
    # generic RUNTIME_VALIDATION_ERROR fallback.
    if isinstance(exc, InvalidAnchorError):
        return domain_error("INVALID_ANCHOR", str(exc), {})
    if isinstance(exc, InvalidNicePriorityError):
        return domain_error("INVALID_NICE_PRIORITY", str(exc), {})
    if isinstance(exc, InvalidBindingScopeError):
        return domain_error("INVALID_BINDING_SCOPE", str(exc), {})
    if isinstance(exc, InvalidRuntimeRoleError):
        return domain_error("INVALID_RUNTIME_ROLE", str(exc), {})
    if isinstance(exc, BugStatusTransitionError):
        return domain_error(
            "INVALID_RUNTIME_STATUS_TRANSITION",
            str(exc),
            {"current_status": exc.current_status, "legal_targets": exc.legal_targets},
        )
    if isinstance(exc, RuntimeValidationError):
        return domain_error("RUNTIME_VALIDATION_ERROR", str(exc), {})
    # Prompt-assembly and graph-integrity failures are typed ValueError subclasses; map them to
    # documented domain codes instead of leaking a raw -32603 (both are checked before any generic
    # ValueError fallthrough because there is none — unknown exceptions are re-raised below).
    if isinstance(exc, PromptAssemblyError):
        return domain_error("PROMPT_ASSEMBLY_FAILED", str(exc), {})
    if isinstance(exc, GraphIntegrityError):
        return domain_error("GRAPH_CORRUPTED_CHAIN", str(exc), {})
    raise exc
