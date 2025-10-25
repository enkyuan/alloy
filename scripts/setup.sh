#!/bin/bash

# Modal Environment Setup Script
# Generates Supabase JWT keys, syncs .env files, and configures iOS app

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Define .env locations
DOCKER_ENV="$PROJECT_ROOT/docker/.env"
API_ENV="$PROJECT_ROOT/apps/api/.env"
IOS_CONFIG="$PROJECT_ROOT/apps/modal/Config.xcconfig"

echo -e "${BLUE}=== Modal Environment Configuration ===${NC}\n"

# Check required commands
command -v openssl >/dev/null 2>&1 || { echo -e "${RED}Error: openssl required${NC}" >&2; exit 1; }

# Base64url encode function
base64url_encode() {
    openssl base64 -e -A | tr '+/' '-_' | tr -d '='
}

# Create JWT function
create_jwt() {
    local role=$1
    local secret=$2
    local expiry=$3
    
    header='{"alg":"HS256","typ":"JWT"}'
    payload="{\"iss\":\"supabase\",\"role\":\"$role\",\"iat\":$(date +%s),\"exp\":$expiry}"
    
    header_base64=$(echo -n "$header" | base64url_encode)
    payload_base64=$(echo -n "$payload" | base64url_encode)
    signature=$(echo -n "${header_base64}.${payload_base64}" | openssl dgst -sha256 -hmac "$secret" -binary | base64url_encode)
    
    echo "${header_base64}.${payload_base64}.${signature}"
}

# Update env var function
update_env_var() {
    local file=$1
    local key=$2
    local value=$3
    
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i.tmp "s|^${key}=.*|${key}=${value}|" "$file" && rm -f "$file.tmp"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

echo -e "${BLUE}=== JWT Configuration ===${NC}\n"

# Check for existing JWT_SECRET
EXISTING_JWT_SECRET=""
if [ -f "$DOCKER_ENV" ] && grep -q "^JWT_SECRET=" "$DOCKER_ENV"; then
    EXISTING_JWT_SECRET=$(grep "^JWT_SECRET=" "$DOCKER_ENV" | cut -d= -f2)
    echo -e "${YELLOW}Found existing JWT_SECRET${NC}"
    read -p "Use existing? (Y/n): " -n 1 -r
    echo
    [[ $REPLY =~ ^[Nn]$ ]] && EXISTING_JWT_SECRET=""
fi

# Generate or use existing
if [ -n "$EXISTING_JWT_SECRET" ]; then
    JWT_SECRET="$EXISTING_JWT_SECRET"
    echo -e "${GREEN}✓ Using existing JWT secret${NC}"
else
    JWT_SECRET=$(openssl rand -base64 32 | tr -d '\n')
    echo -e "${GREEN}✓ Generated new JWT secret${NC}"
fi

# Generate keys (year 2099 expiry)
EXPIRY_DATE=4102444800
ANON_KEY=$(create_jwt "anon" "$JWT_SECRET" "$EXPIRY_DATE")
SERVICE_ROLE_KEY=$(create_jwt "service_role" "$JWT_SECRET" "$EXPIRY_DATE")
echo -e "${GREEN}✓ Generated ANON_KEY and SERVICE_ROLE_KEY${NC}"

# Get OAuth credentials
echo -e "\n${BLUE}=== OAuth Configuration ===${NC}"

GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""
SPOTIFY_CLIENT_ID=""
SPOTIFY_CLIENT_SECRET=""
SONIOX_API_KEY=""

if [ -f "$DOCKER_ENV" ]; then
    GOOGLE_CLIENT_ID=$(grep "^GOOGLE_CLIENT_ID=" "$DOCKER_ENV" 2>/dev/null | cut -d= -f2 || echo "")
    GOOGLE_CLIENT_SECRET=$(grep "^GOOGLE_CLIENT_SECRET=" "$DOCKER_ENV" 2>/dev/null | cut -d= -f2 || echo "")
    SPOTIFY_CLIENT_ID=$(grep "^SPOTIFY_CLIENT_ID=" "$DOCKER_ENV" 2>/dev/null | cut -d= -f2 || echo "")
    SPOTIFY_CLIENT_SECRET=$(grep "^SPOTIFY_CLIENT_SECRET=" "$DOCKER_ENV" 2>/dev/null | cut -d= -f2 || echo "")
    SONIOX_API_KEY=$(grep "^SONIOX_API_KEY=" "$DOCKER_ENV" 2>/dev/null | cut -d= -f2 || echo "")
fi

read -p "Update OAuth credentials? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Google Client ID: " GOOGLE_CLIENT_ID
    read -p "Google Client Secret: " GOOGLE_CLIENT_SECRET
    read -p "Spotify Client ID: " SPOTIFY_CLIENT_ID
    read -p "Spotify Client Secret: " SPOTIFY_CLIENT_SECRET
    read -p "Soniox API Key: " SONIOX_API_KEY
fi

# Generate security keys
SECRET_KEY_BASE=$(openssl rand -base64 48 | tr -d '\n')
VAULT_ENC_KEY=$(openssl rand -base64 24 | tr -d '\n')
LOGFLARE_PUBLIC_TOKEN=$(openssl rand -hex 16)
LOGFLARE_PRIVATE_TOKEN=$(openssl rand -hex 16)

echo -e "\n${BLUE}=== Creating docker/.env ===${NC}"

cat > "$DOCKER_ENV" << EOF
# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_PASSWORD=postgres

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Supabase Configuration
SUPABASE_URL=http://localhost:8001
SUPABASE_PUBLIC_URL=http://localhost:8001
SUPABASE_KONG_URL=http://kong:8000
SUPABASE_ANON_KEY=${ANON_KEY}
SUPABASE_SERVICE_ROLE_KEY=${SERVICE_ROLE_KEY}

# JWT Configuration
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXPIRY=3600
ACCESS_TOKEN_EXPIRE_MINUTES=30

# API Configuration
DEBUG=false
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API
API_PORT=8080
API_EXTERNAL_URL=http://localhost:8001
SITE_URL=http://localhost:3000
ADDITIONAL_REDIRECT_URLS=modal://auth/callback,modal://spotify/callback
DISABLE_SIGNUP=false

# Email Configuration
ENABLE_EMAIL_SIGNUP=true
ENABLE_EMAIL_AUTOCONFIRM=true
ENABLE_ANONYMOUS_USERS=false

# Phone Configuration
ENABLE_PHONE_SIGNUP=false
ENABLE_PHONE_AUTOCONFIRM=false

# SMTP Configuration
SMTP_ADMIN_EMAIL=admin@example.com
SMTP_SENDER_NAME=Modal
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=dummy
SMTP_PASS=dummy

# Mailer URL paths
MAILER_URLPATHS_INVITE=/auth/v1/verify
MAILER_URLPATHS_CONFIRMATION=/auth/v1/verify
MAILER_URLPATHS_RECOVERY=/auth/v1/verify
MAILER_URLPATHS_EMAIL_CHANGE=/auth/v1/verify

# PostgREST Configuration
PGRST_DB_SCHEMAS=public,storage,graphql_public

# Image Proxy
IMGPROXY_ENABLE_WEBP_DETECTION=true

# Studio Configuration
STUDIO_DEFAULT_ORGANIZATION=Default Organization
STUDIO_DEFAULT_PROJECT=Default Project
DASHBOARD_USERNAME=supabase
DASHBOARD_PASSWORD=supabase

# Analytics
LOGFLARE_PUBLIC_ACCESS_TOKEN=${LOGFLARE_PUBLIC_TOKEN}
LOGFLARE_PRIVATE_ACCESS_TOKEN=${LOGFLARE_PRIVATE_TOKEN}
LOGFLARE_API_KEY=${LOGFLARE_PRIVATE_TOKEN}

# Functions
FUNCTIONS_VERIFY_JWT=true

# Pooler Configuration
POOLER_TENANT_ID=pooler-dev
POOLER_DEFAULT_POOL_SIZE=20
POOLER_MAX_CLIENT_CONN=100
POOLER_DB_POOL_SIZE=10
POOLER_PROXY_PORT_TRANSACTION=6543

# Security Keys
SECRET_KEY_BASE=${SECRET_KEY_BASE}
VAULT_ENC_KEY=${VAULT_ENC_KEY}

# Kong Ports
KONG_HTTP_PORT=8001
KONG_HTTPS_PORT=8443

# Docker
DOCKER_SOCKET_LOCATION=/var/run/docker.sock

# OpenAI (optional)
OPENAI_API_KEY=

# OAuth - Google
ENABLE_GOOGLE_OAUTH=true
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=http://localhost:8001/auth/v1/callback
GOOGLE_SKIP_NONCE_CHECK=true

# OAuth - Apple
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# OAuth - Spotify
SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
SPOTIFY_REDIRECT_URI=modal://spotify/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=http://localhost:8080/api/v1/integrations/gmail/callback

# Soniox Speech-to-Text
SONIOX_API_KEY=${SONIOX_API_KEY}
EOF

echo -e "${GREEN}✓ Created docker/.env${NC}"

echo -e "\n${BLUE}=== Creating apps/api/.env ===${NC}"

cat > "$API_ENV" << EOF
# Database Configuration
DATABASE_URL=postgresql://postgres:postgres@0.0.0.0:5432/postgres

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# JWT Configuration
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Supabase Configuration
SUPABASE_URL=http://localhost:8001
SUPABASE_ANON_KEY=${ANON_KEY}
SUPABASE_SERVICE_ROLE_KEY=${SERVICE_ROLE_KEY}

# Google OAuth
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback

# Apple OAuth
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# Spotify OAuth
SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
SPOTIFY_REDIRECT_URI=modal://spotify/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=http://localhost:8080/api/v1/integrations/gmail/callback

# Soniox Speech-to-Text
SONIOX_API_KEY=${SONIOX_API_KEY}

# Application Settings
DEBUG=True
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API
EOF

echo -e "${GREEN}✓ Created apps/api/.env${NC}"

echo -e "\n${BLUE}=== iOS Configuration ===${NC}"

if [ -f "$IOS_CONFIG" ]; then
    echo -e "${YELLOW}iOS Config.xcconfig found${NC}"
    
    # Get current SUPABASE_URL if it exists
    CURRENT_SUPABASE_URL=""
    if grep -q "^SUPABASE_URL" "$IOS_CONFIG"; then
        CURRENT_SUPABASE_URL=$(grep "^SUPABASE_URL" "$IOS_CONFIG" | sed 's/.*= //' | sed 's|http:/\$()/||' | sed 's|https:/\$()/||')
    fi
    
    # Ask user for SUPABASE_URL
    echo -e "\n${YELLOW}Enter SUPABASE_URL for iOS app:${NC}"
    echo -e "  Examples:"
    echo -e "    - localhost:8001 (for simulator)"
    echo -e "    - 192.168.1.100:8001 (for physical device on same network)"
    echo -e "    - your-tunnel.loca.lt (for remote testing)"
    
    if [ -n "$CURRENT_SUPABASE_URL" ]; then
        read -p "SUPABASE_URL [${CURRENT_SUPABASE_URL}]: " IOS_SUPABASE_URL
        IOS_SUPABASE_URL=${IOS_SUPABASE_URL:-$CURRENT_SUPABASE_URL}
    else
        read -p "SUPABASE_URL [localhost:8001]: " IOS_SUPABASE_URL
        IOS_SUPABASE_URL=${IOS_SUPABASE_URL:-localhost:8001}
    fi
    
    # Determine protocol
    if [[ "$IOS_SUPABASE_URL" == *".loca.lt"* ]] || [[ "$IOS_SUPABASE_URL" == *".ngrok"* ]] || [[ "$IOS_SUPABASE_URL" == "https://"* ]]; then
        PROTOCOL="https"
        IOS_SUPABASE_URL=${IOS_SUPABASE_URL#https://}
    else
        PROTOCOL="http"
        IOS_SUPABASE_URL=${IOS_SUPABASE_URL#http://}
    fi
    
    # Format for xcconfig (with $() escape)
    FORMATTED_URL="${PROTOCOL}:/\$()/${IOS_SUPABASE_URL}"
    
    # Update or add SUPABASE_URL
    if grep -q "^SUPABASE_URL" "$IOS_CONFIG"; then
        sed -i.tmp "s|^SUPABASE_URL.*|SUPABASE_URL = ${FORMATTED_URL}|" "$IOS_CONFIG" && rm -f "$IOS_CONFIG.tmp"
    else
        echo "SUPABASE_URL = ${FORMATTED_URL}" >> "$IOS_CONFIG"
    fi
    
    # Update or add SUPABASE_ANON_KEY
    if grep -q "^SUPABASE_ANON_KEY" "$IOS_CONFIG"; then
        sed -i.tmp "s|^SUPABASE_ANON_KEY.*|SUPABASE_ANON_KEY = ${ANON_KEY}|" "$IOS_CONFIG" && rm -f "$IOS_CONFIG.tmp"
    else
        echo "SUPABASE_ANON_KEY = ${ANON_KEY}" >> "$IOS_CONFIG"
    fi
    
    echo -e "${GREEN}✓ Updated iOS Config.xcconfig${NC}"
    echo -e "  SUPABASE_URL = ${FORMATTED_URL}"
    echo -e "  SUPABASE_ANON_KEY = [SYNCED]"
else
    echo -e "${YELLOW}iOS Config.xcconfig not found - skipping${NC}"
fi

echo -e "\n${GREEN}=== Configuration Complete ===${NC}"
echo -e "JWT Secret:        ${GREEN}[SYNCED]${NC}"
echo -e "ANON Key:          ${GREEN}[SYNCED]${NC}"
echo -e "SERVICE_ROLE Key:  ${GREEN}[SYNCED]${NC}"
echo -e "Google OAuth:      ${GREEN}[SYNCED]${NC}"
echo -e "Spotify OAuth:     ${GREEN}[SYNCED]${NC}"

echo -e "\n${BLUE}=== Docker Management ===${NC}"
cd "$PROJECT_ROOT/docker"

if docker compose ps -q 2>/dev/null | grep -q .; then
    echo -e "${YELLOW}Docker containers running - restart required${NC}"
    read -p "Restart now? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}Pulling latest images...${NC}"
        docker compose pull || echo -e "${YELLOW}⚠️  Some images may have failed to pull${NC}"
        echo -e "${YELLOW}Stopping containers...${NC}"
        docker compose down
        echo -e "${YELLOW}Starting containers...${NC}"
        docker compose up -d
        echo -e "${GREEN}✓ Containers restarted${NC}"
    fi
else
    read -p "Start Docker containers? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo -e "${YELLOW}Pulling images (this may take a few minutes)...${NC}"
        docker compose pull || echo -e "${YELLOW}⚠️  Some images may have failed to pull${NC}"
        echo -e "${YELLOW}Starting containers...${NC}"
        docker compose up -d
        echo -e "${GREEN}✓ Containers started${NC}"
    fi
fi

cd "$PROJECT_ROOT"

echo -e "\n${BLUE}=== Next Steps ===${NC}"
echo -e "1. Update iOS config: ${GREEN}apps/modal/Config.xcconfig${NC}"
echo -e "2. Run startup script: ${GREEN}./scripts/startup.sh${NC}\n"
