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
            "pagination convention (limit 1..200, default 50; "
            "non-negative offset; out-of-range values rejected with "
            "INVALID_PAGINATION) and the response always carries total "
            "alongside the page."
        ),
        "parameters": {
            "limit": {
                "description": "Maximum number of catalog entries to return (default 50, max 200).",
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
                "description": "A page of command catalog entries plus the total entry count before pagination.",
                "data": {
                    "commands": "List of catalog entry dicts: name, category, parameters, execution_mode, metadata, source_module.",
                    "total": "Total number of catalog entries before pagination.",
                    "limit": "The limit actually applied to this page.",
                    "offset": "The offset actually applied to this page.",
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
                "explanation": "Returns up to 50 catalog entries starting at offset 0, plus the total entry count.",
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
            "Use total in the response to detect additional pages; it reflects the full catalog size before pagination, not the returned page size.",
            "The catalog is generated from the live command inventory on every call; it always reflects the currently registered command set.",
            "execution_mode mirrors each command class's own use_queue ClassVar; a command with execution_mode 'queued' must be invoked through the queued discipline (job_id + poll_with).",
        ],
    }
