"""Extended documentation metadata for the health command override."""
from typing import Any, Dict


def get_health_metadata(cls) -> Dict[str, Any]:
    """Build the extended documentation metadata dictionary for HealthCommand.

    Args:
        cls: The HealthCommand class object, passed in by
            HealthCommand.metadata() (a classmethod), so identity attributes
            are read from the class itself rather than duplicated here.

    Returns:
        Dict[str, Any]: metadata dictionary with the keys required by the
        command metadata standard.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Overrides the platform builtin health command. In addition to "
            "the platform liveness payload (server version, process uptime, "
            "memory usage, registered command count, and proxy registration "
            "status), it reports the availability of the services "
            "plan_manager depends on under components.services: the required "
            "in-container PostgreSQL database and the optional embedding "
            "service. The database is probed with a trivial SELECT on a "
            "fresh connection; the embedding service is probed with a single "
            "embedding request bounded by the operator-configured "
            "embedding.timeout, the same probe the info command's runtime "
            "section uses, so health and info never disagree for one runtime "
            "state. Overall status is 'error' when the required database is "
            "unreachable and 'ok' otherwise; the optional embedding service "
            "never changes the overall status and is surfaced with its "
            "state ('unconfigured', 'reachable', or 'unreachable') and an "
            "available boolean for observability. This command is read-only "
            "and takes no parameters."
        ),
        "parameters": {},
        "return_value": {
            "success": {
                "description": (
                    "Health payload: status ('ok' or 'error'), server "
                    "version, uptime in seconds, and a components object. "
                    "components.services carries the database and embedding "
                    "availability added by this override; the remaining "
                    "components (system, process, commands, "
                    "proxy_registration) come from the platform builtin."
                ),
                "example": {
                    "status": "ok",
                    "version": "1.0.0",
                    "uptime": 1234.5,
                    "components": {
                        "commands": {"registered_count": 62},
                        "services": {
                            "database": {"required": True, "available": True},
                            "embedding": {
                                "required": False,
                                "available": True,
                                "state": "reachable",
                            },
                        },
                    },
                },
            },
            "error": {
                "description": (
                    "This command declares no domain error cases; probe "
                    "failures are folded into the availability payload rather "
                    "than raised."
                ),
                "code": "none",
                "message": "",
                "details": "Not applicable.",
            },
        },
        "usage_examples": [
            {
                "description": "Check overall server and dependency health.",
                "command": {},
                "explanation": (
                    "Returns platform liveness plus database and embedding "
                    "availability; status is 'error' when the database is down."
                ),
            },
        ],
        "error_cases": {
            "none": {
                "description": (
                    "No stable domain error is declared for this command."
                ),
                "message": "",
                "solution": (
                    "If status is 'error', the required database is "
                    "unreachable: check the database connection configuration "
                    "and the mounted secrets file. If embedding state is "
                    "'unreachable', check the embedding URL, network route, "
                    "and the configured embedding.timeout."
                ),
            },
        },
        "best_practices": [
            "Use health for liveness and dependency checks; a status of 'error' means the required database is unreachable.",
            "Treat embedding state 'unreachable' as a semantic-scoring degradation, not a server outage.",
            "Raise the configured embedding.timeout if a healthy but slow embedding service is reported as 'unreachable'.",
        ],
    }
