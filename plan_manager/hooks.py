"""Startup hook wiring the plan_manager command surface into the adapter."""

from mcp_proxy_adapter.commands.hooks import register_custom_commands_hook as _register

from plan_manager.commands.registration import (
    check_inventory,
    probe_commands,
    register_all,
)


def register_custom_commands_hook(registry) -> None:
    """Register the full command surface and enforce startup invariants."""
    register_all(registry)
    check_inventory(registry)
    probe_commands(registry)


register_custom_commands_hook.__auto_import_modules__ = [
    "plan_manager.runtime.worker_bootstrap",
    "plan_manager.hooks",
    "plan_manager.commands.registration",
]

_register(register_custom_commands_hook)
