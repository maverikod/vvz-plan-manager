"""Extended documentation metadata for the info command (C-025)."""
from typing import Any, Dict


def get_info_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata dictionary for InfoCommand.

    Args:
        cls: The InfoCommand class object, passed in by InfoCommand.metadata()
            (a classmethod), so identity attributes are read from the class
            itself rather than duplicated here.

    Returns:
        Dict[str, Any]: metadata dictionary with the keys required by the
        command metadata standard: name, version, description, category,
        author, email, detailed_description, parameters, return_value,
        usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the server self-description: identity (product name, "
            "package version, platform adapter version), build metadata "
            "(build date, image tag), a runtime summary (database "
            "connectivity, open cascade count across all plans, and "
            "embedding service reachability), and the full operator "
            "documentation text embedded into the package at build time "
            "from the single documentation source that also produces the "
            "installed man and info pages, so this command's documentation "
            "text and the installed documentation cannot diverge. The "
            "optional section parameter restricts the answer to exactly "
            "one of identity, build, runtime, or documentation; omitting "
            "it returns all four. This command is read-only and never "
            "mutates state. A missing embedded documentation payload is a "
            "packaging defect: it is never silently replaced by generated "
            "text, and instead surfaces as an explicit internal error "
            "naming the defect. The database connectivity probe and the "
            "embedding service probe never raise out of this command: an "
            "unreachable database is reported as database_connected: "
            "false with open_cascades: 0, and the embedding service is "
            "reported as 'unconfigured' when no embedding URL is set in "
            "server configuration, 'reachable' when a probe call "
            "succeeds, or 'unreachable' when the probe call fails."
        ),
        "parameters": {
            "section": {
                "description": (
                    "Restrict the response to one section: 'identity', "
                    "'build', 'runtime', or 'documentation'. Omit this "
                    "parameter to receive all four sections."
                ),
                "type": "string",
                "required": False,
                "enum": ["identity", "build", "runtime", "documentation"],
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "The server self-description: either all four "
                    "sections together, or, when section is given, only "
                    "that section's data nested under a 'section' key "
                    "that echoes the requested section name."
                ),
                "data": {
                    "identity": (
                        "Product name, package version, and platform "
                        "adapter version."
                    ),
                    "build": "Build date and image tag.",
                    "runtime": (
                        "Database connectivity, open cascade count, and "
                        "embedding service reachability status."
                    ),
                    "documentation": (
                        "Full embedded operator documentation text under "
                        "a 'text' key."
                    ),
                    "section": (
                        "Present only when the section parameter was "
                        "given; echoes the requested section name."
                    ),
                },
                "example": {
                    "identity": {
                        "product": "plan_manager",
                        "package_version": "1.0.0",
                        "adapter_version": "1.0.0",
                    },
                    "build": {
                        "build_date": "2026-07-02",
                        "image_tag": "1.0.0",
                    },
                    "runtime": {
                        "database_connected": True,
                        "open_cascades": 0,
                        "embedding_service": "reachable",
                    },
                    "documentation": {"text": "..."},
                },
            },
            "error": {
                "description": (
                    "This command declares no domain error cases: it "
                    "never raises DomainCommandError. An unexpected "
                    "failure while assembling the self-description (for "
                    "example a missing embedded documentation payload, "
                    "which is a packaging defect) propagates through "
                    "map_exception as a platform-level JSON-RPC internal "
                    "error, not a stable domain string code."
                ),
                "code": "none",
                "message": (
                    "See the platform's JSON-RPC internal error message "
                    "for the underlying failure."
                ),
                "details": "Not applicable: this command returns no domain error code.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the full server self-description.",
                "command": {},
                "explanation": (
                    "Returns identity, build, runtime, and documentation "
                    "sections together."
                ),
            },
            {
                "description": "Get only the runtime summary.",
                "command": {"section": "runtime"},
                "explanation": (
                    "Returns only database connectivity, open cascade "
                    "count, and embedding service reachability, nested "
                    "under 'section': 'runtime'."
                ),
            },
        ],
        "error_cases": {
            "none": {
                "description": (
                    "No stable domain error is declared for this command; "
                    "unexpected assembly or packaging failures surface as "
                    "platform-level internal errors."
                ),
                "message": "",
                "solution": (
                    "Check runtime configuration, embedded documentation packaging, "
                    "and server logs."
                ),
            },
        },
        "best_practices": [
            "Call info without a section parameter to get a full health snapshot in one round trip.",
            "Use section='runtime' for lightweight liveness checks instead of fetching the full documentation payload.",
            "A missing documentation payload signals a packaging defect; report it to the release pipeline rather than treating it as an empty answer.",
        ],
    }
