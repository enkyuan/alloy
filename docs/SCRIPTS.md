# Modal Scripts

This directory contains utility scripts for the Modal project.

## 🚀 Quick Start

```bash
# 1. Generate and sync environment variables
./scripts/env.sh

# 2. Start everything (Docker + iOS app)
./scripts/startup.sh
```

---

## 📋 Scripts Overview

### 1. env.sh - Environment Configuration

**Purpose**: Generate Supabase JWT keys and sync environment variables across all .env files.

**What it does**:
- Generates secure JWT secret (or uses existing)
- Creates ANON_KEY and SERVICE_ROLE_KEY JWT tokens
- Syncs keys across three .env files:
  - `/` \.env (root - used by Docker Compose)
  - `/supabase/.env` (Supabase services)
  - `/apps/api/.env` (FastAPI local development)
- Updates Kong configuration
- Manages OAuth credentials (Google, Spotify)

**Usage**:

```bash
# Make executable (first time only)
chmod +x scripts/env.sh

# Run the script
./scripts/env.sh
```

**Interactive Prompts**:
1. Use existing JWT_SECRET? (Y/n)
2. Update Google OAuth credentials? (y/N)
3. Update Spotify OAuth credentials? (y/N)

**Key Features**:
- ✅ Ensures consistency across all .env files
- ✅ Preserves existing OAuth credentials
- ✅ Creates backups before modifying files
- ✅ Validates required fields
- ✅ Updates Kong gateway configuration

**Output**:
```
=== Configuration Summary ===
JWT Secret:        [SYNCED]
ANON Key:          [SYNCED]
SERVICE_ROLE Key:  [SYNCED]
Google OAuth:      [SYNCED]
Spotify OAuth:     [SYNCED]
```

**Environment Variables Managed**:

| Variable | Location | Description |
|----------|----------|-------------|
| `JWT_SECRET` | All 3 files | HMAC secret for JWT signing |
| `ANON_KEY` | All 3 files | Anonymous access JWT |
| `SERVICE_ROLE_KEY` | All 3 files | Service-level access JWT |
| `GOOGLE_CLIENT_ID` | All 3 files | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | All 3 files | Google OAuth secret |
| `SPOTIFY_CLIENT_ID` | Root + API | Spotify OAuth client ID |
| `SPOTIFY_CLIENT_SECRET` | Root + API | Spotify OAuth secret |

---

### 2. startup.sh - Application Launcher

**Purpose**: Interactive menu to start Docker services and build/run the iOS app.

**What it does**:
- Starts Supabase Docker services
- Starts Modal API Docker services
- Builds iOS app with Xcode
- Launches app on selected simulator
- Provides service management tools

**Usage**:

```bash
# Make executable (first time only)
chmod +x scripts/startup.sh

# Run the script
./scripts/startup.sh
```

**Interactive Menu**:
```
=== Startup Options ===
1) Start Docker containers only
2) Start Docker + Build and run iOS app
3) Build and run iOS app only
4) Check service status
5) Stop/cleanup services
6) View logs
0) Exit
```

**Features**:

#### Option 1: Start Docker Containers
- Starts Supabase services (auth, database, Kong, etc.)
- Starts Modal API service
- Creates required Docker networks
- Waits for services to be healthy

#### Option 2: Docker + iOS App
- Starts all Docker services
- Lists available iOS simulators
- Lets you select a simulator (or defaults to iPhone 15 Pro)
- Builds the iOS app with Xcodebuild
- Installs and launches app on selected simulator

#### Option 3: iOS App Only
- Skips Docker services
- Builds and runs iOS app
- Useful when services are already running

#### Option 4: Check Service Status
Shows status of all Docker containers:
```
SUPABASE SERVICES:
NAME                STATUS      PORTS
supabase-db         running     5432
supabase-auth       running     9999
supabase-kong       running     8001

MODAL SERVICES:
NAME                STATUS      PORTS
modal-api           running     8000
modal-redis         running     6379
```

#### Option 5: Stop/Cleanup Services
Provides a sub-menu with 4 shutdown options:

**1. Stop containers (keep data)**
- Runs: `docker compose stop`
- Stops containers but keeps them
- Data preserved: ✅ Database, Redis, all volumes
- Use case: Temporary shutdown, fastest restart

**2. Remove containers (keep volumes/data)**
- Runs: `docker compose down`
- Removes containers but keeps volumes
- Data preserved: ✅ Database, Redis data
- Use case: Clean restart, reclaim some memory

**3. Remove containers and volumes** (⚠️ Destructive)
- Runs: `docker compose down -v`
- Removes containers AND volumes
- Data preserved: ❌ All data deleted
- Requires confirmation: Type "yes"
- Use case: Fresh start, testing migrations

**4. Full cleanup** (⚠️ Very Destructive)
- Runs: `docker compose down -v --rmi all`
- Removes containers, volumes, AND images
- Data preserved: ❌ Everything deleted
- Requires confirmation: Type "yes"
- Use case: Free disk space, force rebuild

| Option | Containers | Volumes | Images | Database | Redis | Restart Speed |
|--------|-----------|---------|--------|----------|-------|---------------|
| 1 | Stop | Keep | Keep | ✅ Kept | ✅ Kept | Instant |
| 2 | Remove | Keep | Keep | ✅ Kept | ✅ Kept | Fast |
| 3 | Remove | Delete | Keep | ❌ Lost | ❌ Lost | Medium |
| 4 | Remove | Delete | Delete | ❌ Lost | ❌ Lost | Slow (rebuild) |

#### Option 6: View Logs
Options to view:
- Modal API logs
- Supabase Auth logs
- All logs (combined)

**iOS Simulator Selection**:
```
=== Available iOS Simulators ===

★ Currently Booted:
  ▸ iPhone 15 Pro

All Available Devices:
  1  iPhone SE (3rd generation)
  2  iPhone 14
  3  iPhone 14 Plus
  4  iPhone 14 Pro
  5  iPhone 14 Pro Max
  6  iPhone 15
  7  iPhone 15 Plus
  8  iPhone 15 Pro
  9  iPhone 15 Pro Max

Enter simulator number (or press Enter for currently booted device):
```

**Smart Device Selection**:
- If a device is booted: Pressing **Enter** selects the booted device
- If no device is booted: Pressing **Enter** defaults to iPhone 15 Pro
- Booted devices are shown with a **★** and **no number** (auto-selected)
- Available devices are numbered for manual selection

**Build Output**:
- Uses `xcpretty` if installed for prettier output
- Shows build progress and errors
- Verifies installation on correct device (displays UDID)
- Confirms successful launch
- **Auto-exits after successful launch** (no need to manually exit)

**Service URLs**:
After starting services:
- **API**: http://localhost:8000
- **Supabase**: http://localhost:8001
- **Redis**: localhost:6379

---

## 🔄 Typical Workflow

### First Time Setup

```bash
# 1. Generate environment variables
./scripts/env.sh
# Enter OAuth credentials when prompted

# 2. Start everything
./scripts/startup.sh
# Choose option 2 (Docker + iOS)
```

### Daily Development

```bash
# Start services in the morning
./scripts/startup.sh
# Choose option 1 (Docker only)

# Make code changes...

# Rebuild and test iOS app
./scripts/startup.sh
# Choose option 3 (iOS only)

# Check service status
./scripts/startup.sh
# Choose option 4

# View logs when debugging
./scripts/startup.sh
# Choose option 6
```

### Updating OAuth Credentials

```bash
# 1. Update credentials
./scripts/env.sh
# Answer 'y' to update OAuth credentials

# 2. Restart services to apply changes
./scripts/startup.sh
# Choose option 5 to stop
# Then choose option 1 to start
```

---

## 🛠 Prerequisites

### Required Tools

| Tool | Purpose | Installation |
|------|---------|--------------|
| `bash` 4.0+ | Script execution | Pre-installed on macOS/Linux |
| `openssl` | Key generation | `brew install openssl` |
| `docker` | Container runtime | [Docker Desktop](https://www.docker.com/products/docker-desktop) |
| `docker-compose` | Multi-container orchestration | Included with Docker Desktop |
| `xcodebuild` | iOS app building | Install Xcode from App Store |
| `xcrun` | iOS simulator control | Included with Xcode |

### Optional Tools

| Tool | Purpose | Installation |
|------|---------|--------------|
| `xcpretty` | Prettier Xcode output | `gem install xcpretty` |

---

## 📁 File Structure

```
.
├── .env                      # Root env (Docker Compose)
├── supabase/
│   └── .env                  # Supabase services env
├── apps/
│   └── api/
│       └── .env              # FastAPI local dev env
└── scripts/
    ├── env.sh                # Environment sync script
    ├── startup.sh            # Application launcher
    └── README.md             # This file
```

---

## 🔒 Security Best Practices

### 1. Environment Files
- ✅ All `.env` files are in `.gitignore`
- ✅ Never commit sensitive keys
- ✅ Use different keys per environment (dev/staging/prod)
- ✅ Rotate keys periodically

### 2. JWT Tokens
- Generated JWTs expire in year 2099 (development only)
- For production, use shorter expiry times
- Regenerate keys if compromised

### 3. OAuth Credentials
- Keep client secrets secure
- Use different credentials per environment
- Configure redirect URIs properly

### 4. Backups
Scripts create timestamped backups:
```
.env.backup.20241012_143022
kong.yml.backup.20241012_143022
```
- Safe to delete after verification
- Keep backups secure (contain sensitive data)

---

## 🐛 Troubleshooting

### env.sh Issues

#### "openssl: command not found"
```bash
# macOS
brew install openssl

# Linux
sudo apt-get install openssl
```

#### "JWT_SECRET not syncing"
- Check file permissions
- Ensure script completed without errors
- Manually verify with: `grep JWT_SECRET .env supabase/.env apps/api/.env`

#### "OAuth not working after update"
- Restart Docker containers
- Check that all .env files have the credentials
- Verify redirect URIs match OAuth provider configuration

### startup.sh Issues

#### "Docker is required but not installed"
- Install [Docker Desktop](https://www.docker.com/products/docker-desktop)
- Ensure Docker daemon is running

#### "Container failed to become healthy"
- Check Docker logs: `docker-compose logs <service>`
- Ensure ports 5432, 6379, 8000, 8001 are not in use
- Try: `docker-compose down && docker-compose up -d`

#### "Build failed" (iOS)
- Open project in Xcode and build manually to see detailed errors
- Clean build folder: `rm -rf ~/Library/Developer/Xcode/DerivedData`
- Check that all Swift packages are resolved

#### "Simulator not booting"
- Quit Simulator.app and retry
- Restart macOS
- Check: `xcrun simctl list devices`

#### "No simulators available"
- Install iOS Simulator from Xcode
- Xcode → Preferences → Components → iOS Simulators

---

## 🔧 Advanced Usage

### Running Services Separately

```bash
# Start only Supabase
cd supabase && docker-compose up -d

# Start only API
docker-compose up -d modal_api

# Start only Redis
docker-compose up -d redis
```

### Manual iOS Build

```bash
cd apps/modal

# List simulators
xcrun simctl list devices

# Build for specific simulator
xcodebuild \
  -project modal.xcodeproj \
  -scheme modal \
  -sdk iphonesimulator \
  -destination 'name=iPhone 15 Pro' \
  clean build
```

### Viewing Logs

```bash
# API logs
docker logs -f modal-api

# Supabase auth logs
cd supabase && docker-compose logs -f auth

# All Supabase logs
cd supabase && docker-compose logs -f

# Redis logs
docker logs -f modal-redis
```

### Database Access

```bash
# Connect to PostgreSQL
docker exec -it supabase-db psql -U postgres

# Run migrations
cd apps/api
poetry run alembic upgrade head

# Create new migration
poetry run alembic revision --autogenerate -m "description"
```

---

## 📚 Related Documentation

- [README.md](/README.md) - Project overview
- [CLAUDE.md](/CLAUDE.md) - AI assistant guide
- [docs/SETUP.md](/docs/SETUP.md) - Detailed setup instructions
- [docs/ARCHITECTURE.md](/docs/ARCHITECTURE.md) - System architecture
- [docs/API.md](/docs/API.md) - API documentation
- [docs/DOCKER.md](/docs/DOCKER.md) - Docker configuration

---

## 🆘 Getting Help

1. **Check the Troubleshooting section** above
2. **Review related documentation** (links above)
3. **Check service logs** for detailed error messages
4. **Open an issue** in the repository with:
   - Script name and command run
   - Error message (if any)
   - Relevant log output
   - OS and version

---

## 📝 Notes

- Scripts are designed for **development** environments
- For **production**, use proper secret management (AWS Secrets Manager, Vault, etc.)
- Scripts create backups automatically - clean up old backups periodically
- Always test in development before deploying to production

---

## ✅ Quick Reference

```bash
# Generate/sync environment variables
./scripts/env.sh

# Start everything (interactive menu)
./scripts/startup.sh

# Start Docker only
./scripts/startup.sh
# → Choose option 1

# Start Docker + iOS
./scripts/startup.sh
# → Choose option 2

# Build iOS only
./scripts/startup.sh
# → Choose option 3

# Check status
./scripts/startup.sh
# → Choose option 4

# Stop/cleanup services (with sub-options)
./scripts/startup.sh
# → Choose option 5
# → Then choose:
#    1 = Stop containers (keep data)
#    2 = Remove containers (keep volumes/data)
#    3 = Remove containers + volumes (deletes all data)
#    4 = Full cleanup including images

# View logs
./scripts/startup.sh
# → Choose option 6
```
