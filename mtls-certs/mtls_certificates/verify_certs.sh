#!/bin/bash

# Author: Vasiliy Zdanovskiy
# email: vasilyvz@gmail.com
# Certificate Verification Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Service names
SERVICES=(
    "mcp-proxy"
    "embedding-service"
    "svo-chunker"
    "chunk-writer"
    "chunk-retriever"
    "doc-analyzer"
)

echo -e "${BLUE}🔍 mTLS Certificate Verification${NC}"
echo -e "${BLUE}=================================${NC}"

# Function to verify certificate
verify_cert() {
    local cert_file=$1
    local cert_name=$2
    local expected_ca=$3
    
    echo -e "${YELLOW}📋 Verifying: $cert_name${NC}"
    
    if [ ! -f "$cert_file" ]; then
        echo -e "${RED}❌ Certificate file not found: $cert_file${NC}"
        return 1
    fi
    
    # Verify certificate against CA
    if openssl verify -CAfile "$expected_ca" "$cert_file" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Certificate is valid${NC}"
    else
        echo -e "${RED}❌ Certificate verification failed${NC}"
        return 1
    fi
    
    # Check certificate details
    local subject=$(openssl x509 -in "$cert_file" -subject -noout | sed 's/subject=//')
    local issuer=$(openssl x509 -in "$cert_file" -issuer -noout | sed 's/issuer=//')
    local not_before=$(openssl x509 -in "$cert_file" -startdate -noout | sed 's/notBefore=//')
    local not_after=$(openssl x509 -in "$cert_file" -enddate -noout | sed 's/notAfter=//')
    
    echo -e "   Subject: $subject"
    echo -e "   Issuer: $issuer"
    echo -e "   Valid From: $not_before"
    echo -e "   Valid Until: $not_after"
    
    # Check if certificate is expired
    if openssl x509 -in "$cert_file" -checkend 0 >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Certificate is not expired${NC}"
    else
        echo -e "${RED}❌ Certificate is expired${NC}"
        return 1
    fi
    
    echo ""
    return 0
}

# Function to verify private key
verify_private_key() {
    local key_file=$1
    local cert_file=$2
    local key_name=$3
    
    echo -e "${YELLOW}🔑 Verifying private key: $key_name${NC}"
    
    if [ ! -f "$key_file" ]; then
        echo -e "${RED}❌ Private key file not found: $key_file${NC}"
        return 1
    fi
    
    # Check if private key matches certificate
    local cert_modulus=$(openssl x509 -in "$cert_file" -modulus -noout | openssl md5)
    local key_modulus=$(openssl rsa -in "$key_file" -modulus -noout | openssl md5)
    
    if [ "$cert_modulus" = "$key_modulus" ]; then
        echo -e "${GREEN}✅ Private key matches certificate${NC}"
    else
        echo -e "${RED}❌ Private key does not match certificate${NC}"
        return 1
    fi
    
    echo ""
    return 0
}

# Function to verify combined certificate
verify_combined_cert() {
    local pem_file=$1
    local cert_name=$2
    
    echo -e "${YELLOW}🔗 Verifying combined certificate: $cert_name${NC}"
    
    if [ ! -f "$pem_file" ]; then
        echo -e "${RED}❌ Combined certificate file not found: $pem_file${NC}"
        return 1
    fi
    
    # Extract certificate and key from combined file
    local temp_cert=$(mktemp)
    local temp_key=$(mktemp)
    
    # Extract certificate
    openssl x509 -in "$pem_file" -out "$temp_cert" 2>/dev/null || {
        echo -e "${RED}❌ Failed to extract certificate from combined file${NC}"
        rm -f "$temp_cert" "$temp_key"
        return 1
    }
    
    # Extract private key
    openssl rsa -in "$pem_file" -out "$temp_key" 2>/dev/null || {
        echo -e "${RED}❌ Failed to extract private key from combined file${NC}"
        rm -f "$temp_cert" "$temp_key"
        return 1
    }
    
    # Verify extracted certificate
    if openssl verify -CAfile "truststore.pem" "$temp_cert" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Combined certificate is valid${NC}"
    else
        echo -e "${RED}❌ Combined certificate verification failed${NC}"
        rm -f "$temp_cert" "$temp_key"
        return 1
    fi
    
    # Check if private key matches
    local cert_modulus=$(openssl x509 -in "$temp_cert" -modulus -noout | openssl md5)
    local key_modulus=$(openssl rsa -in "$temp_key" -modulus -noout | openssl md5)
    
    if [ "$cert_modulus" = "$key_modulus" ]; then
        echo -e "${GREEN}✅ Private key matches certificate in combined file${NC}"
    else
        echo -e "${RED}❌ Private key does not match certificate in combined file${NC}"
        rm -f "$temp_cert" "$temp_key"
        return 1
    fi
    
    rm -f "$temp_cert" "$temp_key"
    echo ""
    return 0
}

# Main verification function
main() {
    local errors=0
    
    echo -e "${BLUE}Starting certificate verification...${NC}"
    echo ""
    
    # Verify Root CA
    echo -e "${BLUE}🏦 Verifying Root CA${NC}"
    echo -e "${BLUE}===================${NC}"
    if ! verify_cert "ca/ca.crt" "Root CA" "ca/ca.crt"; then
        ((errors++))
    fi
    echo ""
    
    # Verify each service's certificates
    for service in "${SERVICES[@]}"; do
        echo -e "${BLUE}🔧 Verifying certificates for: $service${NC}"
        echo -e "${BLUE}=====================================${NC}"
        
        # Verify server certificate
        if ! verify_cert "server/${service}.crt" "Server: $service" "truststore.pem"; then
            ((errors++))
        fi
        
        # Verify server private key
        if ! verify_private_key "server/${service}.key" "server/${service}.crt" "Server: $service"; then
            ((errors++))
        fi
        
        # Verify server combined certificate
        if ! verify_combined_cert "server/${service}.pem" "Server: $service"; then
            ((errors++))
        fi
        
        # Verify client certificate
        if ! verify_cert "client/${service}.crt" "Client: $service" "truststore.pem"; then
            ((errors++))
        fi
        
        # Verify client private key
        if ! verify_private_key "client/${service}.key" "client/${service}.crt" "Client: $service"; then
            ((errors++))
        fi
        
        # Verify client combined certificate
        if ! verify_combined_cert "client/${service}.pem" "Client: $service"; then
            ((errors++))
        fi
        
        echo ""
    done
    
    # Summary
    echo -e "${BLUE}📊 Verification Summary${NC}"
    echo -e "${BLUE}=======================${NC}"
    
    if [ $errors -eq 0 ]; then
        echo -e "${GREEN}🎉 All certificates verified successfully!${NC}"
        echo -e "${GREEN}✅ No errors found${NC}"
    else
        echo -e "${RED}❌ Verification completed with $errors errors${NC}"
        echo -e "${RED}⚠️  Please review the errors above${NC}"
    fi
    
    echo ""
    echo -e "${BLUE}📁 Certificate files verified:${NC}"
    echo -e "   Root CA: ca/ca.crt, ca/ca.key"
    echo -e "   Trust Store: truststore.pem"
    for service in "${SERVICES[@]}"; do
        echo -e "   $service:"
        echo -e "     Server: server/${service}.crt, server/${service}.key, server/${service}.pem"
        echo -e "     Client: client/${service}.crt, client/${service}.key, client/${service}.pem"
    done
    
    return $errors
}

# Run main function
main
