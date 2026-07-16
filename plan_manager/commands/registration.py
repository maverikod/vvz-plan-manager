"""Registration entry points for the plan_manager command surface (C-024)."""

import time
from importlib import import_module
from typing import Any

from mcp_proxy_adapter.commands.result import ErrorResult

from plan_manager.commands.inventory import INVENTORY
from plan_manager.runtime.context import db_connection
from plan_manager.storage.command_metrics_store import record_command_metric


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


def _record_metric_best_effort(command_name: str, duration_ms: float, mode: str, outcome: str) -> None:
    """Record one CommandMetricRecord for this invocation, swallowing any exception.

    A metrics-write failure (including a database connection failure) must
    never fail or slow the real command whose invocation is being timed
    (C-005); this function therefore never raises.
    """
    try:
        with db_connection() as conn:
            record_command_metric(
                conn,
                command_name=command_name,
                duration_ms=duration_ms,
                mode=mode,
                outcome=outcome,
            )
    except Exception:
        pass


def _wrap_execute_with_timing(command_class: type, command_name: str) -> None:
    """Wrap command_class.execute so every invocation appends one CommandMetricRecord (C-005).

    Measures wall-clock duration around the original execute coroutine.
    mode is "queued" when the command class declares use_queue = True and
    "direct" otherwise. outcome is "error" when the result is an
    ErrorResult or the original execute raises, "success" otherwise. The
    metrics write goes through _record_metric_best_effort, which never
    raises, so the wrapped execute always returns the real result (or
    re-raises the real exception) unmodified and undelayed by any
    metrics-write failure. Idempotent: a command_class already wrapped by
    this function is returned untouched, so calling it more than once
    (e.g. across repeated register_all calls in tests) never double-wraps
    execute.
    """
    if getattr(command_class, "_command_metrics_wrapped", False):
        return
    original_execute = command_class.execute
    mode = "queued" if getattr(command_class, "use_queue", False) else "direct"

    async def _timed_execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            result = await original_execute(self, *args, **kwargs)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000.0
            _record_metric_best_effort(command_name, duration_ms, mode, "error")
            raise
        duration_ms = (time.monotonic() - start) * 1000.0
        outcome = "error" if isinstance(result, ErrorResult) else "success"
        _record_metric_best_effort(command_name, duration_ms, mode, outcome)
        return result

    command_class.execute = _timed_execute
    command_class._command_metrics_wrapped = True


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
        command_class = getattr(module, _class_name(name))
        _wrap_execute_with_timing(command_class, name)
        registry.register(command_class, "custom")
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
            if key not in meta:
                raise RuntimeError(f"no-stub probe failed: command={name} key={key}")
            if key != "parameters" and not meta.get(key):
                raise RuntimeError(f"no-stub probe failed: command={name} key={key}")
        if not isinstance(getattr(cls, "descr", None), str) or not cls.descr.strip():
            raise RuntimeError(f"no-stub probe failed: command={name} key=descr")
