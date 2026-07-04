#!/usr/bin/env python3
"""
Primitive Server Registration Script
This script creates a simple HTTP server and registers it with the MCP Proxy in mTLS mode.
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""
import asyncio
import json
import logging
import ssl
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PrimitiveServer:
    """Simple HTTP server for testing mTLS registration."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8001, server_id: str = "primitive-server"):
        self.host = host
        self.port = port
        self.server_id = server_id
        self.app = FastAPI(
            title="Primitive Test Server",
            description="Simple server for testing mTLS registration with MCP Proxy",
            version="1.0.0"
        )
        self._setup_routes()
        
    def _setup_routes(self):
        """Setup server routes."""
        
        @self.app.get("/health")
        async def health():
            """Health check endpoint."""
            return {"status": "healthy", "message": "Primitive server is running"}
        
        @self.app.get("/ping")
        async def ping():
            """Ping endpoint."""
            return {"status": "pong", "message": "Server is alive"}
        
        @self.app.get("/info")
        async def info():
            """Server information endpoint."""
            return {
                "server_id": self.server_id,
                "host": self.host,
                "port": self.port,
                "status": "active",
                "capabilities": ["health", "ping", "info"]
            }
        
        @self.app.get("/openapi.json")
        async def openapi():
            """OpenAPI specification."""
            return self.app.openapi()
        
        @self.app.get("/")
        async def root():
            """Root endpoint."""
            return {
                "message": "Primitive Test Server",
                "endpoints": ["/health", "/ping", "/info", "/openapi.json"]
            }
    
    async def start(self):
        """Start the server."""
        logger.info(f"🚀 Starting primitive server on {self.host}:{self.port}")
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

class MCPProxyClient:
    """Client for registering with MCP Proxy in mTLS mode."""
    
    def __init__(self, proxy_url: str = "https://127.0.0.1:3004"):
        self.proxy_url = proxy_url
        self.ssl_context = self._create_ssl_context()
        
    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context for mTLS client connections."""
        try:
            ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            
            # Load CA certificate
            ca_file = "certs/mtls/truststore.pem"
            if Path(ca_file).exists():
                ssl_context.load_verify_locations(ca_file)
                logger.debug(f"Loaded CA certificate from {ca_file}")
            else:
                logger.warning(f"CA certificate file not found: {ca_file}")
                # Try alternative path
                alt_ca_file = "certs/mtls/ca/ca.crt"
                if Path(alt_ca_file).exists():
                    ssl_context.load_verify_locations(alt_ca_file)
                    logger.debug(f"Loaded CA certificate from {alt_ca_file}")
                else:
                    logger.warning(f"Alternative CA certificate file not found: {alt_ca_file}")
            
            # Load client certificate
            client_cert_file = "certs/mtls/client/primitive-server.pem"
            if Path(client_cert_file).exists():
                ssl_context.load_cert_chain(client_cert_file)
                logger.debug(f"Loaded client certificate from {client_cert_file}")
            else:
                # Fallback to mcp-proxy client cert
                fallback_cert = "certs/mtls/client/mcp-proxy.pem"
                if Path(fallback_cert).exists():
                    ssl_context.load_cert_chain(fallback_cert)
                    logger.debug(f"Loaded fallback client certificate from {fallback_cert}")
                else:
                    logger.warning(f"Client certificate not found: {client_cert_file} or {fallback_cert}")
            
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            logger.info("Created SSL context for mTLS client connection")
            return ssl_context
            
        except Exception as e:
            logger.error(f"Failed to create SSL context: {e}")
            return ssl.create_default_context()
    
    async def register_server(self, server_id: str, server_url: str, server_name: str, description: str) -> Optional[str]:
        """Register server with MCP Proxy."""
        try:
            registration_data = {
                "server_id": server_id,
                "server_url": server_url,
                "server_name": server_name,
                "description": description
            }
            
            async with httpx.AsyncClient(verify=self.ssl_context, timeout=30.0) as client:
                response = await client.post(
                    f"{self.proxy_url}/proxy/register",
                    json=registration_data,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    server_key = result.get("server_key")
                    logger.info(f"✅ Server registered successfully: {server_key}")
                    return server_key
                else:
                    logger.error(f"❌ Registration failed: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Registration error: {e}")
            return None
    
    async def check_health(self) -> bool:
        """Check MCP Proxy health."""
        try:
            async with httpx.AsyncClient(verify=self.ssl_context, timeout=10.0) as client:
                response = await client.get(f"{self.proxy_url}/health")
                if response.status_code == 200:
                    logger.info("✅ MCP Proxy is healthy")
                    return True
                else:
                    logger.error(f"❌ MCP Proxy health check failed: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"❌ Health check error: {e}")
            return False
    
    async def list_servers(self) -> Optional[Dict[str, Any]]:
        """List registered servers."""
        try:
            async with httpx.AsyncClient(verify=self.ssl_context, timeout=10.0) as client:
                response = await client.get(f"{self.proxy_url}/proxy/discover")
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"📋 Found {result.get('pagination', {}).get('total_servers', 0)} registered servers")
                    return result
                else:
                    logger.error(f"❌ Failed to list servers: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"❌ List servers error: {e}")
            return None

async def main():
    """Main function."""
    logger.info("🚀 Starting Primitive Server Registration Script")
    logger.info("=" * 60)
    
    # Configuration
    server_host = "127.0.0.1"
    server_port = 8001
    server_id = "primitive-server"
    server_name = "Primitive Test Server"
    server_description = "Simple test server for mTLS registration with MCP Proxy"
    proxy_url = "https://127.0.0.1:3004"
    
    # Create MCP Proxy client
    proxy_client = MCPProxyClient(proxy_url)
    
    # Check MCP Proxy health
    logger.info("🔍 Checking MCP Proxy health...")
    if not await proxy_client.check_health():
        logger.error("❌ MCP Proxy is not available. Exiting.")
        return
    
    # List current servers
    logger.info("📋 Listing current registered servers...")
    servers = await proxy_client.list_servers()
    if servers:
        for server in servers.get("servers", []):
            logger.info(f"  - {server.get('server_key')}: {server.get('server_name')}")
    
    # Create primitive server
    primitive_server = PrimitiveServer(
        host=server_host,
        port=server_port,
        server_id=server_id
    )
    
    # Register server
    server_url = f"http://{server_host}:{server_port}"
    logger.info(f"📝 Registering server: {server_id} at {server_url}")
    
    server_key = await proxy_client.register_server(
        server_id=server_id,
        server_url=server_url,
        server_name=server_name,
        description=server_description
    )
    
    if server_key:
        logger.info(f"✅ Registration successful! Server key: {server_key}")
        
        # List servers again to confirm
        logger.info("📋 Listing servers after registration...")
        servers = await proxy_client.list_servers()
        if servers:
            for server in servers.get("servers", []):
                if server.get("server_key") == server_key:
                    logger.info(f"  ✅ {server.get('server_key')}: {server.get('server_name')} - {server.get('status')}")
                else:
                    logger.info(f"  - {server.get('server_key')}: {server.get('server_name')}")
        
        # Start the primitive server
        logger.info("🚀 Starting primitive server...")
        logger.info(f"📡 Server will be available at: {server_url}")
        logger.info("🔍 Test endpoints:")
        logger.info(f"  - Health: {server_url}/health")
        logger.info(f"  - Ping: {server_url}/ping")
        logger.info(f"  - Info: {server_url}/info")
        logger.info(f"  - OpenAPI: {server_url}/openapi.json")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C to stop the server")
        
        try:
            await primitive_server.start()
        except KeyboardInterrupt:
            logger.info("🛑 Server stopped by user")
    else:
        logger.error("❌ Registration failed. Exiting.")
        return

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Script interrupted by user")
    except Exception as e:
        logger.error(f"❌ Script error: {e}")
        sys.exit(1)
