"""Plan, export, HRS/MRS, and relation command-family facade mixin.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class PlanHrsCommandsMixin:
    """One method per plan_manager command in the plan/export/HRS/MRS family.

    Assumes it is mixed into a class that also inherits
    plan_manager_client.dispatch._CommandDispatchMixin, which supplies the
    coroutine async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def plan_create(self, **params: Any) -> Any:
        """Create a new plan aggregate with a unique name."""
        return await self._call("plan_create", params)

    async def plan_list(self, **params: Any) -> Any:
        """List a paginated page of plans in the catalog with their bound projects; soft-deleted plans are hidden unless show_deleted is true."""
        return await self._call("plan_list", params)

    async def plan_status(self, **params: Any) -> Any:
        """Return the dashboard for one plan: counts, gate, and scoring."""
        return await self._call("plan_status", params)

    async def plan_delete(self, **params: Any) -> Any:
        """Delete a plan: soft by default (hidden from the catalog, reversible), or permanently with hard=true."""
        return await self._call("plan_delete", params)

    async def plan_completed_set(self, **params: Any) -> Any:
        """Set or unset a plan's completion lock; always reachable regardless of freeze state or the current flag value."""
        return await self._call("plan_completed_set", params)

    async def plan_comment_set(self, **params: Any) -> Any:
        """Set, replace, or clear a plan's free-form comment; always reachable regardless of freeze state or the completion lock."""
        return await self._call("plan_comment_set", params)

    async def plan_project_attach(self, **params: Any) -> Any:
        """Attach an analysis-server project UUID to a plan."""
        return await self._call("plan_project_attach", params)

    async def plan_project_detach(self, **params: Any) -> Any:
        """Detach a project UUID from a plan and clear matching step bindings."""
        return await self._call("plan_project_detach", params)

    async def plan_project_list(self, **params: Any) -> Any:
        """List project UUIDs bound to a plan."""
        return await self._call("plan_project_list", params)

    async def plan_project_set_primary(self, **params: Any) -> Any:
        """Set the primary project UUID for a plan."""
        return await self._call("plan_project_set_primary", params)

    async def plan_project_clear_primary(self, **params: Any) -> Any:
        """Clear the primary project UUID for a plan."""
        return await self._call("plan_project_clear_primary", params)

    async def plan_export(self, **params: Any) -> Any:
        """Export a plan to the standard file layout under the configured export root."""
        return await self._call("plan_export", params)

    async def plan_snapshot(self, **params: Any) -> Any:
        """Export an importable snapshot of a plan's live working state."""
        return await self._call("plan_snapshot", params)

    async def plan_import(self, **params: Any) -> Any:
        """Import a plan from a standard file layout under the configured export root."""
        return await self._call("plan_import", params)

    async def export_upload_save(self, **params: Any) -> Any:
        """Promote a completed transfer upload session into the configured export root under a safe bare filename."""
        return await self._call("export_upload_save", params)

    async def export_read(self, **params: Any) -> Any:
        """Read a byte range of a file under <export_root>/<plan>/ as a base64 chunk, with the whole file's size and sha256 for byte-identical reassembly and verification."""
        return await self._call("export_read", params)

    async def export_archive(self, **params: Any) -> Any:
        """Pack the plan's export tree into a single gzip-tar archive under the fixed plan-relative name export.tar.gz; synchronous, returning plan, archive, size_bytes, sha256, and file_count."""
        return await self._call("export_archive", params)

    async def hrs_import(self, **params: Any) -> Any:
        """Replace a plan's HRS text from a Markdown file under the configured export root or from inline source_text."""
        return await self._call("hrs_import", params)

    async def hrs_export(self, **params: Any) -> Any:
        """Export the byte-identical HRS Markdown text of a plan."""
        return await self._call("hrs_export", params)

    async def export_cleanup(self, **params: Any) -> Any:
        """Purge export artifacts under the configured export root, classified per plan; dry_run defaults to true and reports what would be removed without removing it."""
        return await self._call("export_cleanup", params)

    async def para_list(self, **params: Any) -> Any:
        """List a paginated page of a plan's HRS paragraphs with label, binding flag, and position."""
        return await self._call("para_list", params)

    async def para_get(self, **params: Any) -> Any:
        """Resolve one paragraph label of a plan's HRS to its text."""
        return await self._call("para_get", params)

    async def para_label_assign(self, **params: Any) -> Any:
        """Assign fresh labels to unlabeled binding paragraphs of a plan's HRS."""
        return await self._call("para_label_assign", params)

    async def para_mark_non_binding(self, **params: Any) -> Any:
        """Wrap or unwrap the non-binding markers around one HRS block of a plan."""
        return await self._call("para_mark_non_binding", params)

    async def para_insert(self, **params: Any) -> Any:
        """Insert one new binding paragraph into a plan's HRS at a binding-order position."""
        return await self._call("para_insert", params)

    async def para_update(self, **params: Any) -> Any:
        """Replace the text of one binding HRS paragraph addressed by label."""
        return await self._call("para_update", params)

    async def para_delete(self, **params: Any) -> Any:
        """Delete one binding HRS paragraph addressed by label, shifting later paragraphs up."""
        return await self._call("para_delete", params)

    async def concept_get(self, **params: Any) -> Any:
        """Return one concept of a plan by concept_id."""
        return await self._call("concept_get", params)

    async def concept_list(self, **params: Any) -> Any:
        """Return a paginated page of the concept list of a plan."""
        return await self._call("concept_list", params)

    async def concept_add(self, **params: Any) -> Any:
        """Add a new concept to the plan MRS under an open cascade."""
        return await self._call("concept_add", params)

    async def concept_update(self, **params: Any) -> Any:
        """Update fields of an existing concept under an open cascade."""
        return await self._call("concept_update", params)

    async def concept_remove(self, **params: Any) -> Any:
        """Remove an existing concept from the plan MRS under an open cascade."""
        return await self._call("concept_remove", params)

    async def relation_list(self, **params: Any) -> Any:
        """Return a paginated page of the relation list of a plan."""
        return await self._call("relation_list", params)

    async def relation_add(self, **params: Any) -> Any:
        """Add a new relation between two concepts under an open cascade."""
        return await self._call("relation_add", params)

    async def relation_update(self, **params: Any) -> Any:
        """Update the type of an existing relation between two concepts under an open cascade."""
        return await self._call("relation_update", params)

    async def relation_remove(self, **params: Any) -> Any:
        """Remove an existing relation between two concepts under an open cascade."""
        return await self._call("relation_remove", params)

    async def concept_coverage(self, **params: Any) -> Any:
        """Return the steps and HRS paragraphs that justify one concept."""
        return await self._call("concept_coverage", params)


__all__ = ["PlanHrsCommandsMixin"]
