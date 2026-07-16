"""Path A failure atomicity and partial-write outcome tracking.

Assembles the delivery outcome record naming exactly which destination
paths were written and whether a commit was made, distinguishing every
abort point of the Path A composition, realizing DeliveryFailureAtomicity
(MRS concept C-011). An archive-verification or archive-entry-refusal
abort leaves nothing behind, so the record cannot express either of them
alongside written paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

FailurePoint = Literal["archive_verification", "archive_entry_refused", "digest_verification", "upload", "commit"]
# The Path A composition stage at which a delivery failed, when it failed (MRS concept C-011).


@dataclass(frozen=True)
class DeliveryOutcome:
    """Outcome of one Path A delivery attempt.

    Attributes:
        written_paths: Destination paths successfully written to the CA
            project during this attempt, in delivery order, each carrying
            its entry's relative position beneath the destination
            subdirectory.
        commit_made: True when a git commit was made for this attempt.
        commit_hash: The git commit hash, when commit_made is True;
            otherwise None.
        failure_point: The composition stage at which the delivery failed,
            or None when the delivery completed successfully. A failure at
            'archive_verification' or 'archive_entry_refused' always
            carries an empty written_paths: the archive was rejected or
            the whole tree was refused before any entry was materialized,
            so nothing was written and nothing was left behind.
    """

    written_paths: list[str] = field(default_factory=list)
    commit_made: bool = False
    commit_hash: Optional[str] = None
    failure_point: Optional[FailurePoint] = None


_VALID_FAILURE_POINTS: tuple[str, ...] = ("archive_verification", "archive_entry_refused", "digest_verification", "upload", "commit")

_NOTHING_WRITTEN_FAILURE_POINTS: tuple[str, ...] = ("archive_verification", "archive_entry_refused")
# Abort points that precede every write: the archive never verified, or the whole tree was refused before any entry was materialized. Both leave nothing behind, so neither can accompany a non-empty written_paths.


def build_delivery_outcome(
    written_paths: list[str],
    commit_hash: Optional[str],
    failure_point: Optional[FailurePoint] = None,
) -> DeliveryOutcome:
    """Assemble a DeliveryOutcome from one Path A delivery attempt's results.

    Args:
        written_paths: Destination paths successfully written during this
            attempt, in delivery order.
        commit_hash: The git commit hash if a commit was made, else None.
        failure_point: The stage at which the delivery failed, or None for
            a fully successful delivery.

    Returns:
        A DeliveryOutcome with commit_made set to (commit_hash is not
        None), and written_paths, commit_hash, failure_point carried
        through unchanged (written_paths copied, not aliased).

    Raises:
        ValueError: If failure_point is not None and not one of
            'archive_verification', 'archive_entry_refused',
            'digest_verification', 'upload', 'commit'; or if
            failure_point is 'archive_verification' or
            'archive_entry_refused' while written_paths is non-empty,
            which is an impossible outcome because both abort points
            precede every write and leave nothing behind.
    """
    if failure_point is not None and failure_point not in _VALID_FAILURE_POINTS:
        raise ValueError(f"invalid failure_point: {failure_point!r}")

    if failure_point in _NOTHING_WRITTEN_FAILURE_POINTS and len(written_paths) > 0:
        raise ValueError(f"failure_point {failure_point!r} leaves nothing behind but written_paths is non-empty: {list(written_paths)!r}")

    commit_made = commit_hash is not None

    return DeliveryOutcome(
        written_paths=list(written_paths),
        commit_made=commit_made,
        commit_hash=commit_hash,
        failure_point=failure_point,
    )
