# mTLS Certificate Suite

**Author**: Vasiliy Zdanovskiy  
**Email**: vasilyvz@gmail.com

## Overview

This directory contains a complete mTLS (mutual TLS) certificate suite for the MCP-Proxy ecosystem. All certificates are signed by a custom Root CA and are valid for 10 years (until 2035).

## Certificate Structure

### Root CA
- **File**: `ca/ca.crt`, `ca/ca.key`
- **CN**: MCP-Proxy-Root-CA
- **Purpose**: Root Certificate Authority for the entire ecosystem

### Services
Each service has both server and client certificates:

1. **mcp-proxy** - Main MCP Proxy server
2. **embedding-service** - Embedding generation service
3. **svo-chunker** - SVO chunking service
4. **chunk-writer** - Chunk writing service
5. **chunk-retriever** - Chunk retrieval service
6. **doc-analyzer** - Document analysis service

### Certificate Types

#### Server Certificates
- **Location**: `server/{service-name}.crt`, `server/{service-name}.key`, `server/{service-name}.pem`
- **Purpose**: For services acting as TLS servers
- **SAN**: Includes service name, localhost, and common IP addresses
- **Key Usage**: Digital Signature, Key Encipherment
- **Extended Key Usage**: Server Authentication

#### Client Certificates
- **Location**: `client/{service-name}.crt`, `client/{service-name}.key`, `client/{service-name}.pem`
- **Purpose**: For services acting as TLS clients
- **SAN**: Includes service name and local variants
- **Key Usage**: Digital Signature, Key Encipherment
- **Extended Key Usage**: Client Authentication

#### Combined Certificates (.pem files)
- **Format**: Certificate + Private Key in PEM format
- **Usage**: Convenient for applications that expect combined files

## Trust Store

- **File**: `truststore.pem`
- **Content**: Root CA certificate
- **Usage**: Import this into your application's trust store

## Certificate Details

### Validity Period
- **Valid From**: September 14, 2025
- **Valid Until**: September 12, 2035 (10 years)

### Key Sizes
- **CA Key**: 4096 bits
- **Server Keys**: 2048 bits
- **Client Keys**: 2048 bits

### Subject Alternative Names (SAN)
Server certificates include:
- Service-specific DNS names
- `localhost`
- Common IP addresses: `127.0.0.1`, `172.20.0.1`, `172.24.0.1`

## Usage Examples

### Server Configuration
```python
# For a service acting as a server
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain('server/service-name.pem')
ssl_context.load_verify_locations('truststore.pem')
ssl_context.verify_mode = ssl.CERT_REQUIRED
```

### Client Configuration
```python
# For a service acting as a client
ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_cert_chain('client/service-name.pem')
ssl_context.load_verify_locations('truststore.pem')
ssl_context.verify_mode = ssl.CERT_REQUIRED
```

### Docker Configuration
```yaml
volumes:
  - ./certs/mtls/server/service-name.pem:/etc/ssl/certs/service.pem:ro
  - ./certs/mtls/truststore.pem:/etc/ssl/certs/ca.pem:ro
```

### curl Testing
```bash
# Test server with client certificate
curl --cert client/service-name.pem \
     --cacert truststore.pem \
     https://service-name:port/endpoint

# Test with combined certificate
curl --cert client/service-name.pem \
     --cacert truststore.pem \
     https://service-name:port/endpoint
```

## Security Notes

1. **Private Keys**: All private keys have restricted permissions (600)
2. **CA Key**: Keep the CA private key (`ca/ca.key`) secure and backed up
3. **Certificate Rotation**: Plan for certificate renewal before 2035
4. **Network Security**: These certificates are for internal service communication

## Regeneration

To regenerate all certificates:
```bash
./generate_certs.sh
```

**Warning**: Regenerating certificates will invalidate all existing certificates. Ensure all services are updated simultaneously.

## File Permissions

- **Private Keys**: 600 (owner read/write only)
- **Certificates**: 644 (owner read/write, group/other read)
- **Trust Store**: 644 (owner read/write, group/other read)

## Troubleshooting

### Certificate Verification
```bash
# Verify certificate against CA
openssl verify -CAfile truststore.pem server/service-name.crt

# Check certificate details
openssl x509 -in server/service-name.crt -text -noout
```

### Common Issues
1. **Certificate not trusted**: Ensure the CA certificate is in your trust store
2. **Hostname mismatch**: Check SAN entries in the certificate
3. **Expired certificate**: Check validity dates
4. **Wrong key usage**: Ensure certificate has appropriate key usage flags

## Support

For issues with certificates or mTLS configuration, contact:
- **Email**: vasilyvz@gmail.com
- **Project**: MCP-Proxy Ecosystem
