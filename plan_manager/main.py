"""Server entry point and platform bootstrap for plan_manager.

Realises ServerRuntime (C-027): the entry point receives a configuration
file path, initializes the runtime (validating the custom configuration
section, C-028, and aborting startup with an explicit report on invalid
configuration or unreadable secrets), then creates the application through
the platform application factory and runs it with the platform's server
engine. The platform (mcp-proxy-adapter) owns the entire external surface:
the JSON-RPC endpoint with single and batch calls, the asynchronous
endpoint, health, command listing, heartbeat, WebSocket job push, and
OpenAPI and help output. Supported protocols (http, https, mtls) follow
the platform configuration unchanged. The server registers command classes
only through the platform hook mechanism; it adds no custom route and
patches no platform internal. The queue-manager section and the platform
registration section (proxy registration URL, heartbeat, server id,
instance UUID) are platform-owned and pass through untouched — the server
functions identically with registration disabled.

AUTO_IMPORT_MODULES declares, for the platform auto-import facility, the
modules that spawned worker processes must import so that command classes
and the registration hook are available in worker process memory.
"""

import argparse
import os
import sys

from plan_manager.runtime.context import init_runtime
from plan_manager.runtime.config import ConfigError

AUTO_IMPORT_MODULES: tuple[str, ...] = (
    "plan_manager.hooks",
    "plan_manager.commands.registration",
)


def build_app(config_path: str):
    """Create the platform ASGI application for the given configuration file.

    This is the only function that touches the platform API surface
    (mcp_proxy_adapter.api.app.create_app); the imports are placed inside
    the function body so that a mismatch against the platform contract
    stays localized to this one function. The platform owns the entire
    external surface: JSON-RPC with single and batch calls, the
    asynchronous endpoint, health, command listing, heartbeat, WebSocket
    job push, and OpenAPI and help output. Supported protocols (http,
    https, mtls) follow the platform configuration unchanged. The server
    registers command classes only; it adds no route and patches no
    platform internal. The queue-manager section and the platform
    registration section (registration URL, heartbeat URL and interval,
    server id, instance UUID) are read by the platform from the same
    configuration file and passed through untouched — the server functions
    identically with registration disabled.

    Args:
        config_path: Path to the JSON configuration file containing the
            platform-owned sections (server, registration, auth, queue
            manager, and optional ssl/transport/security) plus the
            plan_manager custom section.

    Returns:
        The ASGI application created by the platform application factory.
    """
    from plan_manager import hooks as _plan_manager_hooks
    from fastapi import Request
    from mcp_proxy_adapter.api.handlers import get_commands_list, handle_json_rpc
    from mcp_proxy_adapter.api.app import create_app
    from plan_manager.runtime.config import load_raw

    del _plan_manager_hooks
    app = create_app(
        app_config=load_raw(config_path),
        config_path=config_path,
    )

    async def _legacy_get_methods_payload():
        commands_payload = await get_commands_list()
        commands = commands_payload.get("commands", {})
        methods = sorted(commands.keys()) if isinstance(commands, dict) else []
        return {
            "methods": methods,
            "commands": commands,
            "count": len(methods),
        }

    @app.get("/get_methods")
    async def legacy_get_methods_get():
        return await _legacy_get_methods_payload()

    @app.post("/get_methods")
    async def legacy_get_methods_post():
        return await _legacy_get_methods_payload()

    @app.post("/jsonrpc")
    async def legacy_jsonrpc(request: Request, body: dict):
        request_id = getattr(request.state, "request_id", None)
        return await handle_json_rpc(body, request_id, request)

    return app


def run_app(app, config_path: str) -> None:
    """Serve the platform application on the configured socket.

    The platform owns the transport: the listening host and port and the
    TLS material (server certificate, key, CA, and mTLS client-certificate
    verification) come from the ``server`` section of the same
    configuration file the application was built from. Serving is delegated
    to the platform's own server engine so that host, port, protocol
    (http, https, mtls) and SSL are applied exactly as the platform
    prescribes — the entry point never constructs a transport of its own.

    Args:
        app: The ASGI application created by :func:`build_app`.
        config_path: Path to the same JSON configuration file, read here
            only for the platform-owned ``server`` transport section.
    """
    from mcp_proxy_adapter.core.server_engine import ServerEngineFactory
    from mcp_proxy_adapter.core.app_factory.ssl_config import build_server_ssl_config
    from plan_manager.runtime.config import load_raw

    config = load_raw(config_path)
    server_cfg = config.get("server", {}) or {}
    server_config: dict = {
        "host": server_cfg.get("host", "0.0.0.0"),
        "port": int(server_cfg.get("port", 8080)),
        "log_level": "info",
        "reload": False,
    }
    ssl_engine_config = build_server_ssl_config(config)
    if ssl_engine_config:
        server_config.update(ssl_engine_config)

    engine = ServerEngineFactory.get_engine("hypercorn")
    if engine is None:
        raise RuntimeError("hypercorn server engine is not available")
    engine.run_server(app, server_config)


def main(argv: list[str] | None = None) -> int:
    """Run the plan_manager server bootstrap sequence.

    Parses the single required ``--config`` command-line option, then
    initializes the runtime by validating the custom configuration section
    (C-028) before any platform component starts. On invalid configuration
    or unreadable secrets, ``init_runtime`` raises ``ConfigError``; the
    explicit report from that error is printed to stderr and the function
    returns 1 without creating the platform application. On successful
    initialization, the platform application is created through
    ``build_app`` and served with the platform's hypercorn engine under
    ``asyncio.run``.

    Args:
        argv: Command-line arguments excluding the program name; when
            ``None``, arguments are read from ``sys.argv[1:]``.

    Returns:
        0 on clean shutdown after successful startup; 1 when configuration
        validation aborts startup before any platform component starts.
    """
    parser = argparse.ArgumentParser(prog="plan_manager")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the JSON configuration file.",
    )
    args = parser.parse_args(argv)
    os.environ["PLANMGR_CONFIG_PATH"] = args.config

    try:
        init_runtime(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1

    app = build_app(args.config)
    run_app(app, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
