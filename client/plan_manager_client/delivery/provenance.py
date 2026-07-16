"""Path A delivery provenance recording.

On a successful delivery, records a runtime comment on the exported plan
carrying the export revision, target CA project and the subdirectory
rooting the delivered tree, the per-entry digests keyed by relative path,
and the commit hash, realizing DeliveryProvenanceRecord (MRS concept
C-010).
"""

from __future__ import annotations
from typing import Any, Protocol


class CommentAddCapable(Protocol):
    """Structural type for a facade exposing the plan_manager comment_add command.

    Matches the verified comment_add(plan, anchor_type, anchor_plan_uuid,
    kind, visibility, author, body, created_by) command signature without
    depending on the concrete facade class that implements it.
    """

    async def comment_add(
        self,
        plan: str,
        anchor_type: str,
        anchor_plan_uuid: str,
        kind: str,
        visibility: str,
        author: str,
        body: str,
        created_by: str,
    ) -> dict[str, Any]: ...


async def record_provenance(
    planmgr_client: CommentAddCapable,
    exported_plan_uuid: str,
    plan_name: str,
    export_revision_uuid: str,
    resolved_project_id: str,
    resolved_destination_subdirectory: str,
    per_entry_digest_set: dict[str, str],
    commit_hash: str,
    author: str,
) -> str:
    """Record a successful Path A tree delivery as a runtime comment.

    Args:
        planmgr_client: An object exposing an async comment_add method
            matching CommentAddCapable; this function does not construct
            or close it.
        exported_plan_uuid: UUID of the plan that was exported and
            delivered; used as both the comment_add 'plan' and
            'anchor_plan_uuid' arguments.
        plan_name: Name of the plan being delivered.
        export_revision_uuid: Revision uuid of the delivered export.
        resolved_project_id: Target CA project_id the tree was written
            into.
        resolved_destination_subdirectory: The destination subdirectory
            rooting the delivered tree inside the CA project.
        per_entry_digest_set: Mapping of each delivered tree entry's path
            relative to the plan export root to its sha256 digest.
        commit_hash: Git commit hash returned by the commit composition.
        author: Identity recorded as both 'author' and 'created_by' on the
            comment.

    Returns:
        The 'comment_uuid' field of the comment_add response.
    """
    digest_text = ", ".join(
        f"{relative_path}=sha256:{digest}"
        for relative_path, digest in sorted(per_entry_digest_set.items())
    )
    body = (
        f"Path A tree delivery: revision {export_revision_uuid} -> project {resolved_project_id}, "
        f"tree root {resolved_destination_subdirectory}; entries: {digest_text}; commit {commit_hash}"
    )
    response = await planmgr_client.comment_add(
        plan=exported_plan_uuid,
        anchor_type="plan",
        anchor_plan_uuid=exported_plan_uuid,
        kind="execution_note",
        visibility="public_summary",
        author=author,
        body=body,
        created_by=author,
    )
    return response["comment_uuid"]
