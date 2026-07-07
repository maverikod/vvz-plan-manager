"""Startup hook wiring the plan_manager command surface into the adapter."""

from mcp_proxy_adapter.commands.hooks import register_custom_commands_hook as _register

from plan_manager.commands.health_command import HealthCommand
from plan_manager.commands.registration import (
    check_inventory,
    probe_commands,
    register_all,
)


def register_health_override(registry) -> None:
    """Replace the platform builtin ``health`` command with the plan_manager one.

    Registered as a ``builtin`` replacement rather than a ``custom`` command:
    it overrides a platform command instead of adding a domain one, so it is
    kept out of the normative inventory (C-024) and its inventory probe. The
    custom-commands hook runs after the platform registers its builtins, so
    this registration wins at dispatch by overwriting the ``health`` entry.
    """
    registry.register(HealthCommand, "builtin")


def register_custom_commands_hook(registry) -> None:
    """Register the full command surface and enforce startup invariants."""
    register_all(registry)
    register_health_override(registry)
    check_inventory(registry)
    probe_commands(registry)


register_custom_commands_hook.__auto_import_modules__ = [
    "plan_manager.runtime.worker_bootstrap",
    "plan_manager.hooks",
    "plan_manager.commands.registration",
]

_register(register_custom_commands_hook)
