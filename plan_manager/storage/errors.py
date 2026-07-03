"""Domain storage error types and referential-integrity verdict translation."""

import psycopg


class StorageError(Exception):
    """Base class for all domain-level storage errors."""


class NotFoundError(StorageError):
    """Raised when a lookup by scoped name or UUID finds no matching row."""


class DuplicateNameError(StorageError):
    """Raised when a write would violate a uniqueness constraint (e.g. a scoped name already in use)."""


class ReferentialIntegrityError(StorageError):
    """Raised when a write references an identifier that does not resolve to an existing entity."""


def translate_integrity_error(exc: psycopg.errors.IntegrityError) -> StorageError:
    """Translate a psycopg IntegrityError into a domain-level StorageError.

    Parameters:
        exc: psycopg.errors.IntegrityError
            The integrity error raised by psycopg after a rejected write.

    Returns:
        StorageError
            - ReferentialIntegrityError(str(exc)) if exc is an instance of
              psycopg.errors.ForeignKeyViolation.
            - DuplicateNameError(str(exc)) if exc is an instance of
              psycopg.errors.UniqueViolation.
            - StorageError(str(exc)) for any other
              psycopg.errors.IntegrityError instance.

    This function returns the translated exception instance; it does not
    raise it. The caller is responsible for raising the returned
    exception.
    """
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return ReferentialIntegrityError(str(exc))
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return DuplicateNameError(str(exc))
    return StorageError(str(exc))
