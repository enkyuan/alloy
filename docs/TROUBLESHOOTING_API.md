# Troubleshooting: API Container Issues

## Problem: API container keeps restarting

**Symptoms:**
- `docker compose ps` shows `modal-api` with status "Restarting (1)"
- iOS app can't connect to localhost:8080
- Error: "ModuleNotFoundError: No module named 'redis'" (or other Python packages)

## Root Cause

The Docker image wasn't rebuilt after adding new Python dependencies to `pyproject.toml`.

## Solution

### Quick Fix:
```bash
cd docker
docker compose build api
docker compose up -d api
```

### Verify it's working:
```bash
# Check container status
docker compose ps api

# Should show: Up X seconds (healthy)

# Test the API
curl http://localhost:8080/health
# Should return: {"status":"healthy","service":"Modal API","version":"1.0.0"}
```

### Prevention

The startup script now automatically rebuilds the API container when you start services.

## Common Issues

### 1. Missing Python Dependencies
**Error:** `ModuleNotFoundError: No module named 'X'`

**Fix:**
```bash
# Add the package to apps/api/pyproject.toml
# Then rebuild:
docker compose build api
docker compose up -d api
```

### 2. Database Connection Issues
**Error:** Can't connect to database

**Fix:**
```bash
# Check if database is running
docker compose ps db

# If not healthy, restart:
docker compose restart db
```

### 3. Port Already in Use
**Error:** `port is already allocated`

**Fix:**
```bash
# Find what's using the port
lsof -i :8080

# Kill the process or change the port in docker-compose.yml
```

## Environment Variables

For **localhost development** (same machine):
```xcconfig
API_BASE_URL = https:/$()/localhost:8080/api/v1
WEBSOCKET_URL = wss:/$()/localhost:8080/api/v1
SUPABASE_URL = https:/$()/localhost:8001
```

For **physical device testing** (ngrok):
```xcconfig
API_BASE_URL = https:/$()/your-ngrok-url.ngrok-free.app/api/v1
WEBSOCKET_URL = wss:/$()/your-ngrok-url.ngrok-free.app/api/v1
SUPABASE_URL = https:/$()/your-ngrok-url.ngrok-free.app
```

## Logs

View API logs:
```bash
docker compose logs -f api
```

View all logs:
```bash
docker compose logs -f
```

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
