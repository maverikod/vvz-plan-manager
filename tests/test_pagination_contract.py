"""Contract tests for CR-1 obligation: pagination is present and uniform on every
list-retrieval command (C-016, DeliveryAcceptance).

Every command in the normative INVENTORY whose name ends with "_list" must expose,
in both its JSON schema properties and its metadata parameters, the identical
pagination fragment (limit, offset) defined once in
plan_manager.commands.runtime_filtering. This is checked dynamically against the
live command inventory so newly added list commands are covered automatically.
"""
from __future__ import annotations

from importlib import import_module

import pytest

from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
)

def _class_name(command_name: str) -> str:
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"

def _load_command_class(name: str):
    module = import_module(f"plan_manager.commands.{name}_command")
    return getattr(module, _class_name(name))

_LIST_COMMANDS: list[str] = sorted(name for name in INVENTORY if name.endswith("_list"))

def test_at_least_one_list_command_exists() -> None:
    assert _LIST_COMMANDS

@pytest.mark.parametrize("name", _LIST_COMMANDS)
def test_list_command_schema_exposes_uniform_pagination(name: str) -> None:
    cls = _load_command_class(name)
    schema_properties = cls.get_schema()["properties"]
    expected = pagination_schema_properties()
    for field_name, expected_prop in expected.items():
        assert field_name in schema_properties, f"{name}: missing schema property {field_name!r}"
        assert schema_properties[field_name] == expected_prop, (
            f"{name}: schema property {field_name!r} does not match the uniform pagination fragment: "
            f"got {schema_properties[field_name]!r}, expected {expected_prop!r}"
        )

@pytest.mark.parametrize("name", _LIST_COMMANDS)
def test_list_command_metadata_exposes_uniform_pagination(name: str) -> None:
    cls = _load_command_class(name)
    metadata_parameters = cls.metadata()["parameters"]
    expected = pagination_metadata_params()
    for field_name, expected_param in expected.items():
        assert field_name in metadata_parameters, f"{name}: missing metadata parameter {field_name!r}"
        assert metadata_parameters[field_name] == expected_param, (
            f"{name}: metadata parameter {field_name!r} does not match the uniform pagination fragment: "
            f"got {metadata_parameters[field_name]!r}, expected {expected_param!r}"
        )
