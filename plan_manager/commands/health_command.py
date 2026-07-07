"""Platform ``health`` command override: report required-service availability.

The platform ships a builtin ``health`` command that reports process and
system liveness only (uptime, memory, registered command count, proxy
registration). plan_manager overrides it — registered after the builtin
under the same name, so the override wins at dispatch — to additionally
report the availability of the services the server depends on:

* the in-container PostgreSQL database, which is **required**; and
* the embedding service, which is **optional** and degrades only semantic
  scoring when unavailable.

The overall ``status`` turns ``"error"`` only when a required service (the
database) is unreachable, so a proxy heartbeat consumer observes a
genuinely unhealthy server. The optional embedding service never flips the
overall status; its reachability is reported under
``components.services.embedding`` for observability, using the same probe
and operator-configured timeout as the ``info`` command so the two commands
cannot disagree for one runtime state.

This override is not part of the normative plan_manager command inventory
(C-024): it replaces a platform command rather than adding a domain one, so
it is registered directly against the registry as a builtin replacement and
is excluded from the inventory probe.
"""

from typing import Any, Dict

from mcp_proxy_adapter.commands.health_command import (
    HealthCommand as _BuiltinHealthCommand,
    HealthResult,
)

from plan_manager.commands.health_metadata import get_health_metadata
from plan_manager.runtime.probes import (
    probe_database,
    probe_embedding_detail,
)


class HealthCommand(_BuiltinHealthCommand):
    """Return platform liveness plus required/optional service availability."""

    name = "health"
    version = "1.0.0"
    descr = (
        "Return server health: platform liveness (uptime, process, "
        "registered command count, proxy registration) plus availability "
        "of the required PostgreSQL database and the optional embedding "
        "service. Overall status is 'error' when the required database is "
        "unreachable, otherwise 'ok'; the optional embedding service is "
        "reported for observability and never changes the overall status."
    )
    category = "system"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"

    async def execute(self, **kwargs) -> HealthResult:
        base = await super().execute(**kwargs)
        data = dict(base.data)
        components = dict(data.get("components", {}))

        database_available = probe_database()
        embedding = probe_embedding_detail()
        components["services"] = {
            "database": {
                "required": True,
                "available": database_available,
            },
            "embedding": {
                "required": False,
                # available reflects genuine model readiness, not mere
                # transport reachability; a reachable-but-uninitialized model
                # is available=false with state "not_ready".
                "available": embedding["model_ready"],
                "transport_available": embedding["transport_available"],
                "model_ready": embedding["model_ready"],
                "model_status": embedding["model_status"],
                "state": embedding["state"],
            },
        }
        status = "ok" if database_available else "error"
        return HealthResult(
            status=status,
            version=data.get("version", "unknown"),
            uptime=data.get("uptime", 0.0),
            components=components,
        )

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_health_metadata(cls)
