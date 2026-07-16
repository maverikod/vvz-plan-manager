"""Command dispatch mixin: thin async wrapper over the held JsonRpcClient.execute_command_unified.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class _CommandDispatchMixin:
    """Mixin providing the single dispatch point used by every command-family mixin.

    Assumes it is mixed into a class that stores a composed JsonRpcClient on the
    instance attribute ``self._rpc`` (an instance of
    mcp_proxy_adapter.client.jsonrpc_client.client.JsonRpcClient), which supplies
    the coroutine:

        async def execute_command_unified(
            self,
            command: str,
            params: Optional[Dict[str, Any]] = None,
            *,
            use_cmd_endpoint: bool = False,
            expect_queue: Optional[bool] = None,
            auto_poll: bool = True,
            poll_interval: float = 1.0,
            timeout: Optional[float] = None,
            status_hook: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
            manual_event_handling: bool = False,
        ) -> Any

    which returns {"mode": "immediate", "result": ...} for immediate commands or
    {"mode": "queued", "job_id": ..., "status": ..., "result": ...} for commands
    the server ran via the queue (auto_poll=True waits for completion via
    WebSocket before returning, applying queue_get_job_status semantics). The
    composed JsonRpcClient is held, never inherited, so no transport coroutine
    leaks onto the public facade surface.
    """

    async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Dispatch one plan_manager command and return its unwrapped result.

        Always calls self._rpc.execute_command_unified(command, params, auto_poll=True)
        so a queued command is auto-polled to completion (queue_get_job_status
        semantics) before this coroutine returns. Returns the "result" value from
        the unified response for both immediate and queued commands.
        """
        response = await self._rpc.execute_command_unified(  # type: ignore[attr-defined]
            command,
            params or {},
            auto_poll=True,
        )
        return response.get("result")


__all__ = ["_CommandDispatchMixin"]
