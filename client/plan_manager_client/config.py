"""Direct-connection configuration for a single plan_manager_client server.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Optional


@dataclass(frozen=True)
class ClientConnectionConfig:
    """Direct-connection parameters for one JSON-RPC server.

    Mirrors, field for field, the constructor of
    mcp_proxy_adapter.client.jsonrpc_client.client.JsonRpcClient:

        def __init__(
            self,
            protocol: str = "http",
            host: str = "127.0.0.1",
            port: int = 8080,
            token_header: Optional[str] = None,
            token: Optional[str] = None,
            cert: Optional[str] = None,
            key: Optional[str] = None,
            ca: Optional[str] = None,
            check_hostname: bool = False,
            timeout: Optional[float] = None,
        ) -> None: ...

    Instances are immutable. Use to_jsonrpc_kwargs() to build the keyword
    arguments for JsonRpcClient(**kwargs) or for any other client built on the
    same constructor shape (for example a code-analysis-client construction
    helper), so one configuration entity serves either server.
    """

    protocol: str = "http"
    host: str = "127.0.0.1"
    port: int = 8080
    token_header: Optional[str] = None
    token: Optional[str] = None
    cert: Optional[str] = None
    key: Optional[str] = None
    ca: Optional[str] = None
    check_hostname: bool = False
    timeout: Optional[float] = None

    def to_jsonrpc_kwargs(self) -> dict[str, Any]:
        """Return constructor kwargs for JsonRpcClient(**kwargs)."""
        return {
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "token_header": self.token_header,
            "token": self.token,
            "cert": self.cert,
            "key": self.key,
            "ca": self.ca,
            "check_hostname": self.check_hostname,
            "timeout": self.timeout,
        }


__all__ = ["ClientConnectionConfig"]
