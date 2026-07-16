"""Path A verified export tree materialization from the archive.

Verifies the retrieved export archive against its declared sha256 BEFORE
unpacking anything (DeliveryIntegrityContract, MRS concept C-007), then
unpacks the gzip-compressed tar in memory into ordered tree entries that
preserve every original name and relative position (ExportArchive, MRS
concept C-016). Every entry is validated before any entry is materialized,
so a refusal leaves nothing behind. Nothing enumerates an export, so the
archive is the only way Path A obtains a whole tree. Produces no local
files.
"""

from __future__ import annotations
import hashlib
import io
import tarfile
from dataclasses import dataclass


class ArchiveIntegrityError(Exception):
    """Raised when the export archive does not match its declared sha256.

    Raised by :func:`materialize_tree` before any unpacking is attempted,
    per DeliveryIntegrityContract (MRS concept C-007). Nothing is unpacked
    and nothing reaches any destination when this is raised.
    """
    pass


class ArchiveEntryRefusedError(Exception):
    """Raised when an archive entry is refused during validation.

    Raised by :func:`materialize_tree` for an entry whose stored path is
    absolute or contains a '..' segment, or which is neither a regular
    file nor a directory. Per ExportArchive (MRS concept C-016) every
    entry is validated before any entry is materialized, so a refusal
    leaves nothing behind.
    """
    pass


@dataclass(frozen=True)
class TreeEntry:
    """One file of the verified export tree, in memory.

    Attributes:
        relative_path: The entry's POSIX path relative to the plan export
            root, exactly as stored in the archive (for example
            'spec.yaml' or 'G-001-foo/T-001-bar/atomic_steps/A-001-baz.yaml').
        content: The entry's unpacked bytes, byte-for-byte as archived.
        sha256: The hex sha256 digest computed over content.
    """
    relative_path: str
    content: bytes
    sha256: str


def _validate_member(member: tarfile.TarInfo) -> None:
    """Validate one archive member, refusing it if it is unsafe.

    Args:
        member: The archive member to validate.

    Raises:
        ArchiveEntryRefusedError: If member is neither a regular file nor
            a directory, or if member.name starts with '/' or any
            '/'-separated segment of member.name equals '..'.
    """
    if not member.isfile() and not member.isdir():
        raise ArchiveEntryRefusedError(
            f"archive entry is neither a regular file nor a directory: {member.name!r}"
        )

    if member.name.startswith('/') or '..' in member.name.split('/'):
        raise ArchiveEntryRefusedError(
            f"archive entry escapes the destination: {member.name!r}"
        )


def materialize_tree(
    archive_bytes: bytes,
    declared_archive_sha256: str,
) -> list[TreeEntry]:
    """Verify the archive, then unpack its tree in memory.

    Validation is exhaustive and precedes materialization: every member is
    validated before any member's bytes are read, so a refusal returns
    nothing and leaves nothing behind (ExportArchive, MRS concept C-016).

    Args:
        archive_bytes: The already-retrieved archive content, a
            gzip-compressed tar.
        declared_archive_sha256: The archive's declared whole-archive
            sha256 hex digest.

    Returns:
        The tree entries in the order the archive stores them, each
        carrying its export-root-relative path, its unpacked content, and
        the sha256 computed over that content. Directory members are
        skipped rather than returned.

    Raises:
        ArchiveIntegrityError: If sha256(archive_bytes) does not equal
            declared_archive_sha256. Raised before any unpacking; nothing
            is unpacked.
        ArchiveEntryRefusedError: If ANY member is refused by
            _validate_member. Raised during the validation pass, before
            any member's bytes are read, so no entry is returned.
    """
    computed = hashlib.sha256(archive_bytes).hexdigest()

    if computed != declared_archive_sha256:
        raise ArchiveIntegrityError(
            f"archive digest mismatch: expected {declared_archive_sha256}, computed {computed}"
        )

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        # Validation pass: exhaustive check before any materialization
        members = tar.getmembers()
        for member in members:
            _validate_member(member)

        # Materialization pass: extract bytes and build entries
        result: list[TreeEntry] = []
        for member in members:
            if member.isdir():
                continue

            extracted_file = tar.extractfile(member)
            content = extracted_file.read()
            entry_digest = hashlib.sha256(content).hexdigest()
            result.append(
                TreeEntry(
                    relative_path=member.name,
                    content=content,
                    sha256=entry_digest,
                )
            )

        return result
