"""Command: ops_status -- read-only post-deploy observation surface (C-002)."""

from typing import Any, ClassVar, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.ops_status_metadata import get_ops_status_metadata
from plan_manager.runtime.build_info import build_info
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.probes import probe_database, probe_embedding_detail


class OpsStatusCommand(Command):
    """Return deployed version, health, and applied schema_migration rows in one call."""

    name: ClassVar[str] = "ops_status"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Return the deployed version (image_tag, build_date), the health "
        "state (database and embedding service availability), and the "
        "applied schema_migration rows in one read-only response."
    )
    category: ClassVar[str] = "system"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for ops_status.

        Returns:
            Dict[str, Any]: JSON-schema dict declaring no parameters.
        """
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for ops_status.

        Returns:
            Dict[str, Any]: Metadata dictionary from get_ops_status_metadata(cls).
        """
        return get_ops_status_metadata(cls)

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        """Assemble version, health, and schema_migration in one response.

        Args:
            **kwargs: Ignored; ops_status takes no parameters.

        Returns:
            SuccessResult | ErrorResult: On success, data has "version"
                ({"image_tag", "build_date"}), "health" ({"status",
                "services"}), and "schema_migration" ({"count", "rows"}).
                On an unexpected failure, an ErrorResult produced by
                map_exception.
        """
        try:
            info = build_info()
            version = {
                "image_tag": info["image_tag"],
                "build_date": info["build_date"],
            }

            database_available = probe_database()
            embedding = probe_embedding_detail()
            health = {
                "status": "ok" if database_available else "error",
                "services": {
                    "database": {
                        "required": True,
                        "available": database_available,
                    },
                    "embedding": {
                        "required": False,
                        "available": embedding["model_ready"],
                        "transport_available": embedding["transport_available"],
                        "model_ready": embedding["model_ready"],
                        "model_status": embedding["model_status"],
                        "state": embedding["state"],
                    },
                },
            }

            if database_available:
                with db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT filename, applied_at FROM schema_migration "
                            "ORDER BY applied_at DESC"
                        )
                        rows = cur.fetchall()
                schema_migration = {
                    "count": len(rows),
                    "rows": [
                        {
                            "filename": row[0],
                            "applied_at": row[1].isoformat(),
                        }
                        for row in rows
                    ],
                }
            else:
                schema_migration = {
                    "count": 0,
                    "rows": [],
                    "note": "database unavailable; schema_migration not read",
                }

            return SuccessResult(
                data={
                    "version": version,
                    "health": health,
                    "schema_migration": schema_migration,
                }
            )
        except Exception as exc:
            return map_exception(exc)
