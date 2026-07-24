"""Startup hook wiring the plan_manager command surface into the adapter."""

from mcp_proxy_adapter.commands.hooks import register_custom_commands_hook as _register

from plan_manager.commands.health_command import HealthCommand
from plan_manager.commands.help_command import HelpCommand
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


def register_help_override(registry) -> None:
    """Replace the platform builtin ``help`` command with the plan_manager one.

    Same pattern as ``register_health_override`` above (bug 507b74ae): the
    plan_manager ``HelpCommand`` adds bounded limit/offset pagination to the
    no-cmdname catalog only; ``cmdname=...`` detail output is delegated to
    the builtin unchanged. Registered as a ``builtin`` replacement, kept out
    of the normative inventory (C-024) and its probe, same reasoning as the
    ``health`` override: it replaces a platform command rather than adding a
    domain one. The custom-commands hook runs after the platform registers
    its builtins, so this registration wins at dispatch by overwriting the
    ``help`` entry.
    """
    registry.register(HelpCommand, "builtin")


def register_custom_commands_hook(registry) -> None:
    """Register the full command surface and enforce startup invariants."""
    register_all(registry)
    register_health_override(registry)
    register_help_override(registry)
    check_inventory(registry)
    probe_commands(registry)


register_custom_commands_hook.__auto_import_modules__ = [
    "plan_manager.runtime.worker_bootstrap",
    "plan_manager.hooks",
    "plan_manager.commands.registration",
]

_register(register_custom_commands_hook)
