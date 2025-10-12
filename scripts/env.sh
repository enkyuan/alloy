#!/bin/bash

# Script to generate Supabase JWT keys and update .env file
# This generates proper JWT tokens for anon and service_role keys

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if required commands exist
command -v openssl >/dev/null 2>&1 || { echo -e "${RED}Error: openssl is required but not installed.${NC}" >&2; exit 1; }
command -v base64 >/dev/null 2>&1 || { echo -e "${RED}Error: base64 is required but not installed.${NC}" >&2; exit 1; }

echo -e "${GREEN}=== Supabase Key Generator ===${NC}\n"

# Get the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
ENV_FILE="$PROJECT_ROOT/supabase/.env"
ENV_EXAMPLE="$PROJECT_ROOT/supabase/.env.example"

# Generate a random JWT secret (32 bytes, base64 encoded)
echo -e "${YELLOW}Generating JWT secret...${NC}"
JWT_SECRET=$(openssl rand -base64 32 | tr -d '\n')
echo -e "${GREEN}✓ JWT secret generated${NC}"

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

# Generate tokens with far future expiry (year 2099)
EXPIRY_DATE=4102444800

echo -e "${YELLOW}Generating ANON key...${NC}"
ANON_KEY=$(create_jwt "anon" "$JWT_SECRET" "$EXPIRY_DATE")
echo -e "${GREEN}✓ ANON key generated${NC}"

echo -e "${YELLOW}Generating SERVICE_ROLE key...${NC}"
SERVICE_ROLE_KEY=$(create_jwt "service_role" "$JWT_SECRET" "$EXPIRY_DATE")
echo -e "${GREEN}✓ SERVICE_ROLE key generated${NC}"

# Generate a strong Postgres password
echo -e "${YELLOW}Generating Postgres password...${NC}"
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '\n')
echo -e "${GREEN}✓ Postgres password generated${NC}"

echo -e "\n${GREEN}=== Generated Keys ===${NC}\n"

# Check if .env file exists
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Found existing .env file${NC}"
    read -p "Do you want to update it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Operation cancelled. Printing keys to stdout:${NC}\n"
        echo "JWT_SECRET=$JWT_SECRET"
        echo "ANON_KEY=$ANON_KEY"
        echo "SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY"
        echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
        exit 0
    fi

    # Backup existing .env
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${GREEN}✓ Backed up existing .env file${NC}"

    # Update .env file
    if grep -q "^JWT_SECRET=" "$ENV_FILE"; then
        sed -i.tmp "s|^JWT_SECRET=.*|JWT_SECRET=$JWT_SECRET|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    else
        echo "JWT_SECRET=$JWT_SECRET" >> "$ENV_FILE"
    fi

    if grep -q "^ANON_KEY=" "$ENV_FILE"; then
        sed -i.tmp "s|^ANON_KEY=.*|ANON_KEY=$ANON_KEY|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    else
        echo "ANON_KEY=$ANON_KEY" >> "$ENV_FILE"
    fi

    if grep -q "^SERVICE_ROLE_KEY=" "$ENV_FILE"; then
        sed -i.tmp "s|^SERVICE_ROLE_KEY=.*|SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    else
        echo "SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY" >> "$ENV_FILE"
    fi

    if grep -q "^POSTGRES_PASSWORD=" "$ENV_FILE"; then
        sed -i.tmp "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASSWORD|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    else
        echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> "$ENV_FILE"
    fi

    echo -e "${GREEN}✓ Updated .env file${NC}"

elif [ -f "$ENV_EXAMPLE" ]; then
    echo -e "${YELLOW}.env file not found. Creating from .env.example...${NC}"
    cp "$ENV_EXAMPLE" "$ENV_FILE"

    # Update the new .env file
    sed -i.tmp "s|^JWT_SECRET=.*|JWT_SECRET=$JWT_SECRET|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    sed -i.tmp "s|^ANON_KEY=.*|ANON_KEY=$ANON_KEY|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    sed -i.tmp "s|^SERVICE_ROLE_KEY=.*|SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY|" "$ENV_FILE" && rm "$ENV_FILE.tmp"
    sed -i.tmp "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASSWORD|" "$ENV_FILE" && rm "$ENV_FILE.tmp"

    echo -e "${GREEN}✓ Created and updated .env file${NC}"
else
    echo -e "${RED}Error: Neither .env nor .env.example found${NC}"
    echo -e "${YELLOW}Printing keys to stdout:${NC}\n"
    echo "JWT_SECRET=$JWT_SECRET"
    echo "ANON_KEY=$ANON_KEY"
    echo "SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY"
    echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
    exit 1
fi

# Update Kong configuration
KONG_CONFIG="$PROJECT_ROOT/supabase/kong.yml"
KONG_TEMPLATE="$PROJECT_ROOT/supabase/kong.yml.template"

if [ -f "$KONG_TEMPLATE" ]; then
    echo -e "\n${YELLOW}Generating Kong configuration from template...${NC}"

    # Backup existing Kong config if it exists
    if [ -f "$KONG_CONFIG" ]; then
        cp "$KONG_CONFIG" "$KONG_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
    fi

    # Generate kong.yml from template
    sed "s|__ANON_KEY__|$ANON_KEY|g" "$KONG_TEMPLATE" | \
    sed "s|__SERVICE_ROLE_KEY__|$SERVICE_ROLE_KEY|g" > "$KONG_CONFIG"

    echo -e "${GREEN}✓ Generated Kong configuration${NC}"
elif [ -f "$KONG_CONFIG" ]; then
    echo -e "\n${YELLOW}Updating existing Kong configuration...${NC}"

    # Backup Kong config
    cp "$KONG_CONFIG" "$KONG_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"

    # Try to update keys in existing Kong config (fallback method)
    # Replace anon key
    awk -v new_key="$ANON_KEY" '
        /- username: anon/ { found_anon=1 }
        found_anon && /key:/ {
            sub(/key: .*/, "key: " new_key)
            found_anon=0
        }
        { print }
    ' "$KONG_CONFIG" > "$KONG_CONFIG.tmp1"

    # Replace service_role key
    awk -v new_key="$SERVICE_ROLE_KEY" '
        /- username: service_role/ { found_service=1 }
        found_service && /key:/ {
            sub(/key: .*/, "key: " new_key)
            found_service=0
        }
        { print }
    ' "$KONG_CONFIG.tmp1" > "$KONG_CONFIG"

    # Clean up temp files
    rm -f "$KONG_CONFIG.tmp1"

    echo -e "${GREEN}✓ Updated Kong configuration${NC}"
else
    echo -e "${YELLOW}Warning: Kong configuration not found${NC}"
    echo -e "${YELLOW}You may need to manually create supabase/kong.yml${NC}"
fi

echo -e "\n${GREEN}=== Summary ===${NC}"
echo -e "JWT Secret:        ${GREEN}[GENERATED]${NC}"
echo -e "ANON Key:          ${GREEN}[GENERATED]${NC}"
echo -e "SERVICE_ROLE Key:  ${GREEN}[GENERATED]${NC}"
echo -e "Postgres Password: ${GREEN}[GENERATED]${NC}"

echo -e "\n${YELLOW}Note: Keys have been written to .env file${NC}"
echo -e "${YELLOW}Make sure to restart your Docker containers:${NC}"
echo -e "  ${GREEN}docker-compose down && docker-compose up -d${NC}\n"
