"""Runtime role vocabulary: the named roles a model binding may target (C-011)."""

from __future__ import annotations
from enum import Enum
from plan_manager.domain.runtime_validation import RuntimeValidationError


class RuntimeRole(str, Enum):
    HRS_AUTHOR = "hrs_author"
    MRS_AUTHOR = "mrs_author"
    GS_AUTHOR = "gs_author"
    TS_AUTHOR = "ts_author"
    AS_AUTHOR = "as_author"
    CODE_EXECUTOR = "code_executor"
    OWNER_REVIEWER = "owner_reviewer"
    CONSCIENCE_REVIEWER = "conscience_reviewer"
    ESCALATION_OWNER = "escalation_owner"
    BUG_INVESTIGATOR = "bug_investigator"
    BUG_FIXER = "bug_fixer"
    VERIFICATION_EXECUTOR = "verification_executor"


RUNTIME_ROLES: frozenset[str] = frozenset(r.value for r in RuntimeRole)


def validate_runtime_role(value: str) -> str:
    """
    Validate that a value is a recognized runtime role.

    Args:
        value: A candidate runtime role string.

    Returns:
        The input value unchanged, if it is a recognized role.

    Raises:
        RuntimeValidationError: If value is not in RUNTIME_ROLES.
    """
    if value in RUNTIME_ROLES:
        return value
    raise RuntimeValidationError(f"{value!r} is not a recognized runtime role")
