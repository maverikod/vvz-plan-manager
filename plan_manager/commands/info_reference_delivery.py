"""Export-delivery reference data for the info command (CR-2, C-013).

Describes, for an executing agent, the two export-delivery paths, the archive that carries the no-project path's tree, the export tree layout whose names and relative positions are preserved end to end, the client library's location and entry points, the code-analysis client dependency, and the export artifact lifecycle rules. Consumed by plan_manager.commands.info_command for both the capabilities section and the agent_reference section.
"""

from __future__ import annotations

from typing import Any


def export_delivery_capabilities() -> dict[str, Any]:
    """The capabilities-section descriptor for export delivery."""
    return {
        "summary": "Export results are DELIVERED, not merely read: plan_manager closes the export byte gap by integrating delivery into the toolchain instead of exposing raw transfer plumbing to callers. Two delivery paths are selected by whether a code-analysis project is specified.",
        "delivery_paths": {
            "path_a_project_delivery": "Selected when a code-analysis project is specified (the plan's bound primary project, or an explicit override). The exported TREE is written into that project's documentation area as its own subdirectory, preserving the layout, and is then committed to git through the code-analysis service's own client, so the external project picks the export up from its own repository. Refused when the plan has no bound project and no override is given.",
            "path_b_local_fetch": "Selected when no code-analysis project is specified. The export tree is packed into a single archive, transferred to the caller through the existing byte-serving command, verified against its declared digest, and unpacked locally so the tree reappears byte-identically on the caller's filesystem.",
        },
        "export_archive": {
            "purpose": "No command enumerates an export - the export production command reports a COUNT of files written, never their names - so one archive under one known name is the only way a caller obtains a whole tree without guessing filenames, and one digest then covers the entire delivery.",
            "command": "export_archive takes only the plan and is SYNCHRONOUS: it packs whatever export tree currently sits under that plan's export directory, so which revision the tree represents is a property of the export production call that wrote it. It returns the plan, the archive's fixed plan-relative name, its byte size, its sha256 and the count of files packed.",
            "format_and_location": "A gzip-compressed tar under the fixed plan-relative name export.tar.gz, written INSIDE the plan's own export directory, so the existing byte-serving command serves it with no new transfer machinery. Re-archiving replaces the previous archive under the same name rather than accumulating copies, and the archive never includes itself.",
            "integrity": "The archive is verified against its declared sha256 BEFORE it is unpacked. On unpack every entry is validated before any byte is written: an entry whose path would escape the destination, or which is neither a regular file nor a directory, is REFUSED, so a refusal leaves nothing behind.",
        },
        "export_tree_layout": "An export is a TREE, not a flat set of files: source_spec.md and spec.yaml at the top, then one G-NNN-<slug>/ directory per global step carrying README.yaml, each holding its T-NNN-<slug>/ tactical directories with their own README.yaml, and atomic steps as atomic_steps/A-NNN-<slug>.yaml beneath those. Names and relative positions are preserved end to end by both delivery paths: bare filenames repeat across directories (README.yaml above all), so nothing is ever flattened to a bare name.",
        "client_library_dependency": "Path A is composed entirely client-side: the client library orchestrates two clients and reimplements neither. Every interaction with the code-analysis service goes through that service's own client package (its asynchronous entry client and its file-session facade for create-mode and update-mode uploads, and its git commands for explicit staging and commit); no hand-rolled JSON-RPC is written against the code-analysis service, and its transfer and git functionality is not rebuilt.",
        "export_lifecycle_rules": "Export artifacts do not outlive their plan: soft-deleting a plan marks its export directory orphaned-eligible, hard-deleting a plan removes its export directory, and the export_cleanup command purges export artifacts without requiring filesystem access from the caller. An archive is an ordinary export artifact with no exemption: it is counted in a cleanup preview and removed with its directory like any other file.",
    }


def export_delivery_agent_reference() -> dict[str, Any]:
    """The agent_reference-section table for export delivery."""
    return {
        "client_library": {
            "location": "A first-class Python package named plan_manager_client, living in its own dedicated client/ directory at the repository root as a separate installable distribution (plan-manager-client), independent of the plan_manager server package. It is built on the mcp-proxy-adapter's JSON-RPC client and fully encapsulates all network interaction.",
            "entry_points": "The PlanManagerClient class exposes one async method for every command on the plan_manager surface, export_archive and export_cleanup included, plus queued-command auto-polling that drives a queued job to completion using the surface's own job-status semantics. Its delivery compositions cover both paths: the no-project path requests the archive, fetches it, verifies it and unpacks the tree; the project path materializes the verified tree and uploads it through the code-analysis client.",
            "connection_model": "Every connection is direct to its server; the client never routes calls through the MCP proxy.",
        },
        "delivery_path_selection": "The caller's choice of a code-analysis project selects the path: a project bound to the plan (or an explicit override) selects the project path, delivering the tree into the project's documentation area and committing it to git; its absence selects the local path, delivering one archive that is verified and unpacked into the caller's filesystem.",
        "archive_contract": "export_archive(plan) is synchronous and takes no revision. It writes export.tar.gz inside the plan's export directory and returns that plan-relative name with the archive's size, sha256 and file count. Fetch it by the returned name through the byte-serving command, verify the whole-archive sha256 BEFORE unpacking, then unpack; an entry whose path would escape the destination is refused and nothing is written.",
        "export_tree_layout": "source_spec.md and spec.yaml at the export root; G-NNN-<slug>/README.yaml per global step; T-NNN-<slug>/README.yaml beneath its global step; atomic_steps/A-NNN-<slug>.yaml beneath its tactical step. Every entry travels under its export-root-relative path, never its bare name, because names such as README.yaml repeat across directories.",
        "export_lifecycle_rules": "Exports are scoped to their owning plan for their whole life: written by the queued export production command under the plan's export directory, packed on demand by export_archive, read back by the chunked byte-serving command, and purged either on plan deletion (soft delete marks the directory orphaned-eligible; hard delete removes it) or explicitly through export_cleanup, whose default is a dry run reporting exactly what would be removed. A directory whose plan is live is never removed; a directory resolving to no plan at all is removed only under export_cleanup's explicit orphan-inclusion flag.",
    }
