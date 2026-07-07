"""Tests for the platform ``health`` command override and service probes.

The override reports the availability of the required database and the
optional embedding service, turning the overall status to ``error`` only
when the required database is unreachable. It is registered as a builtin
replacement (not a domain command), so it must not disturb the normative
inventory (C-024). The embedding probe must honor the operator-configured
timeout so a healthy-but-slow service is not misreported as unreachable.
"""

import asyncio

from mcp_proxy_adapter.commands.health_command import HealthCommand as BuiltinHealth

from plan_manager.commands import health_command as hc
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import check_inventory, register_all
from plan_manager.hooks import register_health_override
from plan_manager.runtime import probes


class FakeRegistry:
    def __init__(self) -> None:
        self.commands = {}
        self._command_types = {}

    def register(self, command_class, command_type: str = "builtin") -> None:
        self.commands[command_class.name] = command_class
        self._command_types[command_class.name] = command_type

    def get_all_commands(self) -> dict:
        return dict(self.commands)


def _registry_with_full_surface() -> FakeRegistry:
    registry = FakeRegistry()
    registry.register(BuiltinHealth, "builtin")  # platform registers builtin first
    register_all(registry)
    register_health_override(registry)
    return registry


def test_override_wins_and_stays_out_of_inventory() -> None:
    registry = _registry_with_full_surface()
    # The override replaces the builtin under the same name.
    assert registry.commands["health"] is hc.HealthCommand
    assert registry._command_types["health"] == "builtin"
    # health is a platform override, never a member of the domain inventory.
    assert "health" not in INVENTORY
    # inventory invariants still hold with the override present.
    check_inventory(registry)


def test_health_metadata_is_complete() -> None:
    required = {
        "name", "version", "description", "category", "author", "email",
        "detailed_description", "parameters", "return_value",
        "usage_examples", "error_cases", "best_practices",
    }
    meta = hc.HealthCommand.metadata()
    assert required <= set(meta)
    assert meta["name"] == "health"
    assert meta["description"] == hc.HealthCommand.descr
    assert hc.HealthCommand.descr.strip()


def _run_health(monkeypatch, *, db: bool, embedding: str) -> dict:
    monkeypatch.setattr(hc, "probe_database", lambda: db)
    monkeypatch.setattr(hc, "probe_embedding", lambda: embedding)
    result = asyncio.run(hc.HealthCommand().execute())
    return result.data


def test_status_error_only_when_required_database_down(monkeypatch) -> None:
    data = _run_health(monkeypatch, db=False, embedding="unreachable")
    assert data["status"] == "error"
    services = data["components"]["services"]
    assert services["database"] == {"required": True, "available": False}
    assert services["embedding"]["required"] is False
    assert services["embedding"]["available"] is False
    assert services["embedding"]["state"] == "unreachable"


def test_optional_embedding_never_flips_status(monkeypatch) -> None:
    # Database up, embedding unreachable -> still ok (embedding is optional).
    data = _run_health(monkeypatch, db=True, embedding="unreachable")
    assert data["status"] == "ok"
    # Platform liveness fields from the builtin are preserved.
    assert "version" in data and "uptime" in data
    assert "commands" in data["components"]


def test_reachable_embedding_marked_available(monkeypatch) -> None:
    data = _run_health(monkeypatch, db=True, embedding="reachable")
    assert data["status"] == "ok"
    assert data["components"]["services"]["embedding"]["available"] is True


def test_probe_embedding_uses_configured_timeout(monkeypatch) -> None:
    captured: dict = {}

    class _Cfg:
        embedding_url = "https://embed.example:8001"
        embedding_timeout = 42.0

    def _fake_fetch(base_url, text, timeout):
        captured["base_url"] = base_url
        captured["timeout"] = timeout
        return [0.0, 1.0]

    monkeypatch.setattr(probes, "app_config", lambda: _Cfg())
    monkeypatch.setattr(probes, "fetch_vector", _fake_fetch)

    assert probes.probe_embedding() == probes.EMBEDDING_REACHABLE
    assert captured["base_url"] == "https://embed.example:8001"
    assert captured["timeout"] == 42.0  # configured timeout, not a hardcoded constant


def test_probe_embedding_unconfigured(monkeypatch) -> None:
    class _Cfg:
        embedding_url = None
        embedding_timeout = 30.0

    monkeypatch.setattr(probes, "app_config", lambda: _Cfg())
    assert probes.probe_embedding() == probes.EMBEDDING_UNCONFIGURED


def test_probe_embedding_unreachable(monkeypatch) -> None:
    class _Cfg:
        embedding_url = "https://embed.example:8001"
        embedding_timeout = 5.0

    def _raise(base_url, text, timeout):
        raise probes.EmbeddingUnavailable("boom")

    monkeypatch.setattr(probes, "app_config", lambda: _Cfg())
    monkeypatch.setattr(probes, "fetch_vector", _raise)
    assert probes.probe_embedding() == probes.EMBEDDING_UNREACHABLE
