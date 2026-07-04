from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import check_inventory, probe_commands, register_all


class FakeRegistry:
    def __init__(self) -> None:
        self.commands = {}
        self._command_types = {}

    def register(self, command_class, command_type: str) -> None:
        self.commands[command_class.name] = command_class
        self._command_types[command_class.name] = command_type

    def get_all_commands(self) -> dict:
        return dict(self.commands)


def test_full_command_inventory_registers_and_passes_no_stub_probe() -> None:
    registry = FakeRegistry()

    register_all(registry)
    check_inventory(registry)
    probe_commands(registry)

    assert len(registry.get_all_commands()) == 41
    assert set(registry.get_all_commands()) == set(INVENTORY)
