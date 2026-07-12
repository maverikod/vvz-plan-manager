"""External project reference value object and validators (C-032).

Implements C-032 (ExternalProjectReference) — the rule that project
identities are external UUIDs issued by the analysis server and stored
by the planner only as references. This module is pure domain logic:
it performs no database access, emits no DDL, and maintains no local
project catalog or table. A project identity is only ever treated as
an opaque referenced UUID, never as a row this module owns or looks
up.
"""

import uuid
from dataclasses import dataclass


class InvalidProjectReferenceError(ValueError):
    """Raised when a candidate value cannot be parsed as an external project UUID reference."""


@dataclass(frozen=True)
class ExternalProjectReference:
    """An opaque reference to a project owned by the external analysis server.

    This value object never duplicates or maintains a local project
    catalog: it only carries the external UUID issued by the analysis
    server so that the planner can refer to that project without
    owning project data itself.

    Attributes:
        project_uuid: uuid.UUID
            The external project identifier as issued by the analysis
            server.
    """

    project_uuid: uuid.UUID


def parse_external_project_id(value: str) -> ExternalProjectReference:
    """Parse a candidate external project identity string into an ExternalProjectReference.

    Parameters:
        value: str
            A candidate external project identity, expected to be a
            UUID string issued by the analysis server.

    Returns:
        ExternalProjectReference
            Wraps the parsed project_uuid on success.

    Raises:
        InvalidProjectReferenceError
            If value cannot be parsed as a UUID.

    This function performs no catalog lookup and no database access:
    it only parses the string as a UUID and wraps the result.
    """
    try:
        parsed_uuid = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidProjectReferenceError(
            f"{value!r} is not a valid external project UUID reference"
        ) from exc
    return ExternalProjectReference(project_uuid=parsed_uuid)


def is_valid_external_project_id(value: object) -> bool:
    """Return True iff value is a well-formed external project UUID reference.

    Parameters:
        value: object
            A candidate value to check: may be a uuid.UUID instance, a
            str, or any other object.

    Returns:
        bool
            True if value is a uuid.UUID instance, or a str that
            parses as a UUID. False for every other case, including a
            malformed string. This function never raises.

    This function performs no catalog lookup and no database access.
    """
    if isinstance(value, uuid.UUID):
        return True
    if isinstance(value, str):
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True
    return False
