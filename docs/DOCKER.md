# Docker Setup Guide

This guide explains how to run the Modal application stack using Docker Compose, including the FastAPI backend, Redis, and Supabase.

## Prerequisites

- Docker Desktop 4.0+ (includes Docker Compose V2)
- At least 4GB of available RAM
- Ports available: 3000, 5432, 6379, 8000, 8001, 8443

## Quick Start

### 1. Set Up Environment Variables

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

**Important:** For production, you must change:
- `POSTGRES_PASSWORD`
- `JWT_SECRET` (generate with: `openssl rand -base64 32`)
- `ANON_KEY` and `SERVICE_ROLE_KEY` (regenerate using Supabase JWT generator)

### 2. Start All Services

```bash
docker compose up -d
```

This will start:
- **FastAPI Backend** - http://localhost:8000
- **Worker** - Background task processor
- **Redis** - localhost:6379
- **Kafka** - localhost:9092
- **RabbitMQ** - localhost:5672 (Management: http://localhost:15672)
- **Supabase Studio** - http://localhost:3000 (Database UI)
- **Supabase API Gateway (Kong)** - http://localhost:8001
- **PostgreSQL** - localhost:5432

### 3. Verify Services

Check that all services are running:

```bash
docker compose ps
```

All services should show `Up` or `healthy` status.

### 4. Run Database Migrations
 
 ```bash
 docker compose exec api alembic upgrade head
 ```
 
 **Alternative (Local Poetry):**
 If you have the environment set up locally:
 ```bash
 cd apps/api
 poetry run alembic upgrade head
 ```

## Service Details

### FastAPI Backend (Port 8000)

- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health
- **Hot Reload**: Enabled (changes to `apps/api/` are reflected immediately)

**Logs:**
```bash
docker compose logs -f api
```

### Redis (Port 6379)

Redis is used for caching and session management.

**Connect with redis-cli:**
```bash
docker compose exec redis redis-cli
```

**Monitor Redis:**
```bash
docker compose exec redis redis-cli MONITOR
```

### Kafka (Port 9092)

Event streaming platform for handling voice and command events.

- **Internal**: `kafka:9092`
- **External**: `localhost:9092`

### RabbitMQ (Port 5672)

Message broker used by TaskIQ for background task distribution.

- **Management UI**: http://localhost:15672 (User/Pass: admin/admin)
- **AMQP Port**: 5672

### Worker

Background worker service that consumes tasks from RabbitMQ/Redis.

- **Container Name**: `modal-worker`
- **Command**: Runs `taskiq worker`
- **Scaling**: Can be scaled horizontally (`docker compose up -d --scale worker=3`)

### Supabase

#### Supabase Studio (Port 3000)

Web-based database management UI:
- URL: http://localhost:3000
- View tables, run queries, manage auth users
- Real-time data updates

#### Database (PostgreSQL - Port 5432)

**Connect directly:**
```bash
docker compose exec supabase-db psql -U postgres
```

**Connection string:**
```
postgresql://postgres:postgres@localhost:5432/postgres
```

#### Supabase API (Port 8001)

The Kong gateway exposes Supabase services:

- **REST API**: http://localhost:8001/rest/v1/
- **Auth**: http://localhost:8001/auth/v1/
- **Storage**: http://localhost:8001/storage/v1/
- **Realtime**: ws://localhost:8001/realtime/v1/

**API Keys:**
- Anon Key: Use `ANON_KEY` from `.env`
- Service Role Key: Use `SERVICE_ROLE_KEY` from `.env`

## Common Commands

### Start Services
```bash
# Start all services
docker compose up -d

# Start specific service
docker compose up -d api
```

### Stop Services
```bash
# Stop all services
docker compose down

# Stop and remove volumes (WARNING: deletes all data)
docker compose down -v
```

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f supabase-db
```

### Restart Services
```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart api
```

### Rebuild Images
```bash
# Rebuild API after dependency changes
docker compose build api

# Rebuild and restart
docker compose up -d --build api
```

### Execute Commands
```bash
# Run commands in the API container
docker compose exec api poetry run pytest

# Access PostgreSQL
docker compose exec supabase-db psql -U postgres

# Access Redis CLI
docker compose exec redis redis-cli
```

## Development Workflow

### Making API Changes

1. Edit files in `apps/api/`
2. Changes are automatically reloaded (uvicorn --reload)
3. Check logs: `docker compose logs -f api`

### Adding Python Dependencies

1. Edit `apps/api/pyproject.toml`
2. Rebuild the container:
   ```bash
   docker compose build api
   docker compose up -d api
   ```

### Database Migrations

**Create a new migration:**
```bash
docker compose exec api alembic revision --autogenerate -m "description"
```

**Apply migrations:**
```bash
docker compose exec api alembic upgrade head
```

**Rollback migration:**
```bash
docker compose exec api alembic downgrade -1
```

### Running Tests

```bash
# Run all tests
docker compose exec api poetry run pytest

# Run with coverage
docker compose exec api poetry run pytest --cov=app

# Run specific test file
docker compose exec api poetry run pytest tests/test_main.py
```

## Troubleshooting

### Services Won't Start

**Check logs:**
```bash
docker compose logs
```

**Common issues:**
- Port conflicts: Ensure ports 3000, 5432, 6379, 8000, 8001 are available
- Insufficient memory: Allocate at least 4GB to Docker Desktop
- Database not ready: Wait for `supabase-db` health check to pass

### API Can't Connect to Database

1. Check database is running:
   ```bash
   docker compose ps supabase-db
   ```

2. Verify connection string in `.env`:
   ```
   DATABASE_URL=postgresql://postgres:postgres@supabase-db:5432/postgres
   ```

3. Test connection:
   ```bash
   docker compose exec api python -c "from sqlalchemy import create_engine; create_engine('postgresql://postgres:postgres@supabase-db:5432/postgres').connect()"
   ```

### Redis Connection Issues

Check Redis is healthy:
```bash
docker compose exec redis redis-cli ping
```

Should return `PONG`.

### Supabase Studio Not Loading

1. Ensure Kong is running: `docker compose ps kong`
2. Check Kong logs: `docker compose logs kong`
3. Verify Kong configuration: `docker compose exec kong kong config -c /etc/kong/kong.conf`

### Reset Everything

**WARNING: This deletes all data!**

```bash
docker compose down -v
docker compose up -d
docker compose exec api alembic upgrade head
```

## Production Considerations

### Security

1. **Change default passwords:**
   - Set strong `POSTGRES_PASSWORD`
   - Generate new `JWT_SECRET`
   - Regenerate Supabase keys

2. **Environment variables:**
   - Never commit `.env` to version control
   - Use secrets management (AWS Secrets Manager, HashiCorp Vault)

3. **Network security:**
   - Use Docker networks to isolate services
   - Don't expose database ports publicly
   - Use HTTPS/TLS for all external connections

### Performance

1. **Database:**
   - Configure connection pooling
   - Set up read replicas for scaling
   - Regular backups with `pg_dump`

2. **Redis:**
   - Configure persistence (AOF/RDB)
   - Set max memory limits
   - Use Redis Cluster for high availability

3. **API:**
   - Use production ASGI server (Gunicorn + Uvicorn workers)
   - Disable `--reload` flag
   - Set up horizontal scaling with load balancer

### Monitoring

Add monitoring services:
- **Prometheus**: Metrics collection
- **Grafana**: Visualization dashboards
- **Loki**: Log aggregation
- **Health checks**: Implement comprehensive /health endpoints

### Backups

**Database backup:**
```bash
docker compose exec -T supabase-db pg_dump -U postgres postgres > backup_$(date +%Y%m%d).sql
```

**Restore backup:**
```bash
cat backup_20241012.sql | docker compose exec -T supabase-db psql -U postgres postgres
```

## iOS App Configuration

When running the backend in Docker, update your iOS app configuration:

**For iOS Simulator:**
```swift
let apiURL = "http://localhost:8000"
let supabaseURL = "http://localhost:8001"
```

**For Physical iPhone:**
1. Find your computer's local IP:
   ```bash
   ipconfig getifaddr en0
   ```

2. Update iOS config:
   ```swift
   let apiURL = "http://192.168.1.100:8000"  // Your IP
   let supabaseURL = "http://192.168.1.100:8001"
   ```

3. Ensure firewall allows connections on ports 8000 and 8001

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Supabase Documentation](https://supabase.com/docs)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Redis Documentation](https://redis.io/docs/)

## Support

For issues or questions:
1. Check logs: `docker compose logs`
2. Review this guide's troubleshooting section
3. Open an issue in the project repository
