"""BranchDumpCommand: write every branch's prompt as a non-authoritative snapshot."""
from typing import Any, Dict


def get_branch_dump_metadata(cls: type) -> Dict[str, Any]:
    """Return extended AI/documentation metadata for BranchDumpCommand.

    :param cls: The command class requesting its metadata
        (BranchDumpCommand). The returned dict reads cls.name,
        cls.version, cls.descr, cls.category, cls.author, cls.email.
    :return: A dictionary with the required metadata fields: name,
        version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Writes the deterministic executor prompt of every branch "
            "of the plan under the configured export root at "
            "<export_root>/prompt_dump/<plan uuid>, one file per "
            "branch, by delegating to dump_prompts(conn, plan_uuid, "
            "dump_dir). The written files are an explicitly "
            "non-authoritative derived snapshot: the server never "
            "reads them back, and they carry no plan truth. When "
            "dry_run is True, branches are counted but no file is "
            "written, so a dry_run=True call never touches disk and "
            "is always safe to run against a real plan. Result-set "
            "pagination is not applicable to this command: its large "
            "output is the file artifact written under the export "
            "root and served in byte ranges by export_read; the "
            "JSON-RPC response itself is a fixed-size scalar summary."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the plan catalog.",
                "type": "string",
                "required": True,
            },
            "dry_run": {
                "description": "When true, count branches only and write no file.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The non-authoritative dump snapshot summary.",
                "data": {
                    "branches": "Number of (gs, ts, atomic) branches enumerated.",
                    "root": "Filesystem path of the dump root for this plan.",
                    "dry_run": "Echo of the dry_run flag used for this call.",
                    "non_authoritative": "Always True: the snapshot is never read back by the server.",
                },
                "example": {
                    "branches": 42,
                    "root": "/var/planmgr/export/prompt_dump/<uuid>",
                    "dry_run": False,
                    "non_authoritative": True,
                },
            },
            "error": {
                "description": "The plan identifier could not be resolved.",
                "code": "PLAN_NOT_FOUND",
                "message": "Human-readable description of the missing plan.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Count the branches that would be dumped, without writing files.",
                "command": {"plan": "plan_manager", "dry_run": True},
                "explanation": "Returns the branch count only; disk is not touched.",
            },
            {
                "description": "Write the full prompt dump snapshot for a plan.",
                "command": {"plan": "plan_manager", "dry_run": False},
                "explanation": "Writes one Markdown file per branch under the export root.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "PROMPT_ASSEMBLY_FAILED": {
                "description": "While writing the per-branch dump, the prompt assembler could not resolve a concept_id referenced by some branch's content to an existing concept row (dump_prompts delegates to assemble_prompt for every branch).",
                "message": "no concept row for {concept_id}",
                "solution": "Fix the dangling concept_id reference in the offending branch's content (or add the missing concept via concept_add) and retry.",
            },
        },
        "best_practices": [
            "Use dry_run=True first on a large plan to see how many files would be written before committing to the full dump.",
            "Treat the dumped files as a read-only convenience snapshot for humans or external tooling; never feed them back into the server as plan truth.",
            "Pagination is not applicable here: read large dumped artifacts through export_read byte ranges instead of expecting a paginated JSON-RPC response.",
        ],
    }
