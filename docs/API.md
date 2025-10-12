# API Documentation

This document provides detailed documentation for all Backend API endpoints.

## Base URL

**Development**: `http://localhost:8000`
**Production**: `https://your-domain.com`

**API Version**: All endpoints are prefixed with `/api/v1` except health check.

## Authentication

Most endpoints require authentication via Bearer token:

```http
Authorization: Bearer <supabase_access_token>
```

The token is obtained from Supabase after successful authentication in the iOS app.

## Endpoints

### Health Check

Check if the API is running and healthy.

**Endpoint**: `GET /health`

**Authentication**: None required

**Response**: `200 OK`
```json
{
  "status": "healthy",
  "service": "Modal API",
  "version": "1.0.0"
}
```

---

### Root

Get API information and available endpoints.

**Endpoint**: `GET /`

**Authentication**: None required

**Response**: `200 OK`
```json
{
  "message": "Modal API",
  "version": "1.0.0",
  "docs": "/api/v1/docs",
  "health": "/health"
}
```

---

## Authentication Endpoints

### Sync User

Sync user from Supabase to the backend database. Called automatically after successful authentication in the iOS app.

**Endpoint**: `POST /api/v1/auth/sync`

**Authentication**: Required

**Headers**:
```http
Authorization: Bearer <supabase_access_token>
Content-Type: application/json
```

**Request Body**: None

**Response**: `200 OK`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "avatar_url": "https://lh3.googleusercontent.com/a/...",
  "provider": "google",
  "is_active": true,
  "is_verified": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Error Responses**:

`401 Unauthorized` - Missing or invalid token
```json
{
  "detail": "Missing or invalid authorization header"
}
```

`500 Internal Server Error` - Server error during sync
```json
{
  "detail": "Failed to sync user: <error message>"
}
```

**Description**:
This endpoint:
1. Validates the Supabase access token
2. Retrieves user information from Supabase
3. Creates a new user record in the backend database if not exists
4. Updates existing user record if already exists
5. Returns the user data

---

### Get Current User

Get the currently authenticated user's information.

**Endpoint**: `GET /api/v1/auth/me`

**Authentication**: Required

**Headers**:
```http
Authorization: Bearer <supabase_access_token>
```

**Response**: `200 OK`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "avatar_url": "https://lh3.googleusercontent.com/a/...",
  "provider": "google",
  "is_active": true,
  "is_verified": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Error Responses**:

`401 Unauthorized` - Missing, invalid, or expired token
```json
{
  "detail": "Invalid or expired token"
}
```

`404 Not Found` - User not found in database
```json
{
  "detail": "User not found"
}
```

`500 Internal Server Error` - Server error
```json
{
  "detail": "Failed to get user: <error message>"
}
```

**Description**:
Returns the user data for the authenticated user. The user must have been previously synced via `/auth/sync`.

---

### Refresh Token

Refresh an expired access token using a refresh token.

**Endpoint**: `POST /api/v1/auth/refresh`

**Authentication**: None (uses refresh token)

**Request Body**:
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response**: `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "username": "johndoe",
    "full_name": "John Doe",
    "avatar_url": "https://lh3.googleusercontent.com/a/...",
    "provider": "google",
    "is_active": true,
    "is_verified": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

**Error Responses**:

`404 Not Found` - User not found
```json
{
  "detail": "User not found"
}
```

`500 Internal Server Error` - Token refresh failed
```json
{
  "detail": "Token refresh failed: <error message>"
}
```

**Description**:
Exchanges a refresh token for a new access token. The refresh token must be valid and not expired.

---

## Data Models

### User

Represents an authenticated user in the system.

**Fields**:
- `id` (string, UUID): Unique identifier from Supabase
- `email` (string, email): User's email address
- `username` (string, nullable): Optional username
- `full_name` (string, nullable): User's full name
- `avatar_url` (string, nullable): URL to user's profile picture
- `provider` (string): OAuth provider (`google`, `apple`, `email`)
- `is_active` (boolean): Whether the account is active
- `is_verified` (boolean): Whether the email is verified
- `created_at` (string, ISO 8601): Account creation timestamp

**Example**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "avatar_url": "https://lh3.googleusercontent.com/a/...",
  "provider": "google",
  "is_active": true,
  "is_verified": true,
  "created_at": "2024-01-01T00:00:00.000Z"
}
```

---

### TokenResponse

Response model for token refresh endpoint.

**Fields**:
- `access_token` (string): New JWT access token
- `token_type` (string): Token type (always `"bearer"`)
- `expires_in` (integer): Token expiration time in seconds
- `refresh_token` (string, nullable): New refresh token (optional)
- `user` (User): User information

**Example**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "username": "johndoe",
    "full_name": "John Doe",
    "avatar_url": "https://lh3.googleusercontent.com/a/...",
    "provider": "google",
    "is_active": true,
    "is_verified": true,
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

---

## Error Handling

### Standard Error Response

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### HTTP Status Codes

- `200 OK`: Request succeeded
- `400 Bad Request`: Invalid request parameters or body
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: Authenticated but not authorized for this resource
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation error
- `500 Internal Server Error`: Server-side error

### Common Error Scenarios

**Invalid Token**:
```json
{
  "detail": "Invalid or expired token"
}
```

**Missing Authorization Header**:
```json
{
  "detail": "Missing or invalid authorization header"
}
```

**User Not Found**:
```json
{
  "detail": "User not found"
}
```

**Validation Error**:
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```

---

## Rate Limiting

**Current Status**: Not implemented

**Future Implementation**:
- 100 requests per minute per IP address
- 1000 requests per hour per authenticated user
- Rate limit headers in responses:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

---

## Pagination

**Current Status**: Not implemented

**Future Implementation**:
For list endpoints, pagination will follow this pattern:

**Request**:
```
GET /api/v1/resource?page=1&per_page=20
```

**Response**:
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "per_page": 20,
  "pages": 5
}
```

---

## Interactive Documentation

FastAPI automatically generates interactive API documentation:

- **Swagger UI**: `http://localhost:8000/api/v1/docs`
- **ReDoc**: `http://localhost:8000/api/v1/redoc`

These provide:
- Interactive request/response testing
- Schema validation
- Example requests
- Authentication testing

---

## SDK / Client Libraries

### iOS (Swift)

The iOS app includes a built-in `AuthenticationService` that handles all API communication:

```swift
let authService = AuthenticationService(
    backendURL: "http://localhost:8000/api/v1"
)

// Sync user after authentication
await authService.syncUserWithBackend()

// The service automatically includes the Supabase access token
// in the Authorization header
```

### Other Platforms

For other platforms, you can use:
- **Python**: `httpx` or `requests`
- **JavaScript**: `fetch` or `axios`
- **cURL**: For testing

**Example (Python)**:
```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8000/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    user = response.json()
```

**Example (cURL)**:
```bash
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer <access_token>"
```

---

## Versioning

**Current Version**: v1

**Versioning Strategy**:
- API version in URL path (`/api/v1/`)
- Breaking changes require new version
- Old versions supported for 6 months after new version release
- Version deprecation announced via:
  - API documentation
  - Response headers
  - Email to registered developers

---

## Security Considerations

### Token Management

1. **Access Tokens**:
   - Short-lived (1 hour)
   - Include in Authorization header
   - Never log or expose in URLs

2. **Refresh Tokens**:
   - Long-lived (30 days)
   - Stored securely in iOS Keychain
   - Single-use (rotated on refresh)

### Best Practices

1. **Always use HTTPS** in production
2. **Validate all inputs** (handled by Pydantic)
3. **Never expose sensitive data** in logs or errors
4. **Implement rate limiting** (future)
5. **Monitor for suspicious activity**

---

## Support

For API issues or questions:
1. Check interactive documentation: `/api/v1/docs`
2. Review this documentation
3. Check backend logs: `docker-compose logs api`
4. Open an issue in the project repository

---

## Changelog

### Version 1.0.0 (Current)

**Released**: 2024-01-01

**Features**:
- User authentication and sync
- Google OAuth integration
- Token refresh
- Health check endpoint

**Future Enhancements**:
- Additional user endpoints (update profile, delete account)
- Rate limiting
- Pagination for list endpoints
- WebSocket support
- GraphQL API

