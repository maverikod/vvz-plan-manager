#!/bin/bash

# Author: Vasiliy Zdanovskiy
# email: vasilyvz@gmail.com
# mTLS Certificate Generation Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CA_KEY_SIZE=4096
SERVER_KEY_SIZE=2048
CLIENT_KEY_SIZE=2048
VALIDITY_DAYS=3650  # 10 years

# Service names
SERVICES=(
    "mcp-proxy"
    "embedding-service"
    "svo-chunker"
    "chunk-writer"
    "chunk-retriever"
    "doc-analyzer"
    "primitive-server"
)

echo -e "${BLUE}🔐 Generating mTLS Certificate Suite${NC}"
echo -e "${BLUE}=====================================${NC}"

# Function to generate CA
generate_ca() {
    echo -e "${YELLOW}📋 Generating Root CA...${NC}"
    
    # Generate CA private key
    openssl genrsa -out ca/ca.key $CA_KEY_SIZE
    chmod 600 ca/ca.key
    
    # Generate CA certificate
    openssl req -new -x509 -days $VALIDITY_DAYS -key ca/ca.key -out ca/ca.crt \
        -subj "/C=UA/ST=Kyiv/L=Kyiv/O=MCP-Proxy/OU=IT/CN=MCP-Proxy-Root-CA" \
        -config <(
            echo '[req]'
            echo 'distinguished_name = req'
            echo '[v3_ca]'
            echo 'basicConstraints = critical,CA:TRUE'
            echo 'keyUsage = critical,keyCertSign,cRLSign'
            echo 'subjectKeyIdentifier = hash'
        ) -extensions v3_ca
    
    echo -e "${GREEN}✅ Root CA generated: ca/ca.crt${NC}"
}

# Function to generate server certificate
generate_server_cert() {
    local service_name=$1
    echo -e "${YELLOW}🔧 Generating server certificate for: $service_name${NC}"
    
    # Generate server private key
    openssl genrsa -out server/${service_name}.key $SERVER_KEY_SIZE
    chmod 600 server/${service_name}.key
    
    # Generate server certificate signing request
    openssl req -new -key server/${service_name}.key -out server/${service_name}.csr \
        -subj "/C=UA/ST=Kyiv/L=Kyiv/O=MCP-Proxy/OU=Server/CN=${service_name}"
    
    # Generate server certificate
    openssl x509 -req -in server/${service_name}.csr -CA ca/ca.crt -CAkey ca/ca.key \
        -CAcreateserial -out server/${service_name}.crt -days $VALIDITY_DAYS \
        -extensions v3_server -extfile <(
            echo '[v3_server]'
            echo 'basicConstraints = CA:FALSE'
            echo 'keyUsage = critical,digitalSignature,keyEncipherment'
            echo 'extendedKeyUsage = serverAuth'
            echo 'subjectAltName = @alt_names'
            echo '[alt_names]'
            echo "DNS.1 = ${service_name}"
            echo "DNS.2 = ${service_name}.local"
            echo "DNS.3 = localhost"
            echo "IP.1 = 127.0.0.1"
            echo "IP.2 = 172.20.0.1"
            echo "IP.3 = 172.24.0.1"
        )
    
    # Clean up CSR
    rm server/${service_name}.csr
    
    echo -e "${GREEN}✅ Server certificate generated: server/${service_name}.crt${NC}"
}

# Function to generate client certificate
generate_client_cert() {
    local service_name=$1
    echo -e "${YELLOW}👤 Generating client certificate for: $service_name${NC}"
    
    # Generate client private key
    openssl genrsa -out client/${service_name}.key $CLIENT_KEY_SIZE
    chmod 600 client/${service_name}.key
    
    # Generate client certificate signing request
    openssl req -new -key client/${service_name}.key -out client/${service_name}.csr \
        -subj "/C=UA/ST=Kyiv/L=Kyiv/O=MCP-Proxy/OU=Client/CN=${service_name}-client"
    
    # Generate client certificate
    openssl x509 -req -in client/${service_name}.csr -CA ca/ca.crt -CAkey ca/ca.key \
        -CAcreateserial -out client/${service_name}.crt -days $VALIDITY_DAYS \
        -extensions v3_client -extfile <(
            echo '[v3_client]'
            echo 'basicConstraints = CA:FALSE'
            echo 'keyUsage = critical,digitalSignature,keyEncipherment'
            echo 'extendedKeyUsage = clientAuth'
            echo 'subjectAltName = @alt_names'
            echo '[alt_names]'
            echo "DNS.1 = ${service_name}-client"
            echo "DNS.2 = ${service_name}.local"
        )
    
    # Clean up CSR
    rm client/${service_name}.csr
    
    echo -e "${GREEN}✅ Client certificate generated: client/${service_name}.crt${NC}"
}

# Function to create combined certificates
create_combined_certs() {
    local service_name=$1
    echo -e "${YELLOW}🔗 Creating combined certificates for: $service_name${NC}"
    
    # Server combined (cert + key)
    cat server/${service_name}.crt server/${service_name}.key > server/${service_name}.pem
    chmod 600 server/${service_name}.pem
    
    # Client combined (cert + key)
    cat client/${service_name}.crt client/${service_name}.key > client/${service_name}.pem
    chmod 600 client/${service_name}.pem
    
    echo -e "${GREEN}✅ Combined certificates created${NC}"
}

# Function to create trust store
create_trust_store() {
    echo -e "${YELLOW}🏦 Creating trust store...${NC}"
    
    # Copy CA certificate to trust store
    cp ca/ca.crt truststore.pem
    chmod 644 truststore.pem
    
    echo -e "${GREEN}✅ Trust store created: truststore.pem${NC}"
}

# Function to display certificate info
display_cert_info() {
    local cert_file=$1
    local cert_name=$2
    
    echo -e "${BLUE}📄 Certificate Info: $cert_name${NC}"
    echo -e "${BLUE}====================${NC}"
    openssl x509 -in $cert_file -text -noout | grep -E "(Subject:|Issuer:|Not Before|Not After|DNS:|IP Address:)"
    echo ""
}

# Main execution
main() {
    echo -e "${BLUE}Starting certificate generation...${NC}"
    echo ""
    
    # Generate CA
    generate_ca
    echo ""
    
    # Generate certificates for each service
    for service in "${SERVICES[@]}"; do
        generate_server_cert $service
        generate_client_cert $service
        create_combined_certs $service
        echo ""
    done
    
    # Create trust store
    create_trust_store
    echo ""
    
    # Display certificate information
    echo -e "${BLUE}📋 Certificate Summary${NC}"
    echo -e "${BLUE}=====================${NC}"
    display_cert_info "ca/ca.crt" "Root CA"
    
    for service in "${SERVICES[@]}"; do
        display_cert_info "server/${service}.crt" "Server: $service"
        display_cert_info "client/${service}.crt" "Client: $service"
    done
    
    echo -e "${GREEN}🎉 All certificates generated successfully!${NC}"
    echo -e "${BLUE}📁 Certificate files:${NC}"
    echo -e "   CA: ca/ca.crt, ca/ca.key"
    echo -e "   Trust Store: truststore.pem"
    for service in "${SERVICES[@]}"; do
        echo -e "   $service:"
        echo -e "     Server: server/${service}.crt, server/${service}.key, server/${service}.pem"
        echo -e "     Client: client/${service}.crt, client/${service}.key, client/${service}.pem"
    done
}

# Run main function
main
