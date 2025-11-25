# Architecture Guide

This document describes the architecture, design decisions, and patterns used in the Modal application.

## System Overview

Modal is a full-stack application with three main components:

```
┌─────────────┐
│   iOS App   │
│  (SwiftUI)  │
└──────┬──────┘
       │
       │ HTTPS
       │
┌──────▼──────┐      ┌──────────────┐
│   Backend   │◄────►│   Supabase   │
│  (FastAPI)  │      │ (Auth + DB)  │
└──────┬──────┘      └──────────────┘
       │
       │
┌──────▼──────┐
│ PostgreSQL  │
│  Database   │
└─────────────┘
```

### Component Responsibilities

**iOS App**:
- User interface and interactions
- OAuth flows (Google, Apple Sign In)
- Session management
- Direct communication with Supabase for auth
- Backend API calls for business data

**Backend (FastAPI)**:
- Business logic
- Data persistence in PostgreSQL
- User management and sync
- API endpoints for app features
- Token validation via Supabase

**Supabase**:
- Authentication provider
- OAuth management (Google, Apple)
- Session management
- JWT token generation

**PostgreSQL**:
- Primary data store
- User records synced from Supabase
- Application-specific data

## Architecture Patterns

### Backend Architecture

#### Layered Architecture

```
┌─────────────────────────────────────┐
│         Routers (API Layer)         │
│  - HTTP endpoints                   │
│  - Request/response handling        │
│  - Input validation                 │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│       Services (Business Logic)     │
│  - Pipeline (Voice/Command)         │
│  - Workspace (Gmail/Calendar)       │
│  - Spotify                          │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│         Models (Data Layer)         │
│  - SQLAlchemy ORM models            │
│  - Database schema                  │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│      Database (PostgreSQL)          │
│  - Data persistence                 │
└─────────────────────────────────────┘
```

**Key Principles**:

1. **Separation of Concerns**: Each layer has a specific responsibility
2. **Dependency Injection**: Use FastAPI's dependency system
3. **Type Safety**: Pydantic schemas validate all data
4. **Error Handling**: Centralized exception handling
5. **Logging**: Structured logging at each layer

#### Request Flow

```
Client Request
    ↓
Router (validate input via Pydantic)
    ↓
Service (business logic)
    ↓
Model (database operations)
    ↓
Database
    ↓
Model (return data)
    ↓
Service (transform data)
    ↓
Router (format response via Pydantic)
    ↓
Client Response
```

#### Event Driven Architecture

In addition to the synchronous request/response flow, the application uses an event-driven approach for long-running tasks and voice processing.

```
Voice Input
    ↓
API (Producer)
    ↓
Kafka (Event Stream)
    ↓
Worker (Consumer)
    ↓
TaskIQ (Task Queue)
    ↓
RabbitMQ/Redis
    ↓
Service Execution
```

**Components**:
- **Kafka**: Handles high-throughput voice and command events.
- **TaskIQ**: Manages background tasks (e.g., email syncing, calendar updates).
- **RabbitMQ**: Message broker for TaskIQ.
- **Worker**: Dedicated service for processing background jobs.

### Frontend Architecture (iOS)

#### MVVM Pattern

```
┌─────────────────────────────────────┐
│         View (SwiftUI)              │
│  - UI rendering                     │
│  - User interactions                │
│  - Observes ViewModel               │
└─────────────┬───────────────────────┘
              │ @Observable
┌─────────────▼───────────────────────┐
│         ViewModel                   │
│  - View state                       │
│  - Business logic                   │
│  - Calls Services                   │
└─────────────┬───────────────────────┘
              │
┌─────────────▼───────────────────────┐
│         Services                    │
│  - Network calls                    │
│  - Authentication                   │
│  - Data persistence                 │
└─────────────────────────────────────┘
```

**Component Organization**:

```
Views/
├── Root/           # Top-level navigation
├── Onboarding/     # Authentication flow
├── Home/           # Main app screens
└── Components/     # Reusable UI components
```

### Backend Structure

```
app/
├── services/
│   ├── pipeline/   # Voice processing & Command parsing
│   ├── workspace/  # External integrations (Gmail, Calendar)
│   └── spotify/    # Spotify integration
└── workers/        # Background task workers
```

## Authentication Flow

### Detailed OAuth Flow (Google Sign-In)

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌─────────┐
│ iOS App │     │  Google  │     │ Supabase │     │ Backend │
└────┬────┘     └────┬─────┘     └────┬─────┘     └────┬────┘
     │               │                │                │
     │ 1. Open       │                │                │
     │    Google     │                │                │
     │    Sign-In    │                │                │
     ├──────────────►│                │                │
     │               │                │                │
     │ 2. User       │                │                │
     │    authenticates               │                │
     │◄──────────────┤                │                │
     │               │                │                │
     │ 3. Return     │                │                │
     │    ID token   │                │                │
     │◄──────────────┤                │                │
     │               │                │                │
     │ 4. Send ID token               │                │
     ├──────────────────────────────-►│                │
     │               │                │                │
     │ 5. Validate   │                │                │
     │    with Google│                │                │
     │               │◄───────────────┤                │
     │               │                │                │
     │ 6. Return     │                │                │
     │    Supabase   │                │                │
     │    session    │                │                │
     │◄────────────────────────────── ┤                │
     │               │                │                │
     │ 7. Sync user with backend      │                │
     │    (send access token)         │                │
     ├────────────────────────────────────────────────►│
     │               │                │                │
     │               │                │ 8. Validate    │
     │               │                │    token       │
     │               │                │◄───────────────┤
     │               │                │                │
     │               │                │ 9. Create/     │
     │               │                │    update user │
     │               │                │    in DB       │
     │               │                │                │
     │ 10. Return user data           │                │
     │◄────────────────────────────────────────────────┤
     │               │                │                │
```

### Critical Configuration

**Supabase**: Must have `skip_nonce_check = true` for Google OAuth

Why? The Google Sign-In SDK generates nonces internally. Supabase cannot validate these nonces because they're managed by the SDK, not our application. Therefore, we must configure Supabase to skip nonce validation.

**Configuration**:
```toml
# supabase/config.toml
[auth.external.google]
enabled = true
client_id = "env(GOOGLE_CLIENT_ID)"
secret = "env(GOOGLE_CLIENT_SECRET)"
skip_nonce_check = true  # CRITICAL
```

**Docker Environment**:
```yaml
# supabase/docker-compose.yml
auth:
  environment:
    GOTRUE_EXTERNAL_GOOGLE_SKIP_NONCE_CHECK: "true"
```

## Data Models

### User Model

The user exists in two places:

1. **Supabase Auth**: Authentication provider (source of truth for auth)
2. **Backend PostgreSQL**: Application-specific user data

```
Supabase User             Backend User
┌──────────────┐         ┌──────────────┐
│ id           │────────►│ id (PK)      │
│ email        │         │ email        │
│ app_metadata │         │ provider     │
│ user_metadata│────────►│ full_name    │
│              │         │ avatar_url   │
│              │         │ username     │
│              │         │ is_active    │
│              │         │ is_verified  │
│              │         │ created_at   │
│              │         │ updated_at   │
│              │         │ last_login   │
└──────────────┘         └──────────────┘
```

**Sync Process**:
1. User authenticates with Supabase
2. iOS app receives Supabase session
3. App calls `/auth/sync` with access token
4. Backend validates token with Supabase
5. Backend creates/updates user in PostgreSQL
6. Backend returns user data to app

### Database Schema

```sql
CREATE TABLE users (
    id VARCHAR PRIMARY KEY,           -- From Supabase
    email VARCHAR UNIQUE NOT NULL,
    username VARCHAR UNIQUE,
    full_name VARCHAR,
    avatar_url VARCHAR,
    provider VARCHAR NOT NULL,        -- google, apple, email
    provider_id VARCHAR,              -- Provider's user ID
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_provider ON users(provider);
CREATE INDEX idx_users_provider_id ON users(provider_id);
```

## API Design

### Endpoint Structure

```
/api/v1/
├── /auth/
│   ├── POST /sync      # Sync user from Supabase to backend
│   ├── POST /refresh   # Refresh access token
│   └── GET  /me        # Get current user
│
└── /health            # Health check (no /v1 prefix)
```

### Request/Response Format

**Request**:
```json
{
  "standard_format": "camelCase in frontend",
  "snake_case": "in backend"
}
```

**Response**:
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "username",
  "full_name": "Full Name",
  "avatar_url": "https://...",
  "provider": "google",
  "is_active": true,
  "is_verified": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Error Response**:
```json
{
  "detail": "Error message"
}
```

### Authentication

All protected endpoints require:
```
Authorization: Bearer <supabase_access_token>
```

Backend validates the token with Supabase before processing requests.

## State Management

### Backend (FastAPI)

**Session Management**:
- FastAPI dependency injection for database sessions
- Automatic rollback on errors
- Connection pooling configured in SQLAlchemy

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

### Frontend (iOS)

**Observable Pattern**:
```swift
@Observable
class AuthenticationService {
    var session: Session?
    var currentUser: User?
    var isAuthenticated: Bool { session != nil }
    
    // Automatically updates views when these properties change
}
```

**State Flow**:
```
User Action
    ↓
View calls ViewModel/Service method
    ↓
Service updates @Observable properties
    ↓
SwiftUI automatically re-renders affected views
```

## Error Handling

### Backend

**Strategy**: Catch exceptions at router level, log, and return appropriate HTTP status

```python
try:
    # Business logic
    result = await service.do_something()
    return result
except HTTPException:
    # Already formatted, re-raise
    raise
except SpecificError as e:
    # Handle specific errors
    logger.warning(f"Specific error: {e}")
    raise HTTPException(status_code=400, detail=str(e))
except Exception as e:
    # Catch-all for unexpected errors
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error")
```

### Frontend

**Strategy**: Show user-friendly error messages, log detailed errors

```swift
do {
    try await authService.signIn()
} catch AuthError.invalidCredentials {
    showError(message: "Invalid email or password")
} catch {
    print("Error: \(error)")  // Detailed logging
    showError(message: "Something went wrong. Please try again.")
}
```

## Performance Considerations

### Backend

1. **Database Connection Pooling**:
   ```python
   engine = create_engine(
       settings.DATABASE_URL,
       pool_size=5,
       max_overflow=10,
       pool_recycle=3600
   )
   ```

2. **Async Operations**: Use async/await for I/O operations
3. **Caching**: Redis for session caching (optional)
4. **Pagination**: Implement for list endpoints
5. **Indexing**: Database indexes on frequently queried columns

### Frontend

1. **Lazy Loading**: Load data only when needed
2. **Image Caching**: Use URLCache for avatar images
3. **Background Tasks**: Use Task for async operations
4. **Debouncing**: Prevent excessive API calls

## Security

### Authentication

1. **JWT Tokens**: Short-lived access tokens (1 hour)
2. **Refresh Tokens**: Long-lived for token renewal
3. **Token Storage**: Secure iOS Keychain via Supabase SDK
4. **HTTPS Only**: All production communication over TLS

### Data Protection

1. **Input Validation**: Pydantic schemas validate all inputs
2. **SQL Injection**: Protected by SQLAlchemy ORM
3. **XSS**: Not applicable (no server-side rendering)
4. **CORS**: Configured for specific origins only

### Secrets Management

1. **Environment Variables**: All secrets in .env files
2. **Never Commit Secrets**: .env files in .gitignore
3. **Rotate Keys**: Regular rotation of JWT secrets
4. **Least Privilege**: Service keys with minimal permissions

## Scalability

### Current Architecture (Single Server)

Suitable for:
- Up to 10,000 daily active users
- < 100 requests/second
- Single region deployment

### Scaling Strategy

**Horizontal Scaling**:
1. Deploy multiple backend instances behind load balancer
2. Use Redis for shared session cache
3. PostgreSQL read replicas for read-heavy workloads
4. CDN for static assets

**Vertical Scaling**:
1. Increase server resources (CPU, RAM)
2. Optimize database queries
3. Add database indexes

**Microservices** (Future):
- Auth service
- User service
- Feature-specific services

## Monitoring and Observability

### Logging

**Backend**:
- Structured logging with Python logging module
- Log levels: DEBUG, INFO, WARNING, ERROR
- Include request IDs for tracing

**iOS**:
- Console logging with prefixes (SUCCESS, ERROR, WARN)
- Crash reporting (future: Sentry or similar)

### Metrics

**Backend** (Future):
- Prometheus for metrics collection
- Grafana for visualization
- Track: request rate, error rate, latency

**Health Checks**:
```
GET /health
Response: {"status": "healthy", "service": "modal-api"}
```

## Testing Strategy

### Backend

1. **Unit Tests**: Test business logic in services
2. **Integration Tests**: Test API endpoints
3. **Database Tests**: Use test database
4. **Mocking**: Mock external services (Supabase)

### Frontend

1. **Unit Tests**: Test ViewModels and Services
2. **UI Tests**: Test critical user flows
3. **Snapshot Tests**: Detect UI regressions

## Deployment Architecture

### Production Setup

```
┌──────────────┐
│   CloudFlare │  (CDN, DDoS protection)
│   or similar │
└──────┬───────┘
       │
┌──────▼────────┐
│ Load Balancer │  (AWS ALB, etc.)
└──────┬────────┘
       │
   ┌───┴───┐
   │       │
┌──▼───┐ ┌─▼────┐
│ API  │ │ API  │  (FastAPI containers)
│ Pod 1│ │ Pod 2│
└──┬───┘ └─┬────┘
   │       │
   └───┬───┘
       │
┌──────▼──────┐
│ PostgreSQL  │  (AWS RDS, managed)
│  + Replicas │
└─────────────┘
```

### Environment Strategy

- **Development**: Local Supabase + local PostgreSQL
- **Staging**: Cloud Supabase + cloud PostgreSQL (small instance)
- **Production**: Cloud Supabase + cloud PostgreSQL (sized appropriately)
