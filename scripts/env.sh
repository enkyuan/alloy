#!/bin/bash

# Script to generate Supabase JWT keys and sync .env files across the project
# This ensures consistency between root, supabase, and apps/api .env files

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Define .env file locations
DOCKER_ENV="$PROJECT_ROOT/docker/.env"
SUPABASE_ENV="$PROJECT_ROOT/docker/supabase/.env"
API_ENV="$PROJECT_ROOT/apps/api/.env"

echo -e "${BLUE}=== Modal Environment Configuration ===${NC}\n"

# Check if required commands exist
command -v openssl >/dev/null 2>&1 || { echo -e "${RED}Error: openssl is required but not installed.${NC}" >&2; exit 1; }
command -v base64 >/dev/null 2>&1 || { echo -e "${RED}Error: base64 is required but not installed.${NC}" >&2; exit 1; }

# Function to base64url encode
base64url_encode() {
    openssl base64 -e -A | tr '+/' '-_' | tr -d '='
}

# Function to create JWT
create_jwt() {
    local role=$1
    local secret=$2
    local expiry=$3

    # JWT Header
    header='{"alg":"HS256","typ":"JWT"}'

    # JWT Payload
    payload=$(cat <<EOF
{"iss":"supabase","role":"$role","iat":$(date +%s),"exp":$expiry}
EOF
)

    # Encode header and payload
    header_base64=$(echo -n "$header" | base64url_encode)
    payload_base64=$(echo -n "$payload" | base64url_encode)

    # Create signature
    signature=$(echo -n "${header_base64}.${payload_base64}" | \
        openssl dgst -sha256 -hmac "$secret" -binary | \
        base64url_encode)

    # Return complete JWT
    echo "${header_base64}.${payload_base64}.${signature}"
}

# Check for existing JWT_SECRET
EXISTING_JWT_SECRET=""
if [ -f "$DOCKER_ENV" ] && grep -q "^JWT_SECRET=" "$DOCKER_ENV"; then
    EXISTING_JWT_SECRET=$(grep "^JWT_SECRET=" "$DOCKER_ENV" | cut -d= -f2)
    echo -e "${YELLOW}Found existing JWT_SECRET${NC}"
    read -p "Use existing JWT_SECRET? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        EXISTING_JWT_SECRET=""
    fi
fi

# Generate or use existing JWT secret
if [ -n "$EXISTING_JWT_SECRET" ]; then
    JWT_SECRET="$EXISTING_JWT_SECRET"
    echo -e "${GREEN}✓ Using existing JWT secret${NC}"
else
    echo -e "${YELLOW}Generating new JWT secret...${NC}"
    JWT_SECRET=$(openssl rand -base64 32 | tr -d '\n')
    echo -e "${GREEN}✓ New JWT secret generated${NC}"
fi

# Generate tokens with far future expiry (year 2099)
EXPIRY_DATE=4102444800

echo -e "${YELLOW}Generating ANON key...${NC}"
ANON_KEY=$(create_jwt "anon" "$JWT_SECRET" "$EXPIRY_DATE")
echo -e "${GREEN}✓ ANON key generated${NC}"

echo -e "${YELLOW}Generating SERVICE_ROLE key...${NC}"
SERVICE_ROLE_KEY=$(create_jwt "service_role" "$JWT_SECRET" "$EXPIRY_DATE")
echo -e "${GREEN}✓ SERVICE_ROLE key generated${NC}"

# Get OAuth credentials (preserve existing if available)
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""
GOOGLE_REDIRECT_URI="http://localhost:8001/auth/v1/callback"

if [ -f "$DOCKER_ENV" ]; then
    GOOGLE_CLIENT_ID=$(grep "^GOOGLE_CLIENT_ID=" "$DOCKER_ENV" | cut -d= -f2 || echo "")
    GOOGLE_CLIENT_SECRET=$(grep "^GOOGLE_CLIENT_SECRET=" "$DOCKER_ENV" | cut -d= -f2 || echo "")
    GOOGLE_REDIRECT_URI=$(grep "^GOOGLE_REDIRECT_URI=" "$DOCKER_ENV" | cut -d= -f2 || echo "http://localhost:8001/auth/v1/callback")
fi

echo -e "\n${BLUE}=== OAuth Configuration ===${NC}"
read -p "Update Google OAuth credentials? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter Google Client ID: " GOOGLE_CLIENT_ID
    read -p "Enter Google Client Secret: " GOOGLE_CLIENT_SECRET
    read -p "Enter Google Redirect URI [${GOOGLE_REDIRECT_URI}]: " GOOGLE_REDIRECT_URI_INPUT
    if [ -n "$GOOGLE_REDIRECT_URI_INPUT" ]; then
        GOOGLE_REDIRECT_URI="$GOOGLE_REDIRECT_URI_INPUT"
    fi
fi

# Spotify OAuth credentials
SPOTIFY_CLIENT_ID=""
SPOTIFY_CLIENT_SECRET=""
SPOTIFY_REDIRECT_URI="http://localhost:8000/api/v1/integrations/spotify/callback"

if [ -f "$API_ENV" ]; then
    SPOTIFY_CLIENT_ID=$(grep "^SPOTIFY_CLIENT_ID=" "$API_ENV" | cut -d= -f2 || echo "")
    SPOTIFY_CLIENT_SECRET=$(grep "^SPOTIFY_CLIENT_SECRET=" "$API_ENV" | cut -d= -f2 || echo "")
fi

read -p "Update Spotify OAuth credentials? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter Spotify Client ID: " SPOTIFY_CLIENT_ID
    read -p "Enter Spotify Client Secret: " SPOTIFY_CLIENT_SECRET
fi

# Function to update or append env variable
update_env_var() {
    local file=$1
    local key=$2
    local value=$3
    
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Use | as delimiter since paths and URLs may contain /
        sed -i.tmp "s|^${key}=.*|${key}=${value}|" "$file" && rm -f "$file.tmp"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

echo -e "\n${BLUE}=== Updating Environment Files ===${NC}"

# Create docker/.env if it doesn't exist
if [ ! -f "$DOCKER_ENV" ]; then
    echo -e "${YELLOW}Creating docker/.env file...${NC}"
    mkdir -p "$PROJECT_ROOT/docker"
    cat > "$DOCKER_ENV" << EOF
# Database Configuration (uses container name for internal networking)
DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Supabase Configuration (uses container names for internal networking)
SUPABASE_URL=http://kong:8000
ANON_KEY=${ANON_KEY}
SUPABASE_ANON_KEY=${ANON_KEY}
SERVICE_ROLE_KEY=${SERVICE_ROLE_KEY}
SUPABASE_SERVICE_KEY=${SERVICE_ROLE_KEY}

# JWT Configuration
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# API Configuration
DEBUG=false
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API

# OAuth Configuration
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI}

APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# Spotify OAuth
SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
SPOTIFY_REDIRECT_URI=${SPOTIFY_REDIRECT_URI}
EOF
    echo -e "${GREEN}✓ Created docker/.env${NC}"
else
    # Update existing docker/.env
    echo -e "${YELLOW}Updating docker/.env...${NC}"
    update_env_var "$DOCKER_ENV" "JWT_SECRET" "$JWT_SECRET"
    update_env_var "$DOCKER_ENV" "SUPABASE_ANON_KEY" "$ANON_KEY"
    update_env_var "$DOCKER_ENV" "SUPABASE_SERVICE_ROLE_KEY" "$SERVICE_ROLE_KEY"
    update_env_var "$DOCKER_ENV" "GOOGLE_CLIENT_ID" "$GOOGLE_CLIENT_ID"
    update_env_var "$DOCKER_ENV" "GOOGLE_CLIENT_SECRET" "$GOOGLE_CLIENT_SECRET"
    update_env_var "$DOCKER_ENV" "GOOGLE_REDIRECT_URI" "$GOOGLE_REDIRECT_URI"
    update_env_var "$DOCKER_ENV" "SPOTIFY_CLIENT_ID" "$SPOTIFY_CLIENT_ID"
    update_env_var "$DOCKER_ENV" "SPOTIFY_CLIENT_SECRET" "$SPOTIFY_CLIENT_SECRET"
    echo -e "${GREEN}✓ Updated docker/.env${NC}"
fi

# Update docker/supabase/.env
if [ ! -f "$SUPABASE_ENV" ]; then
    echo -e "${YELLOW}Creating docker/supabase/.env...${NC}"
    mkdir -p "$PROJECT_ROOT/docker/supabase"
    cat > "$SUPABASE_ENV" << EOF
# Database Configuration
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=postgres

# OAuth Configurations
ENABLE_GOOGLE_OAUTH=true
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI}
GOOGLE_SKIP_NONCE_CHECK=true

# JWT Configuration
JWT_SECRET=${JWT_SECRET}
JWT_EXPIRY=3600

# Supabase Configuration
API_EXTERNAL_URL=http://localhost:8001
SITE_URL=http://localhost:3000
ADDITIONAL_REDIRECT_URLS=
DISABLE_SIGNUP=false
SUPABASE_PUBLIC_URL=http://localhost:8001

# Email Configuration
ENABLE_EMAIL_SIGNUP=true
ENABLE_EMAIL_AUTOCONFIRM=true

# Phone Configuration
ENABLE_PHONE_SIGNUP=false
ENABLE_PHONE_AUTOCONFIRM=false

# SMTP Configuration
SMTP_ADMIN_EMAIL=admin@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_SENDER_NAME=Supabase

# Mailer URL paths
MAILER_URLPATHS_INVITE=/auth/v1/verify
MAILER_URLPATHS_CONFIRMATION=/auth/v1/verify
MAILER_URLPATHS_RECOVERY=/auth/v1/verify
MAILER_URLPATHS_EMAIL_CHANGE=/auth/v1/verify

# Supabase Keys
ANON_KEY=${ANON_KEY}
SERVICE_ROLE_KEY=${SERVICE_ROLE_KEY}
SUPABASE_URL=http://localhost:8001

# PostgREST Configuration
PGRST_DB_SCHEMAS=public,storage,graphql_public

# Image Proxy
IMGPROXY_ENABLE_WEBP_DETECTION=true

# Kong Configuration
KONG_HTTP_PORT=8001
KONG_HTTPS_PORT=8443

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true

# Studio Configuration
STUDIO_DEFAULT_ORGANIZATION=Default Organization
STUDIO_DEFAULT_PROJECT=Default Project
DASHBOARD_USERNAME=supabase
DASHBOARD_PASSWORD=supabase

# Analytics
LOGFLARE_API_KEY=dummy-key

# Functions
FUNCTIONS_VERIFY_JWT=true

# Docker
DOCKER_SOCKET_LOCATION=/var/run/docker.sock
EOF
    echo -e "${GREEN}✓ Created docker/supabase/.env${NC}"
else
    echo -e "${YELLOW}Updating docker/supabase/.env...${NC}"
    update_env_var "$SUPABASE_ENV" "JWT_SECRET" "$JWT_SECRET"
    update_env_var "$SUPABASE_ENV" "ANON_KEY" "$ANON_KEY"
    update_env_var "$SUPABASE_ENV" "SERVICE_ROLE_KEY" "$SERVICE_ROLE_KEY"
    update_env_var "$SUPABASE_ENV" "GOOGLE_CLIENT_ID" "$GOOGLE_CLIENT_ID"
    update_env_var "$SUPABASE_ENV" "GOOGLE_CLIENT_SECRET" "$GOOGLE_CLIENT_SECRET"
    update_env_var "$SUPABASE_ENV" "GOOGLE_REDIRECT_URI" "$GOOGLE_REDIRECT_URI"
    echo -e "${GREEN}✓ Updated docker/supabase/.env${NC}"
fi

# Update apps/api/.env
if [ ! -f "$API_ENV" ]; then
    echo -e "${YELLOW}Creating apps/api/.env...${NC}"
    mkdir -p "$PROJECT_ROOT/apps/api"
    cat > "$API_ENV" << EOF
DATABASE_URL=postgresql://postgres:postgres@0.0.0.0:5432/postgres

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# JWT Configuration
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Supabase Keys
SUPABASE_URL=http://localhost:8001
SUPABASE_ANON_KEY=${ANON_KEY}
SUPABASE_SERVICE_ROLE_KEY=${SERVICE_ROLE_KEY}

# Google OAuth Configuration
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback

# Apple OAuth Configuration
APPLE_CLIENT_ID=
APPLE_TEAM_ID=
APPLE_KEY_ID=
APPLE_PRIVATE_KEY=

# Spotify OAuth Configuration
SPOTIFY_CLIENT_ID=${SPOTIFY_CLIENT_ID}
SPOTIFY_CLIENT_SECRET=${SPOTIFY_CLIENT_SECRET}
SPOTIFY_REDIRECT_URI=${SPOTIFY_REDIRECT_URI}

# Application Settings
DEBUG=True
API_V1_PREFIX=/api/v1
PROJECT_NAME=Modal API
EOF
    echo -e "${GREEN}✓ Created apps/api/.env${NC}"
else
    echo -e "${YELLOW}Updating apps/api/.env...${NC}"
    update_env_var "$API_ENV" "JWT_SECRET" "$JWT_SECRET"
    update_env_var "$API_ENV" "SUPABASE_ANON_KEY" "$ANON_KEY"
    update_env_var "$API_ENV" "SUPABASE_SERVICE_ROLE_KEY" "$SERVICE_ROLE_KEY"
    update_env_var "$API_ENV" "GOOGLE_CLIENT_ID" "$GOOGLE_CLIENT_ID"
    update_env_var "$API_ENV" "GOOGLE_CLIENT_SECRET" "$GOOGLE_CLIENT_SECRET"
    update_env_var "$API_ENV" "SPOTIFY_CLIENT_ID" "$SPOTIFY_CLIENT_ID"
    update_env_var "$API_ENV" "SPOTIFY_CLIENT_SECRET" "$SPOTIFY_CLIENT_SECRET"
    echo -e "${GREEN}✓ Updated apps/api/.env${NC}"
fi

# Update Kong configuration if template exists
KONG_CONFIG="$PROJECT_ROOT/docker/supabase/kong.yml"
KONG_TEMPLATE="$PROJECT_ROOT/docker/supabase/kong.yml.template"

if [ -f "$KONG_TEMPLATE" ]; then
    echo -e "\n${YELLOW}Generating Kong configuration from template...${NC}"

    if [ -f "$KONG_CONFIG" ]; then
        cp "$KONG_CONFIG" "$KONG_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
    fi

    sed "s|__ANON_KEY__|$ANON_KEY|g" "$KONG_TEMPLATE" | \
    sed "s|__SERVICE_ROLE_KEY__|$SERVICE_ROLE_KEY|g" > "$KONG_CONFIG"

    echo -e "${GREEN}✓ Generated Kong configuration${NC}"
fi

echo -e "\n${GREEN}=== Configuration Summary ===${NC}"
echo -e "JWT Secret:        ${GREEN}[SYNCED]${NC}"
echo -e "ANON Key:          ${GREEN}[SYNCED]${NC}"
echo -e "SERVICE_ROLE Key:  ${GREEN}[SYNCED]${NC}"
echo -e "Google OAuth:      ${GREEN}[SYNCED]${NC}"
echo -e "Spotify OAuth:     ${GREEN}[SYNCED]${NC}"

echo -e "\n${BLUE}=== Next Steps ===${NC}"
echo -e "1. ${YELLOW}Restart Docker containers:${NC}"
echo -e "   ${GREEN}cd docker && docker compose down && docker compose up -d${NC}"
echo -e "\n2. ${YELLOW}Or use the startup script:${NC}"
echo -e "   ${GREEN}./scripts/startup.sh${NC}\n"
