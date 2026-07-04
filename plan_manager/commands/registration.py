"""Registration entry points for the plan_manager command surface (C-024)."""

from importlib import import_module

from plan_manager.commands.inventory import INVENTORY


_REQUIRED_METADATA_KEYS: tuple[str, ...] = (
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
)


def _class_name(command_name: str) -> str:
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"


def register_all(registry) -> None:
    """Register every implemented command class of the normative inventory."""
    missing: list[str] = []
    for name in INVENTORY:
        module_name = f"plan_manager.commands.{name}_command"
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                missing.append(module_name)
                continue
            raise
        registry.register(getattr(module, _class_name(name)), "custom")
    if missing:
        raise RuntimeError(f"command inventory missing modules: {missing}")


def check_inventory(registry) -> None:
    """Verify the registry contains exactly the normative custom inventory."""
    if len(INVENTORY) != len(set(INVENTORY)):
        duplicates = sorted({name for name in INVENTORY if INVENTORY.count(name) > 1})
        raise RuntimeError(f"command inventory mismatch: duplicates={duplicates}")
    registered = set(registry.get_all_commands().keys())
    expected = set(INVENTORY)
    missing = sorted(expected - registered)
    command_types = getattr(registry, "_command_types", None)
    if isinstance(command_types, dict):
        extra = sorted(
            name
            for name in registered - expected
            if command_types.get(name) == "custom"
        )
    else:
        extra = sorted(registered - expected)
    if missing or extra:
        raise RuntimeError(f"command inventory mismatch: missing={missing} extra={extra}")


def probe_commands(registry) -> None:
    """Probe every plan_manager command for schema, metadata, and descr completeness."""
    commands = registry.get_all_commands()
    for name in INVENTORY:
        cls = commands[name]
        schema = cls.get_schema()
        if schema.get("type") != "object":
            raise RuntimeError(f"no-stub probe failed: command={name} key=type")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise RuntimeError(f"no-stub probe failed: command={name} key=properties")
        for prop_name, prop_schema in properties.items():
            if not prop_schema.get("type"):
                raise RuntimeError(
                    f"no-stub probe failed: command={name} key=properties.{prop_name}.type"
                )
            if not prop_schema.get("description"):
                raise RuntimeError(
                    f"no-stub probe failed: command={name} key=properties.{prop_name}.description"
                )
        if not isinstance(schema.get("required"), list):
            raise RuntimeError(f"no-stub probe failed: command={name} key=required")
        if schema.get("additionalProperties") is not False:
            raise RuntimeError(
                f"no-stub probe failed: command={name} key=additionalProperties"
            )

        meta = cls.metadata()
        for key in _REQUIRED_METADATA_KEYS:
            if not meta.get(key):
                raise RuntimeError(f"no-stub probe failed: command={name} key={key}")
        if not isinstance(getattr(cls, "descr", None), str) or not cls.descr.strip():
            raise RuntimeError(f"no-stub probe failed: command={name} key=descr")
