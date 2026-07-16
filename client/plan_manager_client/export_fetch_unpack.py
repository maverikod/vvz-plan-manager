"""Local unpack of the verified export archive, and the retrieval report (Path B).

The whole export tree arrives as one gzip-compressed tar whose entries carry paths relative
to the plan's export directory. This module expands it onto the caller's filesystem so every
file reappears byte-for-byte under its original name and relative position, and reports what
landed. The archive's digest is verified before this module runs; the duty here is boundary
safety: every entry is checked BEFORE anything is written, so an archive that would escape
the destination is refused whole rather than leaving a partial tree behind.
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from plan_manager_client.export_fetch_verify import VerifiedFile


class ExportUnpackError(RuntimeError):
    """Raised when an archive cannot be unpacked safely.

    Covers an entry whose path would resolve outside the destination, an entry that is
    neither a regular file nor a directory, and an archive whose bytes are not a readable
    gzip tar. It names only the offending relative entry path: it never carries
    connection, credential, or server-side path information.
    """

    def __init__(self, entry: str, detail: str) -> None:
        super().__init__(f"cannot unpack archive entry {entry!r}: {detail}")
        self.entry = entry
        self.detail = detail


@dataclass(frozen=True)
class RetrievalReport:
    """What the local fetch delivered and what it did not.

    Attributes:
        unpacked: The relative paths written beneath the destination, in archive order.
        not_retrieved: A description per item that was not retrieved, naming the stage
            at which it failed. Empty when the whole tree was delivered.
    """

    unpacked: tuple[str, ...]
    not_retrieved: tuple[str, ...]


def _resolved_within(destination: Path, entry_name: str) -> Path:
    """Resolve an entry path under the destination, refusing any escape.

    Args:
        destination: The already-resolved destination directory.
        entry_name: The archive entry's relative path.

    Returns:
        The resolved target path, guaranteed to lie inside destination.

    Raises:
        ExportUnpackError: If the entry is absolute or resolves outside destination.
    """
    if entry_name.startswith("/") or Path(entry_name).is_absolute():
        raise ExportUnpackError(entry_name, "entry path is absolute")
    target = (destination / entry_name).resolve()
    if target != destination and destination not in target.parents:
        raise ExportUnpackError(entry_name, "entry path would escape the destination")
    return target


def unpack_verified_archive(
    archive: VerifiedFile,
    destination: str | Path,
) -> list[str]:
    """Expand a verified gzip-tar archive under destination, preserving relative paths.

    Every entry is validated before any byte is written, so a refusal leaves nothing
    behind. Entries are reproduced under their original names and relative positions.

    Args:
        archive: The verified archive, carrying its plan-relative name and bytes.
        destination: The local directory under which the tree is reproduced; it is
            created if absent.

    Returns:
        The relative paths of the files written, in archive order.

    Raises:
        ExportUnpackError: If the bytes are not a readable gzip tar, or any entry is
            absolute, escapes the destination, or is neither a regular file nor a
            directory.
    """
    root = Path(destination).resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.content), mode="r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if not (member.isfile() or member.isdir()):
                    raise ExportUnpackError(
                        member.name, "entry is neither a regular file nor a directory"
                    )
                _resolved_within(root, member.name)

            root.mkdir(parents=True, exist_ok=True)
            written: list[str] = []
            for member in members:
                target = _resolved_within(root, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ExportUnpackError(member.name, "entry carries no readable content")
                with extracted:
                    target.write_bytes(extracted.read())
                written.append(member.name)
    except tarfile.TarError as error:
        raise ExportUnpackError(archive.filename, f"archive is not a readable gzip tar: {error}") from error
    return written


def build_retrieval_report(
    unpacked: Sequence[str],
    not_retrieved: Sequence[str] = (),
) -> RetrievalReport:
    """Build the report of what the local fetch delivered.

    Args:
        unpacked: The relative paths written beneath the destination.
        not_retrieved: Descriptions of what was not retrieved, each naming the stage at
            which it failed; empty when the whole tree was delivered.

    Returns:
        The RetrievalReport carrying both sets.
    """
    return RetrievalReport(
        unpacked=tuple(unpacked),
        not_retrieved=tuple(not_retrieved),
    )


__all__ = [
    "ExportUnpackError",
    "RetrievalReport",
    "build_retrieval_report",
    "unpack_verified_archive",
]
