# Troubleshooting Guide

Common issues and solutions for the Modal application.

## Table of Contents
- [API Container Issues](#api-container-issues)
- [Database Issues](#database-issues)
- [Docker Issues](#docker-issues)
- [Colima Issues](#colima-issues)
- [Environment Configuration](#environment-configuration)
- [iOS Build Issues](#ios-build-issues)

---

## API Container Issues

### API Container Keeps Restarting

**Symptoms:**
- `docker compose ps` shows `modal-api` with status "Restarting (1)"
- iOS app can't connect to localhost:8080
- Error: "ModuleNotFoundError: No module named 'redis'" (or other Python packages)

**Root Cause:**
The Docker image wasn't rebuilt after adding new Python dependencies to `pyproject.toml`.

**Solution:**

Quick Fix:
```bash
cd docker
docker compose build api
docker compose up -d api
```

Verify it's working:
```bash
# Check container status
docker compose ps api

# Should show: Up X seconds (healthy)

# Test the API
curl http://localhost:8080/health
# Should return: {"status":"healthy","service":"Modal API","version":"1.0.0"}
```

**Prevention:**
The startup script now automatically rebuilds the API container when you start services.

### Missing Python Dependencies

**Error:** `ModuleNotFoundError: No module named 'X'`

**Fix:**
```bash
# Add the package to apps/api/pyproject.toml
# Then rebuild:
docker compose build api
docker compose up -d api
```

### API Port Already in Use

**Error:** `port is already allocated` (port 8080)

**Fix:**
```bash
# Find what's using the port
lsof -i :8080

# Kill the process or change the port in docker-compose.yml
```

### API Logs

View API logs:
```bash
docker compose logs -f api
```

View all logs:
```bash
docker compose logs -f
```

---

## Database Issues

### Database Container is Unhealthy

**Symptoms:**
- `supabase-db` shows as "unhealthy" in `docker compose ps`
- Error when running `startup.sh` after `setup.sh`
- Services fail to connect to database

**Common Causes:**

1. **JWT Configuration Mismatch**
   - Running containers have old JWT keys
   - Environment files updated but containers not restarted

   **Solution:**
   ```bash
   # Full restart to apply new configuration
   cd docker
   docker compose down
   docker compose up -d
   ```

2. **Port Conflict**
   - Port 5432 already in use by another PostgreSQL instance

   **Solution:**
   ```bash
   # Check what's using port 5432
   lsof -i :5432

   # Stop conflicting service or change port in .env
   # Edit docker/.env and docker/supabase/.env:
   POSTGRES_PORT=5433  # Use different port
   ```

3. **Corrupted Volume / Port Parameter Empty**
   - Database volume has corrupted data or missing environment variables
   - Error: `FATAL: invalid value for parameter "port": ""`
   - Error: `Database directory appears to contain a database; Skipping initialization`

   **Cause:**
   This happens when:
   - Setting up on a machine that previously had Modal installed
   - Docker volumes contain old data with incorrect configuration
   - POSTGRES_PORT variable is missing or empty in .env files

   **Solution (Recommended - use setup script):**
   ```bash
   # Run setup script - it will detect volumes and offer to clean them
   ./scripts/setup.sh
   # Choose option 2: "Clean volumes and start fresh"
   ```

   **Solution (Manual):**
   ```bash
   # ⚠️ WARNING: This deletes all data
   cd docker
   docker compose down -v  # -v removes volumes
   cd ..
   ./scripts/setup.sh      # Regenerate config
   ```

4. **Insufficient Resources**
   - Docker Desktop has insufficient memory/CPU

   **Solution:**
   - Open Docker Desktop → Settings → Resources
   - Increase Memory to at least 4GB
   - Increase CPU to at least 2 cores

### Database Connection Issues

**Error:** Can't connect to database

**Fix:**
```bash
# Check if database is running
docker compose ps db

# If not healthy, restart:
docker compose restart db
```

**Check Database Logs:**
```bash
cd docker
docker compose logs db --tail=100
```

**Common Error Messages:**

| Error | Cause | Solution |
|-------|-------|----------|
| `invalid value for parameter "port": ""` | POSTGRES_PORT not set or corrupted volume | Clean volumes: `docker compose down -v` then restart |
| `Database directory appears to contain a database` | Stale volume with wrong config | Clean volumes: `docker compose down -v` then run `setup.sh` |
| `role "authenticator" does not exist` | Database not fully initialized | Wait 30s more, or restart containers |
| `JWT verification failed` | JWT keys don't match | Run `setup.sh` and restart containers |
| `port 5432 already in use` | Port conflict | Change port or stop conflicting service |
| `no space left on device` | Disk full | Free up disk space or prune Docker: `docker system prune` |

---

## Docker Issues

### Containers Keep Restarting

**Symptoms:**
- Containers show "Restarting" status
- Services become available then immediately fail

**Solution:**
```bash
# Check logs for the failing service
docker compose logs [service-name] --tail=50

# Common fixes:
cd docker

# 1. Rebuild containers
docker compose build --no-cache

# 2. Full restart
docker compose down
docker compose up -d

# 3. Nuclear option (deletes data)
docker compose down -v
docker compose up -d
```

### "Error response from daemon: Conflict"

**Symptoms:**
- Cannot start containers due to naming conflicts

**Solution:**
```bash
# Remove orphaned containers
docker compose down --remove-orphans

# Or manually remove conflicting containers
docker ps -a | grep modal
docker rm -f [container-id]
```

### Network Errors

**Symptoms:**
- Containers can't communicate with each other
- "Network modal_network not found"

**Solution:**
```bash
# Recreate network
docker network rm modal_network
docker compose up -d
```

---

## Colima Issues

### Port Forwarding Not Working

**Symptoms:**
- Docker shows port mapping (e.g., `0.0.0.0:8000->8000/tcp`) but `curl http://localhost:8000` fails
- Connection refused errors when accessing ports from host Mac
- Services work fine inside Docker network but not accessible from macOS

**Root Cause:**
When using Colima (instead of Docker Desktop), port forwarding requires Colima to be fully initialized. Sometimes after changing port mappings or after system sleep/wake, Colima's port forwarding stops working.

**Solution:**

Restart Colima to reinitialize port forwarding:
```bash
colima stop
colima start
```

After Colima restarts, test your ports:
```bash
curl http://localhost:8000/
```

**Verification:**
```bash
# Check that ports work inside Colima VM
colima ssh -- curl -s http://localhost:8000/

# Check from macOS
curl http://localhost:8000/
```

Both should return responses (even if "Unauthorized" - that's OK, it means the service is accessible).

**Prevention:**
- After changing Docker port mappings in `.env` files, always restart Colima
- After system sleep/wake, you may need to restart Colima
- Consider using `colima start --foreground` during development to see connection issues immediately

**Alternative Workarounds:**

If restarting doesn't work:
1. **Check Colima status:**
   ```bash
   colima status
   ```

2. **Use Colima VM IP directly:**
   ```bash
   # Get VM IP
   colima ssh ip addr | grep "inet " | grep "192.168"

   # Use that IP instead of localhost
   curl http://192.168.5.1:8000/
   ```

3. **Rebuild Colima completely** (nuclear option):
   ```bash
   colima delete
   colima start --cpu 4 --memory 8 --disk 60
   ```

---

## Environment Configuration

### Tunnel Configuration

When using a tunnel (e.g., ngrok, tunn.dev) for development with physical devices:

#### iOS App Configuration

**[apps/modal/Config.xcconfig](apps/modal/Config.xcconfig):**

For localhost development (simulator):
```xcconfig
API_BASE_URL = http:/$()/localhost:8080/api/v1
WEBSOCKET_URL = ws:/$()/localhost:8080/api/v1
SUPABASE_URL = http:/$()/localhost:8000
```

For tunnel (physical device):
```xcconfig
// Use tunnel for all services (Kong routes to API internally)
API_BASE_URL = https:/$()/your-tunnel-url.tunn.dev/api/v1
WEBSOCKET_URL = wss:/$()/your-tunnel-url.tunn.dev/api/v1
SUPABASE_URL = https:/$()/your-tunnel-url.tunn.dev
```

**Important:**
- Use `https://` instead of `http://` (tunnel provides SSL)
- Use `wss://` instead of `ws://` for WebSocket (secure WebSocket)
- Route ALL traffic through port 8000 (Kong), which internally routes to your API on port 8080

#### Backend Configuration

**[docker/.env](docker/.env) and [docker/supabase/.env](docker/supabase/.env):**

For tunnel configuration, update:
```bash
# API Configuration
API_EXTERNAL_URL=https://your-tunnel-url.tunn.dev

# OAuth - Google (must match Google Console configuration)
GOOGLE_REDIRECT_URI=https://your-tunnel-url.tunn.dev/auth/v1/callback
GOTRUE_GOOGLE_REDIRECT_URI=https://your-tunnel-url.tunn.dev/auth/v1/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=https://your-tunnel-url.tunn.dev/api/v1/integrations/gmail/callback
```

**Critical:** Update your Google Cloud Console OAuth redirect URIs to match the tunnel URL.

### "SUPABASE_KONG_URL" variable is not set

**Symptoms:**
- API container fails to start
- Error: `SUPABASE_KONG_URL field required`

**Cause:**
- Old environment configuration using deprecated variable names

**Solution:**
```bash
# Run setup script to update configuration
./scripts/setup.sh

# Or manually update docker/.env:
SUPABASE_KONG_URL=http://kong:8000
```

### JWT Keys Don't Match

**Symptoms:**
- Authentication fails
- "Invalid JWT signature"
- Services can't communicate

**Cause:**
- JWT keys in different .env files don't match
- Containers running with old keys

**Solution:**
```bash
# Regenerate and sync all JWT keys
./scripts/setup.sh

# When prompted, choose to use existing JWT_SECRET
# Then restart containers when asked

# Or manually:
cd docker
docker compose down
docker compose up -d
```

### OAuth Not Working

**Symptoms:**
- Google/Spotify sign-in fails
- "Redirect URI mismatch"

**Solution:**
```bash
# Update OAuth credentials
./scripts/setup.sh
# Choose 'y' when asked to update OAuth credentials

# Verify redirect URIs match in:
# - Google Cloud Console
# - Spotify Developer Dashboard
# - docker/.env
# - docker/supabase/.env
```

---

## iOS Build Issues

### "Config.xcconfig not found"

**Solution:**
```bash
# Generate config from template
./scripts/setup.sh
```

### "SUPABASE_URL is not set"

**Solution:**
```bash
# Update iOS configuration
./scripts/setup.sh
# Choose 'y' when asked to update Config.xcconfig
```

### Build Succeeds But App Won't Launch

**Symptoms:**
- App installs but crashes immediately
- No error in build logs

**Solution:**
```bash
# Check backend is running
curl http://localhost:8080/health

# Check Supabase is accessible
curl http://localhost:8000/

# Verify iOS Config.xcconfig has correct URLs:
# API_BASE_URL should point to your backend
# SUPABASE_URL should be http://localhost:8000
```

---

## Quick Fixes Checklist

When things go wrong, try these in order:

1. **Check Service Status**
   ```bash
   cd docker
   docker compose ps
   ```

2. **Check Logs**
   ```bash
   docker compose logs --tail=50
   ```

3. **Restart Services**
   ```bash
   docker compose restart
   ```

4. **Full Restart**
   ```bash
   docker compose down
   docker compose up -d
   ```

5. **Rebuild Configuration**
   ```bash
   ./scripts/setup.sh
   ```

6. **Nuclear Option** (⚠️ deletes data)
   ```bash
   cd docker
   docker compose down -v --rmi all
   ./scripts/setup.sh
   ./scripts/startup.sh
   ```

---

## Complete Reset

If all else fails:
```bash
# Stop everything
docker compose down -v

# Rebuild everything
docker compose build

# Start fresh
docker compose up -d
```

---

## Setup Script Best Practices

### First Time Setup

```bash
# 1. Run setup script
./scripts/setup.sh

# 2. Choose to start Docker containers when prompted
# 3. Wait for services to become healthy (30-60 seconds)

# 4. Use startup script for iOS
./scripts/startup.sh
```

### When to Re-run Setup

Run `./scripts/setup.sh` when:
- Cloning the repository on a new machine
- Rotating JWT secrets
- Updating OAuth credentials
- After pulling changes that affect environment configuration
- When you see "field required" errors for environment variables

Do NOT re-run setup when:
- Just restarting containers (use `docker compose restart`)
- Building iOS app (use `./scripts/startup.sh`)
- Making code changes

### Setup + Startup Workflow

**Correct:**
```bash
# Run setup once
./scripts/setup.sh
# → Choose to restart Docker containers: Yes

# Then use startup for iOS builds
./scripts/startup.sh
# → Choose option 3 (Build iOS only, since Docker is already running)
```

**Incorrect:**
```bash
# ❌ Don't do this:
./scripts/setup.sh
# → Skip Docker restart

./scripts/startup.sh
# → Choose option 1 (Start Docker)
# This will start Docker with old configuration!
```

---

## Getting Help

If you're still stuck after trying these solutions:

1. **Check the logs** - Most issues show clear errors in logs
   ```bash
   docker compose logs --tail=100 > logs.txt
   ```

2. **Verify environment files** - Ensure all `.env` files exist and have correct values:
   - `docker/.env`
   - `docker/supabase/.env`
   - `apps/api/.env`
   - `apps/modal/Config.xcconfig`

3. **Check Docker resources** - Ensure Docker Desktop has enough resources allocated

4. **Review recent changes** - If it was working before, what changed?

5. **Start fresh** - Sometimes the cleanest solution:
   ```bash
   cd docker
   docker compose down -v
   cd ..
   ./scripts/setup.sh  # Choose Yes to start Docker
   ```

---

**Last Updated:** January 2025
