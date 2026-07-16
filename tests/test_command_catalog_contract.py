from plan_manager.commands.inventory import INVENTORY
from plan_manager.views.command_catalog import build_command_catalog

def test_catalog_names_exactly_match_inventory() -> None:
    entries = build_command_catalog()
    catalog_names = [entry["name"] for entry in entries]
    catalog_name_set = set(catalog_names)
    inventory_name_set = set(INVENTORY)

    missing_from_catalog = inventory_name_set - catalog_name_set
    extra_in_catalog = catalog_name_set - inventory_name_set

    assert not missing_from_catalog, f"commands missing from catalog: {sorted(missing_from_catalog)}"
    assert not extra_in_catalog, f"catalog entries not present in inventory: {sorted(extra_in_catalog)}"

def test_catalog_has_no_duplicate_entry_names() -> None:
    entries = build_command_catalog()
    catalog_names = [entry["name"] for entry in entries]

    assert len(catalog_names) == len(set(catalog_names)), "duplicate command name(s) found in catalog entries"
