"""Timeout forwarding and live-smoke watchdog regression matrix.

Bug 0107: the PlanManagerClient facade accepted a configured transport
timeout but did not forward it to the adapter's queued command call, while the
live-smoke verifier had no per-call outer watchdog.  A stuck WebSocket terminal
wait could therefore outlive the requested client timeout and stall cleanup.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CLIENT_SRC = REPO_ROOT / "client"
for _path in (str(SCRIPTS_DIR), str(CLIENT_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import live_smoke as ls  # noqa: E402
import plan_manager_client.client as client_module  # noqa: E402
from plan_manager_client.client import PlanManagerClient  # noqa: E402


class _RecordingJsonRpcClient:
    def __init__(self, **kwargs: Any) -> None:
        self.timeout = kwargs.get("timeout")
        self.calls: list[dict[str, Any]] = []
        self.outcome: Any = {"result": {"ok": True}}

    async def execute_command_unified(
        self,
        command: str,
        params: dict[str, Any] | None = None,
        *,
        auto_poll: bool = True,
        timeout: float | None = None,
        manual_event_handling: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "command": command,
                "params": params or {},
                "auto_poll": auto_poll,
                "timeout": timeout,
                "manual_event_handling": manual_event_handling,
            }
        )
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        assert isinstance(self.outcome, dict)
        return self.outcome


def test_plan_manager_client_forwards_configured_timeout_to_unified_adapter(monkeypatch: Any) -> None:
    created: list[_RecordingJsonRpcClient] = []

    def _factory(**kwargs: Any) -> _RecordingJsonRpcClient:
        rpc = _RecordingJsonRpcClient(**kwargs)
        created.append(rpc)
        return rpc

    monkeypatch.setattr(client_module, "JsonRpcClient", _factory)
    client = PlanManagerClient(timeout=2.5)

    assert asyncio.run(client._call("plan_create", {"name": "timeout-probe"})) == {"ok": True}
    assert created[0].calls == [
        {
            "command": "plan_create",
            "params": {"name": "timeout-probe"},
            "auto_poll": True,
            "timeout": 2.5,
            "manual_event_handling": False,
        }
    ]


def test_plan_manager_client_preserves_terminal_success_and_error_semantics(monkeypatch: Any) -> None:
    created: list[_RecordingJsonRpcClient] = []

    def _factory(**kwargs: Any) -> _RecordingJsonRpcClient:
        rpc = _RecordingJsonRpcClient(**kwargs)
        created.append(rpc)
        return rpc

    monkeypatch.setattr(client_module, "JsonRpcClient", _factory)
    client = PlanManagerClient(timeout=1.0)
    created[0].outcome = {"result": {"uuid": "plan-1"}}
    assert asyncio.run(client._call("plan_create", {"name": "ok"})) == {"uuid": "plan-1"}

    created[0].outcome = TimeoutError("adapter timeout")
    try:
        asyncio.run(client._call("plan_create", {"name": "fail"}))
    except TimeoutError as exc:
        assert str(exc) == "adapter timeout"
    else:
        raise AssertionError("adapter timeout exception must propagate unchanged")


class _SmokeFakeRpc:
    def __init__(self, outer: "_SmokeFakeClient") -> None:
        self._outer = outer

    async def execute_command(self, name: str, params: dict[str, Any] | None = None, use_cmd_endpoint: bool = False) -> Any:
        self._outer.direct_calls.append((name, params or {}))
        return {"success": True, "data": {"direct": True}}


class _SmokeFakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.queued_calls: list[tuple[str, dict[str, Any]]] = []
        self.direct_calls: list[tuple[str, dict[str, Any]]] = []
        self._rpc = _SmokeFakeRpc(self)

    async def _call(self, name: str, params: dict[str, Any] | None = None) -> Any:
        self.queued_calls.append((name, params or {}))
        outcome = self._outcomes.pop(0)
        if outcome == "never":
            await asyncio.Event().wait()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _run_with_watchdog(coro: Any, *, timeout: float = 0.02, grace: float = 0.03) -> Any:
    ls.configure_call_watchdog(timeout, grace_seconds=grace)
    try:
        return asyncio.run(coro)
    finally:
        ls.configure_call_watchdog(None)


def test_live_smoke_immediate_non_queued_result_is_unchanged() -> None:
    client = _SmokeFakeClient([{"success": True, "data": {"ok": True}}])

    ok, data = _run_with_watchdog(ls.call(client, "info", {}))

    assert ok is True
    assert data == {"ok": True}
    assert client.queued_calls == [("info", {})]


def test_live_smoke_terminal_success_and_error_are_preserved() -> None:
    success_client = _SmokeFakeClient([{"job_id": "j1", "status": "completed", "result": {"success": True, "data": {"ok": True}}}])
    assert _run_with_watchdog(ls.call(success_client, "plan_list", {})) == (True, {"ok": True})

    error_client = _SmokeFakeClient([{"job_id": "j2", "status": "failed", "result": {"error": "boom"}}])
    ok, diagnostic = _run_with_watchdog(ls.call(error_client, "plan_list", {}))
    assert ok is False
    assert "non-success/incomplete envelope" in diagnostic


def test_live_smoke_adapter_timeout_returns_before_outer_watchdog() -> None:
    client = _SmokeFakeClient([asyncio.TimeoutError("adapter call timeout")])
    started = time.monotonic()

    ok, diagnostic = _run_with_watchdog(ls.call(client, "plan_create", {"name": "probe"}), timeout=0.01, grace=0.5)

    elapsed = time.monotonic() - started
    assert ok is False
    assert "adapter call timeout" in diagnostic
    assert "outer watchdog" not in diagnostic
    assert elapsed < 0.5


def test_live_smoke_manual_or_async_queue_handoff_is_not_labeled_a_leak() -> None:
    client = _SmokeFakeClient([{"mode": "queued", "status": "pending", "job_id": "j3", "manual_event_handling": True, "result": None}])

    ok, diagnostic = _run_with_watchdog(ls.call(client, "plan_create", {"name": "manual"}))

    assert ok is False
    assert "non-success/incomplete envelope" in diagnostic
    assert "outer watchdog" not in diagnostic
    assert client.direct_calls == []


def test_live_smoke_outer_watchdog_bounds_non_returning_call_and_cleanup_can_continue() -> None:
    client = _SmokeFakeClient(["never", {"success": True, "data": {"deleted": True}}])
    started = time.monotonic()

    ok, diagnostic = _run_with_watchdog(ls.call(client, "plan_create", {"name": "hang"}), timeout=0.01, grace=0.02)

    elapsed = time.monotonic() - started
    assert ok is False
    assert "outer watchdog" in diagnostic
    assert elapsed < 1.0
    assert _run_with_watchdog(ls.call(client, "plan_delete", {"plan": "scratch", "hard": True})) == (True, {"deleted": True})
