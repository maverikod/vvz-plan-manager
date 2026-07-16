"""Path A digest-verified CA tree upload composition.

Walks the materialized export tree, verifying each entry against its
digest (DeliveryIntegrityContract, MRS concept C-007) BEFORE uploading it
through the CA service's own client (CodeAnalysisClientDependency, MRS
concept C-015) to its own destination path, so the delivered tree
reproduces the export layout rather than a flat set of names, realizing
the upload phase of PathACodeAnalysisDelivery (MRS concept C-003).
"""

from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Literal
from code_analysis_client.client import CodeAnalysisAsyncClient


class DigestMismatchError(Exception):
    """Raised when a tree entry's content does not match its digest.

    Raised by :func:`verify_and_upload_tree` before any CA-side write is
    attempted for the mismatched entry, per DeliveryIntegrityContract
    (MRS concept C-007).
    """
    pass


@dataclass(frozen=True)
class PendingEntry:
    """One export tree entry queued for digest-verified upload.

    Attributes:
        relative_path: The entry's POSIX path relative to the plan export
            root, preserved unchanged end to end (for example
            'G-001-x/T-001-y/atomic_steps/A-001-z.yaml').
        destination_path: The resolved project-relative POSIX destination
            path inside the CA project, already carrying relative_path's
            position beneath the destination subdirectory.
        content: The entry's unpacked content bytes.
        declared_digest: The declared sha256 hex digest for content.
        already_indexed: True selects UPDATE mode (upload); False selects
            CREATE mode (upload_new).
    """
    relative_path: str
    destination_path: str
    content: bytes
    declared_digest: str
    already_indexed: bool


@dataclass(frozen=True)
class UploadResult:
    """Outcome of one tree entry's digest-verified upload to the CA project."""
    relative_path: str
    destination_path: str
    mode: Literal["create", "update"]
    ca_file_id: str
    success: bool


async def verify_and_upload_tree(
    ca_client: CodeAnalysisAsyncClient,
    resolved_project_id: str,
    pending_entries: list[PendingEntry],
) -> list[UploadResult]:
    """Digest-verify and upload each tree entry through the CA client.

    Args:
        ca_client: An already-connected CodeAnalysisAsyncClient instance
            (MRS concept C-015); this function does not construct or close it.
        resolved_project_id: The CA project_id to upload into.
        pending_entries: Tree entries queued for upload, in tree order.

    Returns:
        One UploadResult per entry of pending_entries, in the same order.

    Raises:
        DigestMismatchError: If, for any entry, hashlib.sha256(entry.content)
            .hexdigest() does not equal entry.declared_digest. Processing
            stops at the first mismatch: no upload call is made for that
            entry or any later entry.
    """
    result: list[UploadResult] = []
    file_sessions = ca_client.file_sessions

    for entry in pending_entries:
        digest = hashlib.sha256(entry.content).hexdigest()

        if digest != entry.declared_digest:
            raise DigestMismatchError(
                f"digest mismatch for {entry.relative_path!r} at {entry.destination_path!r}"
            )

        if entry.already_indexed is False:
            ca_file_id = await file_sessions.upload_new(
                project_id=resolved_project_id,
                file_path=entry.destination_path,
                content=entry.content,
            )
            mode = "create"
        else:
            ca_file_id = await file_sessions.upload(
                file_id=entry.destination_path,
                content=entry.content,
            )
            mode = "update"

        result.append(
            UploadResult(
                relative_path=entry.relative_path,
                destination_path=entry.destination_path,
                mode=mode,
                ca_file_id=str(ca_file_id),
                success=True,
            )
        )

    return result
