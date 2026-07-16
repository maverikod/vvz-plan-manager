"""Whole-file digest verification gate for Path B export retrieval.

Nothing retrieved from the server may reach the caller's filesystem before its whole-file
sha256 has been recomputed locally and matched against the digest the server declared for
that file. This module is that gate: it turns a reassembled buffer into a verified file, or
raises the delivery contract's distinct integrity error. The error is deliberately its own
type so that a digest mismatch is never confused with a transport or protocol failure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from plan_manager_client.export_fetch_chunks import ReassembledFile


class ExportIntegrityError(RuntimeError):
    """Raised when a reassembled file's sha256 does not match its declared digest.

    This is the distinct integrity error of the delivery contract: it aborts retrieval of
    the offending file and is raised for no other kind of failure. It names only the
    plan-relative file name and the two digests: it never carries connection, credential,
    or server-side path information.
    """

    def __init__(self, filename: str, expected_sha256: str, actual_sha256: str) -> None:
        super().__init__(
            f"integrity check failed for {filename!r}: "
            f"expected sha256 {expected_sha256}, computed {actual_sha256}"
        )
        self.filename = filename
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256


@dataclass(frozen=True)
class VerifiedFile:
    """One exported file whose content matched the digest the server declared for it.

    Attributes:
        filename: The plan-relative name of the file, unchanged from retrieval.
        content: The verified bytes of the file, eligible for persistence.
    """

    filename: str
    content: bytes


def verify_reassembled_file(reassembled: ReassembledFile) -> VerifiedFile:
    """Verify one reassembled file's whole-file sha256 against its declared digest.

    Args:
        reassembled: The in-memory file carrying the server-declared digest.

    Returns:
        The VerifiedFile, eligible for persistence, when the digests match.

    Raises:
        ExportIntegrityError: When the computed digest differs from the declared one.
    """
    actual_sha256 = hashlib.sha256(reassembled.content).hexdigest()
    if actual_sha256 != reassembled.declared_sha256:
        raise ExportIntegrityError(
            reassembled.filename, reassembled.declared_sha256, actual_sha256
        )
    return VerifiedFile(filename=reassembled.filename, content=reassembled.content)


def verify_reassembled_files(
    reassembled: Iterable[ReassembledFile],
) -> tuple[list[VerifiedFile], list[ExportIntegrityError]]:
    """Verify every reassembled file independently, collecting both outcomes.

    A mismatch on one file does not stop the others from being verified, so the caller
    can report precisely which files passed and which did not.

    Args:
        reassembled: The in-memory files to verify.

    Returns:
        A tuple of the files that verified and the integrity errors raised for those
        that did not, each list in the order the inputs were given.
    """
    verified: list[VerifiedFile] = []
    failures: list[ExportIntegrityError] = []
    for item in reassembled:
        try:
            verified.append(verify_reassembled_file(item))
        except ExportIntegrityError as error:
            failures.append(error)
    return verified, failures


__all__ = [
    "ExportIntegrityError",
    "VerifiedFile",
    "verify_reassembled_file",
    "verify_reassembled_files",
]
