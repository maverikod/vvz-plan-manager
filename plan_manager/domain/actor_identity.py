"""Structured audit actor identity: shape detection and per-component validation for the changed_by value recorded by the runtime audit surface (C-014)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from plan_manager.domain.runtime_validation import RuntimeValidationError

ROLE_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_]*$")
STEP_PATH_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z]+-[0-9]+(?:/[A-Za-z]+-[0-9]+)*$")


@dataclass(frozen=True)
class ActorIdentity:
    """A parsed structured changed_by identity of the form role@step_path@attempt_uuid (C-014).

    Attributes:
        role: The machine-writer role name, e.g. "writer".
        step_path: The step path the mutation was performed under, e.g. "G-001/T-001/A-002".
        attempt_uuid: The execution-attempt identifier the mutation is traceable to.
    """

    role: str
    step_path: str
    attempt_uuid: uuid.UUID


def parse_actor_identity(value: str) -> ActorIdentity | None:
    """Detect and parse the structured changed_by shape role@step_path@attempt_uuid.

    Splits ``value`` on "@". A value that does not split into exactly three
    non-empty components is a plain actor string, not the structured shape,
    and this function returns ``None`` for it without raising. A value that
    DOES split into exactly three non-empty components is the structured
    shape and is validated component-by-component: the first component
    against ROLE_PATTERN, the second against STEP_PATH_PATTERN, and the
    third parsed via ``uuid.UUID``. If all three validate, the parsed
    ``ActorIdentity`` is returned. If the shape is present (three non-empty
    components) but any component fails its check, this function raises
    ``RuntimeValidationError`` — a matching three-part shape is never
    silently treated as a plain string.

    Parameters:
        value: The candidate changed_by string.

    Returns:
        ActorIdentity | None: The parsed identity when ``value`` has the
        valid structured shape; ``None`` when ``value`` does not have the
        three-non-empty-component shape at all (i.e. it is a plain actor
        string).

    Raises:
        RuntimeValidationError: If ``value`` has the three-non-empty-component
            shape but the role, step_path, or attempt_uuid component is
            malformed.
    """
    parts = value.split("@")
    if len(parts) != 3 or not all(parts):
        return None
    role, step_path, attempt_uuid_str = parts
    if not ROLE_PATTERN.match(role):
        raise RuntimeValidationError(
            f"malformed structured actor identity role component: {role!r}"
        )
    if not STEP_PATH_PATTERN.match(step_path):
        raise RuntimeValidationError(
            f"malformed structured actor identity step_path component: {step_path!r}"
        )
    try:
        attempt_uuid = uuid.UUID(attempt_uuid_str)
    except (ValueError, AttributeError):
        raise RuntimeValidationError(
            f"malformed structured actor identity attempt_uuid component: {attempt_uuid_str!r}"
        )
    return ActorIdentity(role=role, step_path=step_path, attempt_uuid=attempt_uuid)


def validate_actor_identity(value: str) -> str:
    """Validate a changed_by value for the runtime audit surface (C-014).

    Calls ``parse_actor_identity`` purely for its validating side effect: if
    ``value`` has the structured three-component shape, malformed components
    raise; a well-formed structured value or a plain (non-structured) string
    both pass through unchanged. This is the single entry point the audit
    surface calls before persisting a changed_by value.

    Parameters:
        value: The candidate changed_by value.

    Returns:
        str: ``value`` unchanged, in both accepting cases (valid structured
        value or plain string).

    Raises:
        RuntimeValidationError: If ``value`` is not a ``str``, or if it has
            the three-component structured shape but a component is
            malformed.
    """
    if not isinstance(value, str):
        raise RuntimeValidationError(
            f"changed_by must be a str, got {type(value).__name__}"
        )
    parse_actor_identity(value)  # side effect only: raises on malformed structured shape
    return value
