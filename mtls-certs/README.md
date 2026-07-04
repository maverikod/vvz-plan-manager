# mTLS Certificate Suite and Test Scripts

This archive contains the complete mTLS certificate infrastructure and test scripts for the MCP Proxy server.

## 📁 Contents

### Certificates (`mtls_certificates/`)
- **Root CA**: `ca/ca.crt`, `ca/ca.key` - Root Certificate Authority
- **Trust Store**: `truststore.pem` - Combined CA certificates for client verification
- **Server Certificates**: 
  - `mcp-proxy` - MCP Proxy server certificates
  - `embedding-service` - Embedding service certificates  
  - `svo-chunker` - SVO chunker service certificates
  - `chunk-writer` - Chunk writer service certificates
  - `chunk-retriever` - Chunk retriever service certificates
  - `doc-analyzer` - Document analyzer service certificates
  - `primitive-server` - Test server certificates
- **Client Certificates**: Corresponding client certificates for each service

### Test Scripts
- `start_and_register_server.py` - Complete test script that starts a server and registers it with MCP Proxy
- `simple_mtls_server.py` - Simple mTLS server implementation
- `register_primitive_server.py` - Registration script for primitive server

## 🚀 Quick Start

### 1. Start MCP Proxy Server
```bash
# In the main project directory
source .venv/bin/activate
python main.py --config config/mcp_config_host.json
```

### 2. Run Test Server with Auto-Registration
```bash
# From this archive directory
python start_and_register_server.py
```

### 3. Verify Registration
```bash
# Check registered servers
curl -s --cacert mtls_certificates/truststore.pem \
     --cert mtls_certificates/client/mcp-proxy.pem \
     --key mtls_certificates/client/mcp-proxy.pem \
     https://127.0.0.1:3004/proxy/discover | jq .
```

## 🔐 Certificate Details

### Root CA
- **Subject**: C=UA, ST=Kyiv, L=Kyiv, O=MCP-Proxy, OU=IT, CN=MCP-Proxy-Root-CA
- **Validity**: 10 years (2025-2035)
- **Key Size**: 4096 bits

### Server Certificates
- **Key Size**: 2048 bits
- **Validity**: 10 years (2025-2035)
- **SAN Extensions**: DNS names and IP addresses for localhost and Docker networks

### Client Certificates  
- **Key Size**: 2048 bits
- **Validity**: 10 years (2025-2035)
- **Purpose**: Client authentication for mTLS connections

## 🌐 Network Configuration

### MCP Proxy
- **MCP Interface**: `http://127.0.0.1:3002` (for Cursor AI)
- **OpenAPI Interface**: `https://0.0.0.0:3004` (for external servers with mTLS)

### Test Server
- **Server URL**: `https://127.0.0.1:8001`
- **Endpoints**:
  - `/health` - Health check
  - `/ping` - Ping endpoint
  - `/info` - Server information
  - `/openapi.json` - OpenAPI specification

## 🔧 Certificate Generation

To regenerate certificates, use the included script:
```bash
cd mtls_certificates
./generate_certs.sh
```

## 📋 Verification

Verify certificates with:
```bash
cd mtls_certificates
./verify_certs.sh
```

## 🛡️ Security Features

- **Mutual TLS (mTLS)**: Both client and server authenticate each other
- **Certificate-based Authentication**: No passwords required
- **Strong Encryption**: TLS 1.2+ with modern cipher suites
- **Certificate Validation**: Full chain validation with CRL support
- **Network Isolation**: Certificates include Docker network IPs

## 📝 Usage Examples

### Test Server Health
```bash
curl -s --cacert mtls_certificates/truststore.pem \
     --cert mtls_certificates/client/primitive-server.pem \
     --key mtls_certificates/client/primitive-server.pem \
     https://127.0.0.1:8001/health
```

### Register Custom Server
```bash
python register_primitive_server.py
```

### List All Registered Servers
```bash
curl -s --cacert mtls_certificates/truststore.pem \
     --cert mtls_certificates/client/mcp-proxy.pem \
     --key mtls_certificates/client/mcp-proxy.pem \
     https://127.0.0.1:3004/proxy/discover
```

## ⚠️ Important Notes

1. **Keep Private Keys Secure**: Never share private key files
2. **Certificate Expiry**: Certificates are valid for 10 years
3. **Network Access**: Ensure firewall allows connections on ports 3002, 3004, 8001
4. **Dependencies**: Requires Python 3.8+ with httpx, fastapi, uvicorn
5. **Virtual Environment**: Always use the project's virtual environment

## 🐛 Troubleshooting

### Common Issues
- **Certificate Verification Failed**: Ensure CA certificate is properly loaded
- **Connection Refused**: Check if MCP Proxy is running
- **Registration Failed**: Verify server is accessible before registration
- **SSL Context Errors**: Check certificate file paths and permissions

### Debug Mode
Run scripts with debug logging:
```bash
python start_and_register_server.py --debug
```

## 📞 Support

For issues or questions:
- **Author**: Vasiliy Zdanovskiy
- **Email**: vasilyvz@gmail.com
- **Project**: MCP Proxy Server

---

**Generated**: 2025-09-15  
**Version**: 1.0.0  
**Certificate Suite**: mTLS v1.0
