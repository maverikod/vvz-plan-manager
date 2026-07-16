"""Extended documentation metadata for the ops_status command (C-002)."""
from typing import Any, Dict


def get_ops_status_metadata(cls: Any) -> Dict[str, Any]:
    """Build the extended documentation metadata dictionary for OpsStatusCommand.

    Args:
        cls: The OpsStatusCommand class object, passed in by
            OpsStatusCommand.metadata() (a classmethod), so identity
            attributes are read from the class itself rather than
            duplicated here.

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
            "Collapses the post-deploy verification dance (remote shell, "
            "container exec, direct database query) into one read-only "
            "JSON-RPC call. Returns, in one response: the deployed "
            "version (image_tag and build_date, read from the same "
            "build-time payload the info command's build section reads "
            "via plan_manager.runtime.build_info.build_info()); the "
            "health state (status 'ok' or 'error', and a services object "
            "with the same database/embedding availability shape the "
            "health command's components.services reports, computed with "
            "the same plan_manager.runtime.probes.probe_database and "
            "probe_embedding_detail probes so ops_status and health never "
            "disagree for one runtime state); and the applied "
            "schema_migration ledger (every row of the schema_migration "
            "table -- filename and applied_at -- newest first, with a "
            "total count), obtained by a plain read-only SELECT over the "
            "already-populated table created at deploy time by "
            "plan_manager_db/init.sh. Deploy actions (build, cutover, "
            "restart) are explicitly out of scope: this command only "
            "observes already-deployed state. When the database is "
            "unreachable, health.status is 'error' and the "
            "schema_migration section reports count 0 with an empty rows "
            "list and an explanatory note, instead of raising -- the "
            "migration read is skipped only when the database probe "
            "itself already reports the database unavailable. This "
            "command is read-only, takes no parameters, and is not "
            "queued (use_queue=False)."
        ),
        "parameters": {},
        "return_value": {
            "success": {
                "description": (
                    "version, health, and schema_migration reported "
                    "together in one response."
                ),
                "data": {
                    "version": "image_tag and build_date from the build-time payload.",
                    "health": (
                        "status ('ok' or 'error') and a services object "
                        "with database (required) and embedding "
                        "(optional) availability, the same shape health "
                        "reports under components.services."
                    ),
                    "schema_migration": (
                        "count (total applied migrations) and rows: a "
                        "list of {filename, applied_at} objects ordered "
                        "newest first by applied_at."
                    ),
                },
                "example": {
                    "version": {
                        "image_tag": "0.1.36",
                        "build_date": "2026-07-15",
                    },
                    "health": {
                        "status": "ok",
                        "services": {
                            "database": {"required": True, "available": True},
                            "embedding": {
                                "required": False,
                                "available": True,
                                "transport_available": True,
                                "model_ready": True,
                                "model_status": "ready",
                                "state": "reachable",
                            },
                        },
                    },
                    "schema_migration": {
                        "count": 2,
                        "rows": [
                            {
                                "filename": "0016_add_metrics_store.sql",
                                "applied_at": "2026-07-16T09:00:00+00:00",
                            },
                            {
                                "filename": "0009_runtime_audit_log.sql",
                                "applied_at": "2026-06-01T12:00:00+00:00",
                            },
                        ],
                    },
                },
            },
            "error": {
                "description": (
                    "This command declares no domain error cases; a "
                    "database that is unreachable is reported through "
                    "health.status == 'error' and an empty "
                    "schema_migration section rather than raised. "
                    "Unexpected failures while reading the build-time "
                    "payload (a packaging defect) propagate as a "
                    "platform-level internal error."
                ),
                "code": "none",
                "message": "",
                "details": "Not applicable.",
            },
        },
        "usage_examples": [
            {
                "description": "Verify a deployed release in one call.",
                "command": {},
                "explanation": (
                    "Returns the deployed version, health, and applied "
                    "schema_migration rows together, replacing a "
                    "remote-shell + container-exec + psql sequence."
                ),
            },
        ],
        "error_cases": {
            "none": {
                "description": (
                    "No stable domain error is declared for this "
                    "command."
                ),
                "message": "",
                "solution": (
                    "If health.status is 'error', the required database "
                    "is unreachable: check the database connection "
                    "configuration and the mounted secrets file; "
                    "schema_migration.count will be 0 with an empty rows "
                    "list until the database is reachable again."
                ),
            },
        },
        "best_practices": [
            "Call ops_status once after a deploy instead of chaining ssh, docker exec, and psql to confirm a release.",
            "Compare version.image_tag against the release you just deployed.",
            "Treat health.status == 'error' as the same required-database signal the health command reports.",
            "Read schema_migration.rows[0] for the most recently applied migration; rows are ordered newest first.",
        ],
    }
