# Modal Docker Compose Setup

This repository contains Docker Compose configurations for running the Modal application stack with Supabase, Redis, and the Modal API.

## Services

### Supabase Stack
- **Studio** (Port 8000): Supabase Studio dashboard for database management
- **Kong** (Port 8001): API Gateway for routing requests
- **Auth**: Authentication service with Google OAuth support
- **PostgREST**: Automatic REST API for PostgreSQL
- **Realtime**: WebSocket server for real-time subscriptions
- **Storage**: Object storage service
- **PostgreSQL** (Port 5432): Main database
- **Analytics**: Logging and analytics service

### Application Services
- **Redis** (Port 6379): In-memory cache and message broker
- **Modal API** (Port 8080): FastAPI backend service

## Prerequisites

- Docker Desktop or Docker Engine with Docker Compose
- Git
- At least 4GB of available RAM

## Quick Start

### Option 1: Run from Root Directory

```bash
# Navigate to project root
cd /Users/enkyuan/Desktop/Projects/modal

# Copy environment file (if needed)
cp supabase/.env.example supabase/.env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

### Option 2: Run from Supabase Directory

```bash
# Navigate to supabase directory
cd /Users/enkyuan/Desktop/Projects/modal/supabase

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

## Service URLs

After starting the services, you can access:

- **Supabase Studio**: http://localhost:8000
- **Supabase API Gateway**: http://localhost:8001
- **Modal API**: http://localhost:8080
  - Health Check: http://localhost:8080/health
  - API Docs: http://localhost:8080/api/v1/docs
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

## Google OAuth Configuration

The setup includes Google OAuth configuration. The credentials are loaded from your environment variables:

```env
GOOGLE_CLIENT_ID=1021220745951-7mavjjtg16o9i91eb7rtcc6smpg3m1b9.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback
```

### Setting Up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable Google Sign-In API
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URIs:
   - `http://localhost:8001/auth/v1/callback` (Supabase)
   - `http://localhost:8080/api/v1/auth/google/callback` (API)
6. Update the `.env` files with your credentials

## Database Initialization

The API will automatically run Alembic migrations on startup to create the necessary tables:

```bash
# Check migration status
docker-compose exec api alembic current

# Create a new migration
docker-compose exec api alembic revision --autogenerate -m "description"

# Apply migrations manually
docker-compose exec api alembic upgrade head
```

## Environment Variables

### Supabase Environment (supabase/.env)

Key variables you should configure:

```env
# Database
POSTGRES_PASSWORD=postgres

# JWT
JWT_SECRET=your-secret-key
JWT_EXPIRY=3600

# Supabase Keys
ANON_KEY=your-anon-key
SERVICE_ROLE_KEY=your-service-role-key

# URLs
API_EXTERNAL_URL=http://localhost:8001
SITE_URL=http://localhost:3000

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8080/api/v1/auth/google/callback
```

## Useful Commands

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f db
docker-compose logs -f auth

# Last 100 lines
docker-compose logs --tail=100 api
```

### Rebuilding Services

```bash
# Rebuild and restart API
docker-compose up -d --build api

# Rebuild everything
docker-compose up -d --build
```

### Database Access

```bash
# Connect to PostgreSQL
docker-compose exec db psql -U postgres -d postgres

# Run SQL file
docker-compose exec db psql -U postgres -d postgres -f /path/to/file.sql

# Create database backup
docker-compose exec db pg_dump -U postgres postgres > backup.sql

# Restore database backup
docker-compose exec -T db psql -U postgres -d postgres < backup.sql
```

### Redis Access

```bash
# Connect to Redis CLI
docker-compose exec redis redis-cli

# Monitor Redis commands
docker-compose exec redis redis-cli monitor

# Check Redis info
docker-compose exec redis redis-cli info
```

### Cleaning Up

```bash
# Stop services
docker-compose down

# Stop and remove volumes (CAUTION: This deletes all data)
docker-compose down -v

# Remove all containers, networks, and images
docker-compose down --rmi all
```

## Troubleshooting

### Services Not Starting

1. Check logs: `docker-compose logs [service-name]`
2. Ensure ports are not in use: `lsof -i :8000,8001,8080,5432,6379`
3. Verify environment variables are set correctly
4. Check available disk space and memory

### API Connection Issues

If the API can't connect to services:

1. Verify service names in environment variables (use `db`, `redis`, `kong` instead of `localhost`)
2. Check that dependent services are healthy: `docker-compose ps`
3. Verify network connectivity: `docker-compose exec api ping db`

### Database Migration Errors

```bash
# Reset migrations (CAUTION: This will drop all tables)
docker-compose exec api alembic downgrade base
docker-compose exec api alembic upgrade head

# Or recreate the database container
docker-compose down db
docker-compose up -d db
```

### Port Conflicts

If ports are already in use, you can modify the port mappings in `docker-compose.yml`:

```yaml
ports:
  - "8080:8000"  # Change first number to use different host port
```

## Development Workflow

### Making Changes to the API

The API container mounts the code as read-only. To apply changes:

```bash
# Rebuild the API container
docker-compose up -d --build api

# View logs to verify changes
docker-compose logs -f api
```

### Database Schema Changes

```bash
# 1. Modify models in apps/api/app/models/
# 2. Generate migration
docker-compose exec api alembic revision --autogenerate -m "add new field"

# 3. Review generated migration in apps/api/alembic/versions/
# 4. Apply migration
docker-compose exec api alembic upgrade head
```

## Production Considerations

Before deploying to production:

1. **Change default passwords**: Update `POSTGRES_PASSWORD`, `DASHBOARD_PASSWORD`
2. **Generate new JWT secrets**: Use `openssl rand -base64 32`
3. **Use production OAuth credentials**: Update Google OAuth keys
4. **Set up proper SMTP**: Configure email settings for auth
5. **Enable SSL/TLS**: Configure Kong for HTTPS
6. **Set up backups**: Implement database backup strategy
7. **Configure resource limits**: Add CPU/memory limits to services
8. **Use secrets management**: Don't commit credentials to git
9. **Enable monitoring**: Set up logging and alerting
10. **Review security settings**: Disable debug mode, restrict CORS

## Support

For issues specific to:
- **Supabase**: https://supabase.com/docs
- **FastAPI**: https://fastapi.tiangolo.com/
- **Docker Compose**: https://docs.docker.com/compose/
