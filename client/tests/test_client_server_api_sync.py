"""Facade-completeness synchronisation test for plan_manager_client.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from plan_manager.commands.inventory import INVENTORY as LIVE_INVENTORY
from plan_manager_client.client import PlanManagerClient
from plan_manager_client.server_api import COMMAND_NAMES
from plan_manager_client.server_api import assert_facade_commands_registered
from plan_manager_client.server_api import assert_facade_complete
from plan_manager_client.server_api import assert_removed_commands_absent


def test_facade_is_complete() -> None:
    """Every canonical command name has a public async method on PlanManagerClient."""
    assert_facade_complete(PlanManagerClient)


def test_facade_has_no_orphaned_methods() -> None:
    """Every public async method on PlanManagerClient is a canonical command name."""
    assert_facade_commands_registered(PlanManagerClient)


def test_facade_has_no_removed_commands() -> None:
    """No facade method lingers for the (currently empty) set of removed commands.

    When a command is removed from the live catalog, add its name to the
    frozenset passed below; this test then fails until the corresponding
    facade method is deleted from every command-family mixin.
    """
    assert_removed_commands_absent(PlanManagerClient, frozenset())


def test_canonical_command_set_matches_live_inventory() -> None:
    """The client's canonical COMMAND_NAMES matches the server's live inventory exactly.

    LIVE_INVENTORY is plan_manager.commands.inventory.INVENTORY, the repo's
    own normative command list (C-024). This is the ONLY place in the
    plan_manager_client distribution that references plan_manager server
    code, and only from this test module, never from library code — the
    facade and canonical command-set module themselves stay import-independent
    of the server package.
    """
    assert COMMAND_NAMES == frozenset(LIVE_INVENTORY)
