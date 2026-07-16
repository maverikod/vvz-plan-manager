"""Export production request and archive reference resolution (Path B).

Nothing on the plan_manager command surface enumerates an export: plan_export reports a
COUNT of files written, never their names. The whole export tree is therefore delivered as
ONE archive under one known name, and this module obtains the reference to it: it drives the
queue-bound export production to completion, then asks the synchronous archive command to
pack the tree it just wrote, and returns the archive's name, size and declared digest. No
archive byte is read here, and no file list is requested, derived, or guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SupportsExportProduction(Protocol):
    """The two calls this module needs from a client facade."""

    async def plan_export(
        self, plan: str, revision: str | None = None
    ) -> dict[str, Any]:
        ...

    async def export_archive(self, plan: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ExportArchiveRef:
    """The reference to one archive holding a whole export tree.

    Attributes:
        name: The archive's plan-relative name, to be passed to the byte source as-is.
        size_bytes: The archive's size in bytes as the server reported it.
        sha256: The hex sha256 digest of the WHOLE archive, declared by the server.
        file_count: The number of export-tree files packed into the archive.
    """

    name: str
    size_bytes: int
    sha256: str
    file_count: int


async def request_export_archive(
    client: SupportsExportProduction,
    plan: str,
    revision: str | None = None,
) -> ExportArchiveRef:
    """Produce a plan's export tree and obtain the reference to its archive.

    The export production call is queue-bound and is driven to completion by the client
    facade's queued-command auto-polling before the archive is requested. The archive call
    is synchronous and takes no revision of its own: it packs whatever tree the export
    production call just wrote.

    Args:
        client: An object exposing the plan_export and export_archive coroutines.
        plan: The plan identifier whose export tree is produced and archived.
        revision: Optional revision passed to the export production call only; when None
            that call uses its own default revision selection.

    Returns:
        The ExportArchiveRef naming exactly one archive file, with its size, declared
        whole-file digest, and packed-file count.
    """
    await client.plan_export(plan=plan, revision=revision)
    response = await client.export_archive(plan=plan)
    return ExportArchiveRef(
        name=str(response["archive"]),
        size_bytes=int(response["size_bytes"]),
        sha256=str(response["sha256"]),
        file_count=int(response["file_count"]),
    )


__all__ = [
    "ExportArchiveRef",
    "SupportsExportProduction",
    "request_export_archive",
]
