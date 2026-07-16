"""Chunked retrieval and in-memory reassembly of exported plan files (Path B).

The plan_manager server serves exported files only through the export_read command, which
returns a bounded base64 chunk of one file together with the whole file's size, its sha256
digest, and an end-of-file marker. This module drives that command in a loop to reassemble
each requested file byte-identically in memory. Nothing here touches the filesystem and
nothing here verifies the digest: the reassembled buffer carries the digest the server
declared so a later verification gate can check it before any byte is persisted.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

# Maximum number of DECODED bytes export_read returns in a single chunk.
MAX_CHUNK_BYTES: int = 262144


class ExportChunkProtocolError(RuntimeError):
    """Raised when an export_read chunk sequence cannot be reassembled.

    Covers a chunk that makes no progress before the end-of-file marker, a file whose
    declared size or digest changes between chunks, and a reassembled length that
    disagrees with the declared total size. It names only the plan-relative file name:
    it never carries connection, credential, or server-side path information.
    """

    def __init__(self, filename: str, detail: str) -> None:
        super().__init__(f"export chunk protocol error for {filename!r}: {detail}")
        self.filename = filename
        self.detail = detail


class SupportsExportRead(Protocol):
    """The single export_read call this module needs from a client facade."""

    async def export_read(
        self, plan: str, file: str, offset: int = 0, limit: int = MAX_CHUNK_BYTES
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ReassembledFile:
    """One exported file reassembled in memory, pending digest verification.

    Attributes:
        filename: The plan-relative name of the file, exactly as requested from the server.
        content: The fully reassembled bytes of the file, in original order.
        declared_total_size: The whole-file size the server declared for this file.
        declared_sha256: The whole-file hex sha256 digest the server declared for this file.
    """

    filename: str
    content: bytes
    declared_total_size: int
    declared_sha256: str


async def fetch_export_file(
    client: SupportsExportRead,
    plan: str,
    file: str,
    chunk_limit: int = MAX_CHUNK_BYTES,
) -> ReassembledFile:
    """Reassemble one exported file in memory by looping export_read.

    Args:
        client: An object exposing the export_read coroutine.
        plan: The plan identifier whose export directory owns the file.
        file: The plan-relative path of the file to retrieve.
        chunk_limit: Maximum decoded bytes to request per chunk; must be in [1, 262144].

    Returns:
        The ReassembledFile carrying the file's bytes and the server-declared size and digest.

    Raises:
        ValueError: If chunk_limit is outside [1, 262144].
        ExportChunkProtocolError: If the chunk sequence cannot be reassembled.
    """
    if chunk_limit < 1 or chunk_limit > MAX_CHUNK_BYTES:
        raise ValueError(f"chunk_limit must be an integer in [1, {MAX_CHUNK_BYTES}]")

    buffer = bytearray()
    offset = 0
    declared_total_size: int | None = None
    declared_sha256: str | None = None

    while True:
        response = await client.export_read(
            plan=plan, file=file, offset=offset, limit=chunk_limit
        )
        total_size = int(response["total_size"])
        sha256 = str(response["sha256"])
        if declared_total_size is None:
            declared_total_size = total_size
            declared_sha256 = sha256
        elif total_size != declared_total_size or sha256 != declared_sha256:
            raise ExportChunkProtocolError(
                file, "declared size or digest changed between chunks"
            )

        chunk = base64.b64decode(response["chunk_base64"])
        eof = bool(response["eof"])
        if not chunk and not eof:
            raise ExportChunkProtocolError(
                file, "server returned an empty chunk before the end of the file"
            )

        buffer.extend(chunk)
        offset += len(chunk)
        if eof:
            break

    if declared_total_size is None or declared_sha256 is None:
        raise ExportChunkProtocolError(file, "no chunk was returned")
    if len(buffer) != declared_total_size:
        raise ExportChunkProtocolError(
            file, "reassembled length does not match the declared total size"
        )

    return ReassembledFile(
        filename=file,
        content=bytes(buffer),
        declared_total_size=declared_total_size,
        declared_sha256=declared_sha256,
    )


async def fetch_export_files(
    client: SupportsExportRead,
    plan: str,
    files: Sequence[str],
    chunk_limit: int = MAX_CHUNK_BYTES,
) -> list[ReassembledFile]:
    """Reassemble every named exported file, in the order given.

    Args:
        client: An object exposing the export_read coroutine.
        plan: The plan identifier whose export directory owns the files.
        files: The plan-relative paths of the files to retrieve.
        chunk_limit: Maximum decoded bytes to request per chunk; must be in [1, 262144].

    Returns:
        One ReassembledFile per requested file, in the same order as files.

    Raises:
        ValueError: If chunk_limit is outside [1, 262144].
        ExportChunkProtocolError: If any file's chunk sequence cannot be reassembled.
    """
    return [
        await fetch_export_file(client, plan, file, chunk_limit=chunk_limit)
        for file in files
    ]


__all__ = [
    "MAX_CHUNK_BYTES",
    "ExportChunkProtocolError",
    "ReassembledFile",
    "SupportsExportRead",
    "fetch_export_file",
    "fetch_export_files",
]
