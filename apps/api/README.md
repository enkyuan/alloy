# Modal API

FastAPI backend for Modal voice assistant with Google OAuth and Supabase integration.

## Features

- 🔐 Google OAuth authentication via Supabase
- 🍎 Apple Sign In support
- 👤 User management with PostgreSQL
- 🗄️ Database migrations with Alembic
- 🔄 JWT token refresh
- 📝 OpenAPI documentation

## Setup

### 1. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

**Required Environment Variables:**

- `DATABASE_URL`: PostgreSQL connection string
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_ANON_KEY`: Supabase anonymous key
- `SUPABASE_SERVICE_KEY`: Supabase service role key
- `JWT_SECRET`: Secret key for JWT tokens

**Optional for Enhanced Features:**

- `GOOGLE_CLIENT_ID`: Google OAuth client ID (for server-side verification)
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret
- `APPLE_CLIENT_ID`: Apple Sign In service ID
- Other Apple credentials for Apple Sign In

### 2. Supabase Setup

1. Go to your [Supabase Dashboard](https://supabase.com/dashboard)
2. Enable Google authentication:
   - Go to Authentication → Providers
   - Enable Google provider
   - Add your Google OAuth credentials
   - Add redirect URLs for your iOS app

3. Get your Supabase credentials:
   - Project Settings → API
   - Copy `URL`, `anon` key, and `service_role` key

### 3. Google OAuth Setup (for iOS)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google Sign-In API
4. Create OAuth 2.0 credentials:
   - Application type: iOS
   - Bundle ID: `com.app.modal` (or your bundle ID)
5. Download the client ID
6. Add the client ID to your Supabase Google provider settings

### 4. Database Migration

Run Alembic migrations to create the users table:

```bash
# Generate migration (if needed)
alembic revision --autogenerate -m "create users table"

# Apply migration
alembic upgrade head
```

### 5. Run the Application

```bash
# Development with hot reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Or with Docker
docker-compose up api
```

## API Endpoints

### Authentication

- `POST /api/v1/auth/google` - Authenticate with Google OAuth
  ```json
  {
    "id_token": "google-id-token-from-ios-app"
  }
  ```

- `POST /api/v1/auth/apple` - Authenticate with Apple Sign In
  ```json
  {
    "id_token": "apple-id-token-from-ios-app",
    "authorization_code": "optional-auth-code",
    "user_info": {}
  }
  ```

- `POST /api/v1/auth/refresh` - Refresh access token
  ```json
  {
    "refresh_token": "your-refresh-token"
  }
  ```

- `GET /api/v1/auth/me` - Get current user (requires Authorization header)

### Health Check

- `GET /health` - API health status

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Database Schema

### Users Table

| Column | Type | Description |
|--------|------|-------------|
| id | String | Primary key (from Supabase) |
| email | String | User email (unique) |
| username | String | Username (unique, optional) |
| full_name | String | User's full name |
| avatar_url | String | Profile picture URL |
| provider | String | OAuth provider (google, apple, email) |
| provider_id | String | Provider-specific user ID |
| is_active | Boolean | Account active status |
| is_verified | Boolean | Email verification status |
| created_at | DateTime | Account creation timestamp |
| updated_at | DateTime | Last update timestamp |
| last_login | DateTime | Last login timestamp |

## Development

### Project Structure

```
app/
├── __init__.py
├── main.py              # FastAPI application
├── config.py            # Configuration settings
├── database.py          # Database connection
├── models/              # SQLAlchemy models
│   ├── __init__.py
│   └── user.py
├── schemas/             # Pydantic schemas
│   ├── __init__.py
│   └── auth.py
├── routers/             # API routes
│   ├── __init__.py
│   └── auth.py
└── services/            # Business logic
    ├── __init__.py
    └── supabase_auth.py
```

### Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=app tests/
```

## iOS Integration

To integrate with your iOS app:

1. Install Google Sign-In SDK in your iOS project
2. Configure Google Sign-In with your client ID
3. When user signs in, get the ID token
4. Send the ID token to `/api/v1/auth/google`
5. Store the returned access token and refresh token
6. Use the access token for authenticated requests

See the iOS app code for implementation details.

## Troubleshooting

### Common Issues

1. **Database connection fails**
   - Ensure PostgreSQL is running
   - Check DATABASE_URL in .env
   - Verify docker-compose services are up

2. **Supabase authentication fails**
   - Verify SUPABASE_URL and keys are correct
   - Check that Google provider is enabled in Supabase
   - Ensure redirect URLs are configured

3. **Token verification fails**
   - Check that ID token is fresh (not expired)
   - Verify the token is for the correct Google OAuth client
   - Ensure Supabase project has correct Google credentials

## License

MIT
