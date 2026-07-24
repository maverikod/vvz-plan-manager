"""Extended AI/documentation metadata for the command_catalog_dump command."""

from typing import Any

def get_command_catalog_dump_metadata(cls: type) -> dict[str, Any]:
    """Return the extended metadata dictionary for CommandCatalogDumpCommand.

    :param cls: The command class requesting its metadata
        (CommandCatalogDumpCommand). The returned dict reads cls.name,
        cls.version, cls.descr, cls.category, cls.author, cls.email.
    :type cls: type
    :return: A dictionary with the required metadata fields: name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases,
        best_practices.
    :rtype: dict[str, Any]
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the complete machine-readable catalog of every "
            "registered command, generated from the live command "
            "inventory (plan_manager.commands.inventory.INVENTORY) rather "
            "than hand-maintained. Each catalog entry carries name, "
            "category, parameters (from the command's own metadata()), "
            "execution_mode ('queued' when the command class's use_queue "
            "ClassVar is True, otherwise 'direct'), metadata (description, "
            "error_cases, best_practices, usage_examples), and "
            "source_module (the dotted module path of the command's "
            "implementation). The result is returned as a bounded, "
            "total-annotated page: offset and limit follow the uniform "
            "pagination validation (limit 1..200; non-negative offset; "
            "out-of-range or non-integer values rejected with "
            "INVALID_PAGINATION), but an OMITTED limit defaults to 10 for "
            "this command specifically, not the project's general 50-row "
            "default -- each catalog entry is a complete per-command "
            "metadata blob (full parameter descriptions/examples, "
            "usage_examples, error_cases, best_practices), averaging ~4.3 "
            "KB on the live catalog, so a 50-entry page would still "
            "serialize to roughly a quarter of a megabyte (bug 85b180bf's "
            "revised fix). The response always carries total "
            "alongside the page. Entries are sorted alphabetically by "
            "command name before slicing, giving a stable, deterministic "
            "page ordering across calls (independent of command "
            "registration/inventory order) -- the same contract used by "
            "the paginated help() catalog override. The response also "
            "carries returned (the actual entry count on this page) and "
            "has_more (True when offset + returned < total), alongside "
            "the existing commands/total/limit/offset keys, so paging "
            "loops do not need to recompute either from total/limit/offset "
            "themselves."
        ),
        "parameters": {
            "limit": {
                "description": (
                    "Maximum number of catalog entries to return (default 10 for this "
                    "command specifically -- smaller than the project's general 50-row "
                    "default because each entry is a complete per-command metadata blob; "
                    "max 200, same as every other paginated command)."
                ),
                "type": "integer",
                "required": False,
            },
            "offset": {
                "description": "Number of catalog entries to skip before returning results (default 0).",
                "type": "integer",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "A page of command catalog entries, sorted alphabetically by name, plus the total entry count before pagination.",
                "data": {
                    "commands": "List of catalog entry dicts, sorted alphabetically by name: name, category, parameters, execution_mode, metadata, source_module.",
                    "total": "Total number of catalog entries before pagination.",
                    "limit": "The limit actually applied to this page.",
                    "offset": "The offset actually applied to this page.",
                    "returned": "The actual number of entries on this page (len(commands)); equals limit except possibly on the last page.",
                    "has_more": "True when offset + returned < total, i.e. additional pages remain.",
                },
            },
            "error": {
                "description": "Domain error with stable domain_code in details.",
                "code": "Stable domain error code, e.g. INVALID_PAGINATION.",
                "message": "Human-readable message.",
                "details": "Programmatic diagnostic fields.",
            },
        },
        "usage_examples": [
            {
                "description": "List the first page of the command catalog with default pagination.",
                "command": {},
                "explanation": "Returns up to 10 catalog entries starting at offset 0, plus the total entry count.",
            },
            {
                "description": "Page through the catalog with an explicit limit and offset.",
                "command": {"limit": 20, "offset": 20},
                "explanation": "Returns entries 20 through 39 of the catalog, plus the total entry count.",
            },
        ],
        "error_cases": {
            "INVALID_PAGINATION": {
                "description": "limit or offset is not an integer, offset is negative, or limit is less than 1.",
                "message": "limit must be an integer, got {limit!r} (or the equivalent offset message).",
                "solution": "Retry with an integer limit >= 1 and a non-negative integer offset.",
            },
        },
        "best_practices": [
            "Use has_more (or total in the response) to detect additional pages; total reflects the full catalog size before pagination, not the returned page size.",
            "The catalog is generated from the live command inventory on every call; it always reflects the currently registered command set. Entries are always sorted alphabetically by name first, so consecutive calls with the same limit/offset return identical, gap-free, duplicate-free pages even if the underlying inventory order changes.",
            "execution_mode mirrors each command class's own use_queue ClassVar; a command with execution_mode 'queued' must be invoked through the queued discipline (job_id + poll_with).",
            "The default page (limit omitted) is intentionally smaller (10) than this project's general 50-row pagination default: each entry is a full per-command metadata blob (parameters, usage_examples, error_cases, best_practices), so a larger default page would still be a large response. Pass an explicit larger limit (up to 200) only when the full detail for many commands at once is actually needed.",
        ],
    }
