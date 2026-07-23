"""Composed full-surface facade client for the plan_manager JSON-RPC API.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any

from mcp_proxy_adapter.client.jsonrpc_client.client import JsonRpcClient

from plan_manager_client.dispatch import _CommandDispatchMixin
from plan_manager_client.facade_agent_config_mixin import AgentConfigCommandsMixin
from plan_manager_client.facade_bug_project_mixin import BugProjectCommandsMixin
from plan_manager_client.facade_context_gate_mixin import ContextGateCommandsMixin
from plan_manager_client.facade_plan_hrs_mixin import PlanHrsCommandsMixin
from plan_manager_client.facade_runtime_mixin import RuntimeCommandsMixin
from plan_manager_client.facade_step_graph_mixin import StepGraphCommandsMixin


class PlanManagerClient(
    _CommandDispatchMixin,
    PlanHrsCommandsMixin,
    StepGraphCommandsMixin,
    ContextGateCommandsMixin,
    RuntimeCommandsMixin,
    BugProjectCommandsMixin,
    AgentConfigCommandsMixin,
):
    """Full command-surface facade for the plan_manager JSON-RPC API.

    Composes (HOLDS, never inherits) a
    mcp_proxy_adapter.client.jsonrpc_client.client.JsonRpcClient on the private
    attribute ``self._rpc``, which supplies transport (http/https/mTLS), token
    authentication, queued-job polling, and chunked file transfer with sha256
    verification and resume. Because the transport client is held rather than
    inherited, the network interaction is fully hidden: the public surface of
    this class is exactly one public async method per plan_manager command,
    contributed by the internal _call dispatch coroutine (queued-command
    auto-polling per queue_get_job_status semantics) from _CommandDispatchMixin
    and the six command-family mixins, together covering every name in
    plan_manager_client.server_api.COMMAND_NAMES. Construct directly with the
    JsonRpcClient constructor arguments, or via
    PlanManagerClient(**config.to_jsonrpc_kwargs()) using a
    plan_manager_client.config.ClientConnectionConfig instance. Connections are
    direct to the plan_manager server; this class performs no proxy call_server
    routing.
    """

    def __init__(self, **jsonrpc_kwargs: Any) -> None:
        """Compose the underlying JsonRpcClient from JsonRpcClient constructor kwargs.

        Accepts exactly the keyword arguments of
        mcp_proxy_adapter.client.jsonrpc_client.client.JsonRpcClient (protocol,
        host, port, token_header, token, cert, key, ca, check_hostname,
        timeout), so PlanManagerClient(**config.to_jsonrpc_kwargs()) from a
        plan_manager_client.config.ClientConnectionConfig works directly. The
        constructed client is stored on the private attribute self._rpc and is
        never exposed as a public method, keeping the public surface exactly the
        canonical command methods.
        """
        self._rpc = JsonRpcClient(**jsonrpc_kwargs)


__all__ = ["PlanManagerClient"]
