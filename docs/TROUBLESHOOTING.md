# Troubleshooting Guide

Common issues and solutions for the Modal application.

## Table of Contents
- [Database Issues](#database-issues)
- [Docker Issues](#docker-issues)
- [Environment Configuration](#environment-configuration)
- [iOS Build Issues](#ios-build-issues)

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

## Environment Configuration

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
curl http://localhost:8001/

# Verify iOS Config.xcconfig has correct URLs:
# API_BASE_URL should point to your backend
# SUPABASE_URL should be http://localhost:8001
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
- ✅ Cloning the repository on a new machine
- ✅ Rotating JWT secrets
- ✅ Updating OAuth credentials
- ✅ After pulling changes that affect environment configuration
- ✅ When you see "field required" errors for environment variables

Do NOT re-run setup when:
- ❌ Just restarting containers (use `docker compose restart`)
- ❌ Building iOS app (use `./scripts/startup.sh`)
- ❌ Making code changes

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

**Last Updated:** October 16, 2025
