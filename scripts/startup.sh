#!/bin/bash

# Modal Startup Script
# Starts Docker containers and optionally builds/runs the iOS app

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Check for Docker
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Error: Docker is required but not installed.${NC}" >&2; exit 1; }
command -v docker-compose >/dev/null 2>&1 || { echo -e "${RED}Error: docker-compose is required but not installed.${NC}" >&2; exit 1; }

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Modal Application Startup        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}\n"

# Function to check if a container is running
is_container_running() {
    local container_name=$1
    docker ps --format '{{.Names}}' | grep -q "^${container_name}$"
}

# Function to wait for service to be healthy
wait_for_service() {
    local service_name=$1
    local max_attempts=30
    local attempt=1

    echo -e "${YELLOW}Waiting for ${service_name} to be healthy...${NC}"

    while [ $attempt -le $max_attempts ]; do
        if docker inspect --format='{{.State.Health.Status}}' "$service_name" 2>/dev/null | grep -q "healthy"; then
            echo -e "${GREEN}✓ ${service_name} is healthy${NC}"
            return 0
        fi
        echo -n "."
        sleep 2
        attempt=$((attempt + 1))
    done

    echo -e "\n${RED}✗ ${service_name} failed to become healthy${NC}"
    
    # Show helpful troubleshooting info for database
    if [ "$service_name" = "supabase-db" ]; then
        echo -e "${YELLOW}Troubleshooting tips:${NC}"
        
        # Check for specific error in logs
        DB_LOGS=$(docker compose logs db --tail=20 2>/dev/null)
        if echo "$DB_LOGS" | grep -q "invalid value for parameter \"port\""; then
            echo -e "${RED}  ⚠️  Detected: Database port configuration error${NC}"
            echo -e "${YELLOW}  This is usually caused by corrupted Docker volumes.${NC}"
            echo -e "${GREEN}  Solution: Stop this script (Ctrl+C) and run:${NC}"
            echo -e "${GREEN}    cd docker && docker compose down -v${NC}"
            echo -e "${GREEN}    ./scripts/setup.sh  # Choose option 2 to clean volumes${NC}"
        elif echo "$DB_LOGS" | grep -q "Database directory appears to contain a database"; then
            echo -e "${RED}  ⚠️  Detected: Stale database volume${NC}"
            echo -e "${YELLOW}  Old database data is preventing initialization.${NC}"
            echo -e "${GREEN}  Solution: Clean volumes and restart:${NC}"
            echo -e "${GREEN}    cd docker && docker compose down -v && docker compose up -d${NC}"
        else
            echo -e "  1. Check database logs: ${GREEN}docker compose logs db${NC}"
            echo -e "  2. Verify JWT configuration is synced across .env files"
            echo -e "  3. Run ${GREEN}./scripts/setup.sh${NC} to regenerate configuration"
            echo -e "  4. Try a full cleanup: ${GREEN}docker compose down -v${NC} then restart"
        fi
    fi
    
    return 1
}

# Function to start all services
start_all_services() {
    echo -e "\n${CYAN}=== Starting All Services ===${NC}"

    cd "$PROJECT_ROOT/docker"

    # Check if .env exists
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}Warning: docker/.env not found.${NC}"
        echo -e "${YELLOW}Run ./scripts/setup.sh to configure your environment.${NC}"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # Check if volumes exist that might have stale data
    if docker volume ls | grep -q "modal"; then
        echo -e "${YELLOW}⚠️  Existing Docker volumes detected.${NC}"
        echo -e "${YELLOW}   If you're experiencing database errors, you may need to clean them.${NC}\n"
        echo -e "Choose startup mode:"
        echo -e "  1) Normal start (reuse existing volumes)"
        echo -e "  2) Clean start (⚠️  removes volumes - fixes database errors)"
        echo -e "  3) Cancel"
        read -p "Selection (1/2/3): " -n 1 -r
        echo
        
        case $REPLY in
            1)
                # Normal restart - keep volumes
                echo -e "\n${YELLOW}Stopping and removing existing containers...${NC}"
                docker compose down 2>/dev/null || true
                
                echo -e "${YELLOW}Building API container...${NC}"
                docker compose build api
                
                echo -e "${YELLOW}Starting all services...${NC}"
                docker compose up -d --force-recreate
                ;;
            2)
                # Clean restart - remove volumes
                echo -e "\n${RED}⚠️  This will delete all database data, uploads, and cached data.${NC}"
                read -p "Are you absolutely sure? (type 'yes' to confirm): " confirm
                if [ "$confirm" = "yes" ]; then
                    echo -e "\n${YELLOW}Stopping containers and removing volumes...${NC}"
                    docker compose down -v
                    
                    echo -e "${YELLOW}Building API container...${NC}"
                    docker compose build api
                    
                    echo -e "${YELLOW}Starting fresh services...${NC}"
                    docker compose up -d
                    
                    echo -e "\n${GREEN}✓ Started with clean volumes${NC}"
                else
                    echo -e "${YELLOW}Cancelled. Using normal start instead...${NC}"
                    docker compose down 2>/dev/null || true
                    docker compose build api
                    docker compose up -d --force-recreate
                fi
                ;;
            3)
                echo -e "${YELLOW}Cancelled startup.${NC}"
                cd "$PROJECT_ROOT"
                return 1
                ;;
            *)
                echo -e "${YELLOW}Invalid selection. Using normal start...${NC}"
                docker compose down 2>/dev/null || true
                docker compose build api
                docker compose up -d --force-recreate
                ;;
        esac
    else
        # No existing volumes - normal startup
        echo -e "${YELLOW}Stopping and removing existing containers...${NC}"
        docker compose down 2>/dev/null || true
        
        echo -e "${YELLOW}Building API container...${NC}"
        docker compose build api
        
        echo -e "${YELLOW}Starting all services with fresh containers...${NC}"
        docker compose up -d --force-recreate
    fi

    echo -e "\n${GREEN}✓ All services starting...${NC}"
    echo -e "${YELLOW}Note: Services may take 30-60 seconds to become healthy.${NC}"
    
    # Wait for critical services to be healthy
    echo -e "\n${YELLOW}Waiting for critical services to be healthy...${NC}"
    wait_for_service "supabase-db" || echo -e "${YELLOW}⚠️  Database may still be starting up${NC}"
    wait_for_service "modal-redis" || echo -e "${YELLOW}⚠️  Redis may still be starting up${NC}"
    
    echo -e "\n${GREEN}✓ Core services are healthy${NC}"

    cd "$PROJECT_ROOT"
}

# Function to start specific services
start_specific_service() {
    local service=$1
    echo -e "\n${CYAN}=== Starting ${service} ===${NC}"

    cd "$PROJECT_ROOT/docker"

    docker compose up -d $service

    echo -e "${GREEN}✓ ${service} started${NC}"

    cd "$PROJECT_ROOT"
}

# Function to list iOS simulators
list_simulators() {
    echo -e "\n${CYAN}=== Available iOS Simulators ===${NC}\n"

    # Get booted simulators
    BOOTED_SIMS=$(xcrun simctl list devices | grep "Booted" | sed 's/(.*//' | sed 's/^[[:space:]]*//')

    if [ -n "$BOOTED_SIMS" ]; then
        echo -e "${GREEN}★ Currently Booted:${NC}"
        echo "$BOOTED_SIMS" | while IFS= read -r sim; do
            echo -e "  ${GREEN}▸${NC} $sim"
        done
        echo ""
    fi

    # Get all available simulators (iOS only, runtime available)
    echo -e "${YELLOW}All Available Devices:${NC}"
    xcrun simctl list devices available | grep "iPhone\|iPad" | grep -v "unavailable" | sed 's/(.*//' | sed 's/^[[:space:]]*//' | nl
}

# Function to select a simulator
select_simulator() {
    list_simulators

    # Check if there's a booted device
    BOOTED_LINE=$(xcrun simctl list devices | grep "Booted" | head -n 1)

    if [ -n "$BOOTED_LINE" ]; then
        echo -e "\n${YELLOW}Enter simulator number (or press Enter for currently booted device):${NC} "
    else
        echo -e "\n${YELLOW}Enter simulator number (or press Enter for iPhone 15 Pro):${NC} "
    fi
    read -r sim_choice

    if [ -z "$sim_choice" ]; then
        # Default to currently booted device if available
        if [ -n "$BOOTED_LINE" ]; then
            SELECTED_LINE="$BOOTED_LINE"
        else
            # Otherwise default to iPhone 15 Pro
            SELECTED_LINE=$(xcrun simctl list devices | grep "iPhone 15 Pro" | grep -v "Max" | grep "Booted\|Shutdown" | head -n 1)
            if [ -z "$SELECTED_LINE" ]; then
                # Fallback to any iPhone
                SELECTED_LINE=$(xcrun simctl list devices | grep "iPhone" | grep -v "unavailable" | grep "Booted\|Shutdown" | head -n 1)
            fi
        fi
        SELECTED_SIM=$(echo "$SELECTED_LINE" | sed 's/(.*//' | sed 's/^[[:space:]]*//')
        SIMULATOR_UDID=$(echo "$SELECTED_LINE" | grep -o -E '\([A-Z0-9-]+\)' | head -n 1 | tr -d '()')
    else
        SELECTED_LINE=$(xcrun simctl list devices available | grep "iPhone\|iPad" | grep -v "unavailable" | sed -n "${sim_choice}p")
        SELECTED_SIM=$(echo "$SELECTED_LINE" | sed 's/(.*//' | sed 's/^[[:space:]]*//')
        SIMULATOR_UDID=$(echo "$SELECTED_LINE" | grep -o -E '\([A-Z0-9-]+\)' | head -n 1 | tr -d '()')
    fi

    if [ -z "$SELECTED_SIM" ] || [ -z "$SIMULATOR_UDID" ]; then
        echo -e "${RED}✗ Invalid selection or could not find simulator${NC}"
        return 1
    fi

    echo -e "${GREEN}✓ Selected: ${SELECTED_SIM}${NC}"
    echo -e "${GREEN}  UDID: ${SIMULATOR_UDID}${NC}"
}

# Function to build and run iOS app
build_ios_app() {
    echo -e "\n${CYAN}=== Building iOS App ===${NC}"

    # Select simulator
    select_simulator || return 1

    # Boot simulator if not already booted
    echo -e "\n${YELLOW}Booting simulator...${NC}"
    xcrun simctl boot "$SIMULATOR_UDID" 2>/dev/null || echo -e "${YELLOW}Simulator already booted${NC}"

    # Open Simulator.app
    open -a Simulator

    # Build the app
    echo -e "\n${YELLOW}Building app...${NC}"
    cd "$PROJECT_ROOT/apps/modal"

    # Determine if xcpretty is available
    if command -v xcpretty &> /dev/null; then
        BUILD_FORMATTER="xcpretty"
    else
        BUILD_FORMATTER="cat"
    fi

    # Enable pipefail to catch build errors even with pipes
    set -o pipefail

    xcodebuild \
        -project modal.xcodeproj \
        -scheme modal \
        -sdk iphonesimulator \
        -destination "id=$SIMULATOR_UDID" \
        -configuration Debug \
        -derivedDataPath ./build \
        -allowProvisioningUpdates \
        clean build \
        2>&1 | $BUILD_FORMATTER

    BUILD_EXIT_CODE=$?
    set +o pipefail

    if [ $BUILD_EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✓ Build successful${NC}"

        # Install and run the app
        echo -e "\n${YELLOW}Installing app on simulator...${NC}"

        # Find the built app (check local build dir first, then DerivedData)
        APP_PATH=$(find "$PROJECT_ROOT/apps/modal/build" -name "modal.app" -type d -path "*Build/Products/Debug-iphonesimulator*" 2>/dev/null | head -n 1)

        if [ -z "$APP_PATH" ]; then
            APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData -name "modal.app" -type d -path "*Build/Products/Debug-iphonesimulator*" 2>/dev/null | head -n 1)
        fi

        if [ -n "$APP_PATH" ]; then
            # Verify bundle exists
            if [ ! -d "$APP_PATH" ]; then
                echo -e "${RED}✗ App bundle not found at: $APP_PATH${NC}"
                return 1
            fi

            # Install app on the selected simulator
            echo -e "${YELLOW}Installing on: ${SELECTED_SIM} (${SIMULATOR_UDID})${NC}"
            if xcrun simctl install "$SIMULATOR_UDID" "$APP_PATH" 2>&1; then
                echo -e "${GREEN}✓ App installed successfully${NC}"
            else
                echo -e "${RED}✗ Installation failed${NC}"
                return 1
            fi

            # Launch app on the selected simulator
            echo -e "\n${YELLOW}Launching app on ${SELECTED_SIM}...${NC}"
            if xcrun simctl launch "$SIMULATOR_UDID" com.app.modal 2>&1; then
                echo -e "${GREEN}✓ App launched successfully on ${SELECTED_SIM}${NC}"
                echo -e "\n${CYAN}════════════════════════════════════════${NC}"
                echo -e "${GREEN}✓ Build and Launch Complete!${NC}"
                echo -e "${CYAN}════════════════════════════════════════${NC}\n"

                cd "$PROJECT_ROOT"

                # Auto-exit after successful launch
                echo -e "${GREEN}Exiting...${NC}\n"
                exit 0
            else
                echo -e "${RED}✗ Launch failed${NC}"
                return 1
            fi
        else
            echo -e "${RED}✗ Could not find built app${NC}"
            return 1
        fi
    else
        echo -e "${RED}✗ Build failed${NC}"
        return 1
    fi

    cd "$PROJECT_ROOT"
}

# Main menu
show_menu() {
    echo -e "\n${BLUE}=== Startup Options ===${NC}"
    echo -e "1) Start Docker containers only"
    echo -e "2) Start Docker + Build and run iOS app"
    echo -e "3) Build and run iOS app only"
    echo -e "4) Check service status"
    echo -e "5) Stop/cleanup services"
    echo -e "6) View logs"
    echo -e "0) Exit"
    echo -e "\n${YELLOW}Select an option:${NC} "
}

# Function to check status
check_status() {
    echo -e "\n${CYAN}=== Service Status ===${NC}\n"

    cd "$PROJECT_ROOT/docker"
    docker compose ps
    cd "$PROJECT_ROOT"
}

# Function to stop services with options
stop_services() {
    echo -e "\n${CYAN}=== Stop/Cleanup Services ===${NC}"
    echo -e "1) Stop containers (keep data)"
    echo -e "2) Remove containers (keep volumes/data)"
    echo -e "3) Remove containers and volumes (⚠️  deletes all data)"
    echo -e "4) Full cleanup (⚠️  deletes everything including images)"
    echo -e "0) Cancel"
    echo -e "\n${YELLOW}Select shutdown option:${NC} "
    read -r shutdown_choice

    cd "$PROJECT_ROOT/docker"

    case $shutdown_choice in
        1)
            echo -e "${YELLOW}Stopping Docker containers...${NC}"
            docker compose stop
            echo -e "${GREEN}✓ Containers stopped${NC}"
            echo -e "${CYAN}Use option 1 to start them again${NC}"
            ;;
        2)
            echo -e "${YELLOW}Removing Docker containers...${NC}"
            docker compose down
            echo -e "${GREEN}✓ Containers removed${NC}"
            echo -e "${CYAN}Data volumes preserved. Use option 1 to recreate containers${NC}"
            ;;
        3)
            echo -e "${RED}⚠️  WARNING: This will delete all database data, Redis data, etc.${NC}"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                echo -e "${YELLOW}Removing Docker containers and volumes...${NC}"
                docker compose down -v
                echo -e "${GREEN}✓ Containers and volumes removed${NC}"
                echo -e "${CYAN}All data deleted. Use option 1 to start fresh${NC}"
            else
                echo -e "${YELLOW}Cancelled${NC}"
            fi
            ;;
        4)
            echo -e "${RED}⚠️  WARNING: This will delete EVERYTHING (containers, volumes, and images)${NC}"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                echo -e "${YELLOW}Removing Docker containers, volumes, and images...${NC}"
                docker compose down -v --rmi all
                echo -e "${GREEN}✓ Full cleanup complete${NC}"
                echo -e "${CYAN}Use option 1 to rebuild and start${NC}"
            else
                echo -e "${YELLOW}Cancelled${NC}"
            fi
            ;;
        0)
            echo -e "${YELLOW}Cancelled${NC}"
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}"
            ;;
    esac

    cd "$PROJECT_ROOT"
}

# Function to view logs
view_logs() {
    echo -e "\n${CYAN}=== Service Logs ===${NC}"
    echo -e "1) Modal API logs"
    echo -e "2) Supabase Auth logs"
    echo -e "3) Database logs"
    echo -e "4) Redis logs"
    echo -e "5) All logs"
    echo -e "\n${YELLOW}Select:${NC} "
    read -r log_choice

    cd "$PROJECT_ROOT/docker"

    case $log_choice in
        1)
            docker compose logs -f modal_api
            ;;
        2)
            docker compose logs -f auth
            ;;
        3)
            docker compose logs -f db
            ;;
        4)
            docker compose logs -f redis
            ;;
        5)
            docker compose logs -f
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}"
            ;;
    esac

    cd "$PROJECT_ROOT"
}

# Check if xcpretty is installed (for better Xcode output)
if ! command -v xcpretty &> /dev/null; then
    echo -e "${YELLOW}Note: xcpretty not installed for prettier build output.${NC}"
    echo -e "${YELLOW}      Install with: sudo gem install xcpretty${NC}"
fi

# Check if Xcode Command Line Tools are installed
if ! xcode-select -p &> /dev/null; then
    echo -e "${RED}Error: Xcode Command Line Tools not installed.${NC}"
    echo -e "${YELLOW}Install with: xcode-select --install${NC}"
fi

# Main execution
while true; do
    show_menu
    read -r choice

    case $choice in
        1)
            start_all_services
            echo -e "\n${GREEN}✓ All Docker services started${NC}"
            echo -e "${YELLOW}API: http://localhost:8000${NC}"
            echo -e "${YELLOW}Supabase: http://localhost:8001${NC}"
            echo -e "${YELLOW}Database: localhost:5432${NC}"
            echo -e "${YELLOW}Redis: redis:6379${NC}"
            ;;
        2)
            start_all_services
            sleep 5  # Give services time to start
            build_ios_app
            ;;
        3)
            build_ios_app
            ;;
        4)
            check_status
            ;;
        5)
            stop_services
            ;;
        6)
            view_logs
            ;;
        0)
            echo -e "\n${GREEN}Goodbye!${NC}\n"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option${NC}"
            ;;
    esac
done
