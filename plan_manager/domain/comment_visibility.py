"""Comment visibility modes and prompt-context reachability gating (C-015)."""
from __future__ import annotations
from enum import Enum

from plan_manager.domain.runtime_validation import RuntimeValidationError


class CommentVisibility(str, Enum):
    AUDIT_ONLY = "audit_only"
    EXECUTION_CONTEXT = "execution_context"
    OWNER_CONTEXT = "owner_context"
    REVIEWER_CONTEXT = "reviewer_context"
    PUBLIC_SUMMARY = "public_summary"


VISIBILITY_MODES: frozenset[str] = frozenset(v.value for v in CommentVisibility)


class PromptContextKind(str, Enum):
    EXECUTION = "execution"
    OWNER = "owner"
    REVIEWER = "reviewer"
    PUBLIC = "public"


PROMPT_CONTEXT_KINDS: frozenset[str] = frozenset(k.value for k in PromptContextKind)


# Which prompt contexts each visibility mode may enter. audit_only enters NONE ({87e5};
# a companion test mandates audit_only comments are excluded from execution prompts).
# A public_summary may enter every context.
VISIBILITY_CONTEXT_MAP: dict[str, frozenset[str]] = {
    "audit_only": frozenset(),
    "execution_context": frozenset({"execution"}),
    "owner_context": frozenset({"owner"}),
    "reviewer_context": frozenset({"reviewer"}),
    "public_summary": frozenset({"execution", "owner", "reviewer", "public"}),
}


def validate_visibility(value: str) -> str:
    """Return value if it is a known CommentVisibility mode, else raise RuntimeValidationError."""
    if value not in VISIBILITY_MODES:
        raise RuntimeValidationError(f"invalid comment visibility: {value!r}; expected one of {sorted(VISIBILITY_MODES)}")
    return value


def may_reach_context(visibility: str, context_kind: str) -> bool:
    """Return True if a comment with the given visibility may enter the given prompt context kind.

    Raises RuntimeValidationError if visibility is not a known CommentVisibility mode or if
    context_kind is not a known PromptContextKind.
    """
    validate_visibility(visibility)
    if context_kind not in PROMPT_CONTEXT_KINDS:
        raise RuntimeValidationError(f"invalid prompt context kind: {context_kind!r}")
    return context_kind in VISIBILITY_CONTEXT_MAP[visibility]


def is_executor_reachable(visibility: str) -> bool:
    """Convenience predicate: return True only if visibility may reach the execution prompt context.

    True for execution_context and public_summary; False for audit_only, owner_context,
    and reviewer_context.
    """
    return may_reach_context(visibility, "execution")
