"""Queue-worker runtime bootstrap for plan_manager.

The adapter restores its own global config in spawned queue workers before it
imports hook auto-import modules. Importing this module then initializes the
plan_manager runtime from the same config file so queued commands can use the
database and application configuration accessors.
"""

from __future__ import annotations

import os

from plan_manager.runtime.context import init_runtime


def _config_path_from_adapter() -> str | None:
    env_config_path = os.environ.get("PLANMGR_CONFIG_PATH")
    if env_config_path and os.path.exists(env_config_path):
        return env_config_path

    try:
        from mcp_proxy_adapter.config import get_config

        config = get_config()
    except Exception:
        return None

    config_path = getattr(config, "config_path", None)
    if not config_path:
        return None
    config_path_str = str(config_path)
    if not os.path.exists(config_path_str):
        return None
    return config_path_str


def bootstrap_worker_runtime() -> bool:
    """Initialize plan_manager runtime in a spawned queue worker if possible."""
    config_path = _config_path_from_adapter()
    if not config_path:
        return False
    init_runtime(config_path)
    return True


BOOTSTRAPPED = bootstrap_worker_runtime()
