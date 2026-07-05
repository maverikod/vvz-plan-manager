import inspect
import importlib
from typing import Any

from mcp_proxy_adapter.commands.command_help_info import build_command_help_payload

from plan_manager import hooks
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


def _annotation_json_type(annotation: Any) -> str | None:
    if annotation is inspect.Signature.empty:
        return None
    text = str(annotation).replace("typing.", "")
    if text.startswith("<class '"):
        text = text.removeprefix("<class '").removesuffix("'>")
    return {
        "str": "string",
        "str | None": "string",
        "Optional[str]": "string",
        "int": "integer",
        "bool": "boolean",
        "dict": "object",
        "dict[str, Any]": "object",
        "dict[str, typing.Any]": "object",
        "list[str] | None": "array",
    }.get(text)


def test_full_command_inventory_registers_and_passes_no_stub_probe() -> None:
    registry = FakeRegistry()

    register_all(registry)
    check_inventory(registry)
    probe_commands(registry)

    assert len(registry.get_all_commands()) == 41
    assert set(registry.get_all_commands()) == set(INVENTORY)


def test_every_command_has_rich_adapter_visible_help() -> None:
    registry = FakeRegistry()
    register_all(registry)

    for name, cls in registry.get_all_commands().items():
        payload = build_command_help_payload(name, cls, "custom")
        metadata = payload["metadata"]
        ai_metadata = payload["ai_metadata"]
        schema = payload["schema"]

        for key in (
            "detailed_description",
            "parameters",
            "return_value",
            "usage_examples",
            "error_cases",
            "best_practices",
        ):
            assert key in metadata, name
            assert key in ai_metadata, name

        assert metadata["detailed_description"].strip(), name
        assert metadata["usage_examples"], name
        assert all(example.get("description") for example in metadata["usage_examples"]), name
        assert all(isinstance(example.get("command"), dict) for example in metadata["usage_examples"]), name
        assert set(metadata["parameters"]) == set(schema.get("properties", {})), name


def test_command_metadata_schema_and_code_contracts_match() -> None:
    registry = FakeRegistry()
    register_all(registry)

    required_metadata = {
        "name",
        "version",
        "description",
        "category",
        "author",
        "email",
        "detailed_description",
        "parameters",
        "return_value",
        "usage_examples",
        "error_cases",
        "best_practices",
    }

    for name, cls in registry.get_all_commands().items():
        schema = cls.get_schema()
        metadata = cls.metadata()
        signature = inspect.signature(cls.execute)

        assert set(metadata) >= required_metadata, name
        assert metadata["name"] == cls.name, name
        assert metadata["version"] == cls.version, name
        assert metadata["description"] == cls.descr, name
        assert metadata["category"] == cls.category, name
        assert metadata["author"] == cls.author, name
        assert metadata["email"] == cls.email, name

        assert schema["type"] == "object", name
        assert isinstance(schema["properties"], dict), name
        assert isinstance(schema["required"], list), name
        assert len(schema["required"]) == len(set(schema["required"])), name
        assert schema["additionalProperties"] is False, name
        assert set(schema["required"]) <= set(schema["properties"]), name

        metadata_parameters = metadata["parameters"]
        schema_properties = schema["properties"]
        assert isinstance(metadata_parameters, dict), name
        assert set(metadata_parameters) == set(schema_properties), name

        for parameter_name, property_schema in schema_properties.items():
            metadata_parameter = metadata_parameters[parameter_name]
            assert property_schema["type"] == metadata_parameter["type"], name
            assert property_schema["description"].strip(), name
            assert metadata_parameter["description"].strip(), name
            assert metadata_parameter["required"] is (
                parameter_name in schema["required"]
            ), name

        execute_parameters = {}
        accepts_kwargs = False
        for parameter_name, parameter in signature.parameters.items():
            if parameter_name in {"self", "context"}:
                continue
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                accepts_kwargs = True
                continue
            execute_parameters[parameter_name] = parameter

        if not accepts_kwargs:
            assert set(execute_parameters) == set(schema_properties), name
            for parameter_name, parameter in execute_parameters.items():
                assert (
                    parameter.default is inspect.Parameter.empty
                ) is (parameter_name in schema["required"]), name
                json_type = _annotation_json_type(parameter.annotation)
                if json_type is not None:
                    assert schema_properties[parameter_name]["type"] == json_type, name

        for example in metadata["usage_examples"]:
            command = example["command"]
            assert isinstance(command, dict), name
            assert set(command) <= set(schema_properties), name
            assert set(schema["required"]) <= set(command), name


def test_command_execute_signatures_accept_adapter_context() -> None:
    registry = FakeRegistry()
    register_all(registry)

    for name, cls in registry.get_all_commands().items():
        signature = inspect.signature(cls.execute)
        parameters = signature.parameters.values()
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
        )
        assert accepts_kwargs or "context" in signature.parameters, name


def test_command_execute_methods_are_async_for_adapter_await() -> None:
    registry = FakeRegistry()
    register_all(registry)

    for name, cls in registry.get_all_commands().items():
        assert inspect.iscoroutinefunction(cls.execute), name


def test_queue_worker_auto_imports_runtime_bootstrap() -> None:
    modules = hooks.register_custom_commands_hook.__auto_import_modules__

    assert "plan_manager.runtime.worker_bootstrap" in modules
    importlib.import_module("plan_manager.runtime.worker_bootstrap")
