"""Path A explicit git staging and commit composition.

After the tree upload phase, explicitly stages the written destination
paths and issues an explicit commit through the CA service's own client
(CodeAnalysisClientDependency, MRS concept C-015), independent of the CA
service's commit-on-write configuration, realizing the commit phase of
PathACodeAnalysisDelivery (MRS concept C-003) and the deterministic-message
requirement of DeliveryFailureAtomicity (MRS concept C-011).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from code_analysis_client.client import CodeAnalysisAsyncClient


@dataclass(frozen=True)
class CommitReceipt:
    """Outcome of the explicit git staging and commit composition.

    Attributes:
        commit_hash: The git commit hash the CA client returned, or None
            when no commit was made (empty written_paths).
        commit_message: The deterministic commit message text used, or
            an empty string when no commit was made.
    """

    commit_hash: Optional[str]
    commit_message: str


def build_commit_message(
    plan_name: str,
    export_revision_uuid: str,
    per_entry_digest_set: dict[str, str],
) -> str:
    """Build the deterministic Path A commit message.

    Args:
        plan_name: Name of the plan being delivered.
        export_revision_uuid: Revision uuid of the export being delivered.
        per_entry_digest_set: Mapping of each delivered tree entry's path
            relative to the plan export root to its sha256 hex digest.

    Returns:
        A deterministic multi-line commit message: a header line naming
        plan_name and export_revision_uuid, followed by one line per entry
        of per_entry_digest_set sorted by relative path ascending (str
        order), each formatted as two spaces then
        '{relative_path}: sha256:{digest}'. Sorting makes the message
        reproducible across retried deliveries regardless of input dict
        ordering.
    """
    header = f"plan_manager export delivery: {plan_name} (revision {export_revision_uuid})"
    lines = [header] + [f"  {relative_path}: sha256:{digest}" for relative_path, digest in sorted(per_entry_digest_set.items())]
    return "\n".join(lines)


async def stage_and_commit(
    ca_client: CodeAnalysisAsyncClient,
    resolved_project_id: str,
    written_paths: list[str],
    plan_name: str,
    export_revision_uuid: str,
    per_entry_digest_set: dict[str, str],
) -> CommitReceipt:
    """Explicitly stage and commit the written Path A tree.

    Args:
        ca_client: An already-connected CodeAnalysisAsyncClient instance
            (MRS concept C-015); this function does not construct or
            close it.
        resolved_project_id: The CA project_id the tree was written into.
        written_paths: Destination paths successfully uploaded, each
            carrying its entry's relative position beneath the destination
            subdirectory.
        plan_name: Name of the plan being delivered.
        export_revision_uuid: Revision uuid of the export being delivered.
        per_entry_digest_set: Mapping of each delivered tree entry's
            export-root-relative path to its sha256 digest.

    Returns:
        A CommitReceipt. When written_paths is empty, CommitReceipt(None, '')
        is returned without any CA git call. Otherwise the CA client's
        git_add is called with resolved_project_id and written_paths, then
        its git_commit is called with resolved_project_id and the message
        from build_commit_message; the returned CommitReceipt carries the
        commit hash the CA client reports and the message used.
    """
    if len(written_paths) == 0:
        return CommitReceipt(commit_hash=None, commit_message="")

    await ca_client.commands.git_add(project_id=resolved_project_id, paths=written_paths)

    message = build_commit_message(plan_name, export_revision_uuid, per_entry_digest_set)

    result = await ca_client.commands.git_commit(project_id=resolved_project_id, message=message)

    def extract_commit_hash(result_obj):
        # Try attribute access first
        if hasattr(result_obj, 'commit_hash'):
            return result_obj.commit_hash
        # Try dict-like access
        try:
            return result_obj["commit_hash"]
        except (TypeError, KeyError):
            pass
        # Fall back to str
        return str(result_obj)

    commit_hash = extract_commit_hash(result)

    return CommitReceipt(commit_hash=commit_hash, commit_message=message)
