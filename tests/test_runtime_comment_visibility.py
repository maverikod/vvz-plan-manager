from __future__ import annotations

import pytest

from plan_manager.domain.comment_visibility import (
    CommentVisibility,
    PromptContextKind,
    VISIBILITY_CONTEXT_MAP,
    PROMPT_CONTEXT_KINDS,
    may_reach_context,
    is_executor_reachable,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.runtime_comment import (
    CommentAnchorType,
    COMMENT_ANCHOR_TYPES,
    validate_comment_anchor_type,
)


# Main test section: comment visibility coverage

def test_audit_only_reaches_no_execution_context() -> None:
    """Audit-only comments must be excluded from the execution prompt (HRS {d118} bullet 22)."""
    assert may_reach_context("audit_only", "execution") is False


def test_audit_only_reaches_no_context_at_all() -> None:
    """Audit-only comments must reach NO prompt context at all (HRS {d118} bullet 22)."""
    for context in PROMPT_CONTEXT_KINDS:
        assert may_reach_context("audit_only", context) is False


def test_execution_context_reaches_execution() -> None:
    """Execution-context comments reach only the execution context."""
    assert may_reach_context("execution_context", "execution") is True
    assert may_reach_context("execution_context", "owner") is False


def test_public_summary_reaches_every_context() -> None:
    """Public-summary comments reach every prompt context."""
    for context in PROMPT_CONTEXT_KINDS:
        assert may_reach_context("public_summary", context) is True


def test_owner_context_reaches_only_owner() -> None:
    """Owner-context comments reach only the owner context."""
    assert may_reach_context("owner_context", "owner") is True
    assert may_reach_context("owner_context", "execution") is False
    assert may_reach_context("owner_context", "reviewer") is False


def test_reviewer_context_reaches_only_reviewer() -> None:
    """Reviewer-context comments reach only the reviewer context."""
    assert may_reach_context("reviewer_context", "reviewer") is True
    assert may_reach_context("reviewer_context", "execution") is False


def test_may_reach_context_rejects_invalid_visibility() -> None:
    """Invalid visibility values must raise RuntimeValidationError."""
    with pytest.raises(RuntimeValidationError):
        may_reach_context("not_a_real_visibility", "execution")


def test_may_reach_context_rejects_invalid_context_kind() -> None:
    """Invalid context kinds must raise RuntimeValidationError."""
    with pytest.raises(RuntimeValidationError):
        may_reach_context("execution_context", "not_a_real_context")


def test_is_executor_reachable_true_cases() -> None:
    """Only execution_context and public_summary are executor-reachable."""
    assert is_executor_reachable("execution_context") is True
    assert is_executor_reachable("public_summary") is True


def test_is_executor_reachable_false_cases() -> None:
    """Audit-only, owner-context, and reviewer-context are not executor-reachable (HRS {d118} bullets 7 & 22)."""
    assert is_executor_reachable("audit_only") is False
    assert is_executor_reachable("owner_context") is False
    assert is_executor_reachable("reviewer_context") is False


def test_visibility_context_map_matches_enum_members() -> None:
    """Every visibility mode enum member must have a corresponding context map entry."""
    assert set(VISIBILITY_CONTEXT_MAP.keys()) == {v.value for v in CommentVisibility}


# Additional required tests: comment anchor vocabulary (HRS {b5dj})

def test_comment_anchor_type_escalation_is_accepted() -> None:
    """An escalation-anchored comment is accepted at the vocabulary level (HRS {b5dj})."""
    assert validate_comment_anchor_type("escalation") == "escalation"
    assert "escalation" in COMMENT_ANCHOR_TYPES
    assert CommentAnchorType.ESCALATION.value == "escalation"


def test_comment_anchor_type_none_is_rejected() -> None:
    """'none' is NOT a valid comment anchor: a comment always attaches to a subject."""
    assert "none" not in COMMENT_ANCHOR_TYPES
    with pytest.raises(RuntimeValidationError):
        validate_comment_anchor_type("none")


def test_comment_anchor_vocabulary_is_exactly_the_eleven_kinds() -> None:
    """The comment anchor vocabulary must contain exactly the eleven defined anchor types."""
    assert COMMENT_ANCHOR_TYPES == frozenset({
        "plan", "revision", "step", "project", "file", "todo", "bug",
        "bug_fix", "execution_attempt", "review_result", "escalation",
    })
