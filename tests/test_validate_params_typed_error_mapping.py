"""Regression tests for bug 0d8755bd-066d-4d42-a3d2-f71389c190df.

A bare ``raise ValueError(...)`` inside a Command's ``validate_params``
override is invisible to the adapter's typed-error mapping in
``mcp_proxy_adapter.commands.base.Command.run``: that classmethod only
special-cases ``ValidationError`` / ``InvalidParamsError`` / ``NotFoundError``
/ ``TimeoutError`` / ``CommandError``; anything else falls through to the
generic ``except Exception`` branch and surfaces as a raw JSON-RPC -32603
"Unexpected error executing command ..." with the original message buried in
``details.original_error`` and a full traceback logged server-side, instead
of a clean -32602 invalid-params ErrorResult.

These tests drive the real adapter dispatch path (``Command.run``, the same
classmethod the JSON-RPC handler calls), not ``execute()`` directly (every
prior test in this suite calls ``execute()`` directly, which is exactly why
this defect went undetected: it bypasses ``validate_params`` entirely and
never touches ``run()``'s error mapping).
"""
from __future__ import annotations

import asyncio

import pytest
from mcp_proxy_adapter.commands import command_registry as command_registry_module
from mcp_proxy_adapter.commands.command_registry import CommandRegistry
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.plan_validate_command import PlanValidateCommand


@pytest.fixture()
def isolated_registry(monkeypatch):
    """Swap the adapter's global command registry for a throwaway instance.

    ``Command.run`` re-imports ``registry`` from
    ``mcp_proxy_adapter.commands.command_registry`` on every call (a local
    import inside the method body), so patching the module attribute here is
    picked up live without touching the real process-wide singleton that
    other tests / the running server may depend on.
    """
    registry = CommandRegistry()
    registry.register(PlanValidateCommand, "custom")
    monkeypatch.setattr(command_registry_module, "registry", registry)
    return registry


def test_branch_scope_missing_step_ids_is_typed_invalid_params(isolated_registry) -> None:
    """scope='branch' without gs/ts/as_step_id must map to a clean -32602, not -32603."""
    result = asyncio.run(PlanValidateCommand.run(plan="some-plan", scope="branch"))
    payload = result.to_dict()

    assert payload["success"] is False
    error = payload["error"]
    assert error["code"] == InvalidParamsError().code == -32602
    assert "Unexpected error" not in error["message"]
    assert "gs_step_id, ts_step_id, and as_step_id are all required" in error["message"]
    # The bug's symptom: the original ValueError text demoted to a details blob
    # instead of being the actual typed error message.
    assert "original_error" not in payload["error"].get("data", {})


def test_plan_scope_with_step_id_present_is_typed_invalid_params(isolated_registry) -> None:
    """scope='plan' with a step id present must map to a clean -32602, not -32603."""
    result = asyncio.run(
        PlanValidateCommand.run(plan="some-plan", scope="plan", gs_step_id="G-001")
    )
    payload = result.to_dict()

    assert payload["success"] is False
    error = payload["error"]
    assert error["code"] == InvalidParamsError().code == -32602
    assert "Unexpected error" not in error["message"]
    assert "gs_step_id, ts_step_id, and as_step_id must be absent" in error["message"]
    assert "original_error" not in payload["error"].get("data", {})
