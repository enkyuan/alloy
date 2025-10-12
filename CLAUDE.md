# Claude AI Assistant Guide

This document contains essential information for AI assistants (like Claude) working on the Modal project. It ensures consistency, maintains code quality, and prevents common mistakes.

## 🎯 Project Overview

**Modal** is a production-grade full-stack application with:
- **Backend**: FastAPI (Python) with PostgreSQL
- **Frontend**: SwiftUI iOS app
- **Auth**: Supabase with Google OAuth and Apple Sign In
- **Deployment**: Docker-ready, cloud-deployable

## 🏗️ Architecture Patterns

### Backend (FastAPI)

#### Layer Structure
```
Routers (API endpoints) 
    ↓
Services (Business logic) 
    ↓
Models (Database) 
    ↓
Database (PostgreSQL)
```

**Key Principles**:
1. **Routers**: Handle HTTP, validation, responses. NO business logic.
2. **Services**: All business logic, external API calls, complex operations
3. **Models**: SQLAlchemy ORM models, database schema
4. **Schemas**: Pydantic models for request/response validation

#### File Organization
```python
# apps/api/app/routers/auth.py
# - Route definitions
# - Input validation via Pydantic
# - HTTP status codes
# - Error handling
# - Call services for business logic

# apps/api/app/services/auth.py
# - Business logic
# - External API calls (Supabase)
# - Data transformations
# - Complex operations

# apps/api/app/models/user.py
# - SQLAlchemy models
# - Database schema
# - Relationships

# apps/api/app/schemas/auth.py
# - Pydantic schemas
# - Request/response models
# - Validation rules
```

### Frontend (iOS)

#### View Structure
```
Views/
├── Root/           # Navigation root (ContentView)
├── Onboarding/     # Authentication flow
├── Home/           # Main app screens
└── Components/     # Reusable components
```

**Key Principles**:
1. **MVVM**: ViewModels (`@Observable`) handle state and business logic
2. **Composition**: Small, reusable components
3. **Services**: Separate business logic from views
4. **MARK**: Use MARK comments for organization

## ⚠️ Critical Configuration

### Google OAuth Nonce Handling

**IMPORTANT**: The iOS app uses Google Sign-In SDK directly, which generates nonces internally. Supabase cannot validate these nonces, so:

**Backend (Supabase)**: `skip_nonce_check = true` MUST be set
- File: `supabase/config.toml`
- Setting: `[auth.external.google]` → `skip_nonce_check = true`
- Docker: `GOTRUE_EXTERNAL_GOOGLE_SKIP_NONCE_CHECK=true` in docker-compose.yml

**iOS**: Do NOT pass nonce parameter
```swift
// ✅ CORRECT
let session = try await SupabaseConfig.shared.auth.signInWithIdToken(
    credentials: .init(
        provider: .google,
        idToken: idToken
    )
)

// ❌ INCORRECT
let session = try await SupabaseConfig.shared.auth.signInWithIdToken(
    credentials: .init(
        provider: .google,
        idToken: idToken,
        nonce: someNonce  // DON'T DO THIS
    )
)
```

### Authentication Flow

**Correct Flow**:
1. iOS: Google Sign-In SDK → Get ID token
2. iOS: Send ID token to Supabase via `signInWithIdToken`
3. iOS: Receive Supabase session
4. iOS: Call backend `/auth/sync` with Supabase access token
5. Backend: Validate token with Supabase
6. Backend: Create/update user in PostgreSQL
7. Backend: Return user data

**DO NOT**:
- Send ID token directly to backend
- Use backend for OAuth redirect flows (use Supabase SDK in iOS)
- Store passwords or sensitive tokens

## 🔒 Security Best Practices

### Backend
1. **Never commit secrets**: Use environment variables
2. **Validate all inputs**: Use Pydantic schemas
3. **Use parameterized queries**: SQLAlchemy ORM handles this
4. **Log securely**: Don't log sensitive data (tokens, passwords)
5. **CORS**: Configure allowed origins properly

### iOS
1. **Anon key is safe**: Supabase anon key can be in client code
2. **No secrets in code**: Use configuration files (excluded from git)
3. **Validate backend responses**: Don't trust server blindly
4. **Handle errors gracefully**: User-friendly error messages

## 📝 Code Style Guide

### Python (Backend)

```python
"""Module docstring explaining purpose."""
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Get current authenticated user.
    
    Args:
        authorization: Bearer token from Authorization header
        db: Database session
        
    Returns:
        UserResponse with user data
        
    Raises:
        HTTPException: If user not found or token invalid
    """
    try:
        # Implementation
        pass
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed: {str(e)}"
        )
```

**Rules**:
- Docstrings for all public functions
- Type hints everywhere
- Logging with appropriate levels
- Structured error handling
- Import organization (stdlib → third-party → local)

### Swift (iOS)

```swift
import SwiftUI

// MARK: - Main View

/// Description of what this view does
struct ContentView: View {
    // MARK: - Properties
    
    @State private var authService = AuthenticationService()
    
    // MARK: - Body
    
    var body: some View {
        Group {
            if authService.isAuthenticated {
                HomeView(authService: authService)
            } else {
                OnboardingView(authService: authService)
            }
        }
    }
    
    // MARK: - Private Methods
    
    private func handleAuthentication() {
        // Implementation
    }
}

// MARK: - Preview

#Preview {
    ContentView()
}
```

**Rules**:
- MARK comments for organization
- Documentation comments for public APIs
- Descriptive variable names
- Group related code
- Extract complex views into components

## 🚫 Common Mistakes to Avoid

### Backend

1. **Mixing concerns**: Don't put business logic in routers
2. **Missing error handling**: Always catch and log exceptions
3. **No logging**: Add appropriate logging statements
4. **Hardcoded values**: Use config/environment variables
5. **Missing docstrings**: Document all public functions

### iOS

1. **Massive views**: Break large views into smaller components
2. **No error handling**: Always handle async errors gracefully
3. **State management**: Use `@Observable`, `@State`, `@Bindable` appropriately
4. **Force unwrapping**: Avoid `!` unless absolutely necessary
5. **Missing MARK**: Use MARK comments for organization

## 📊 Database Migrations

### Creating Migrations

```bash
# Auto-generate migration
cd apps/api
poetry run alembic revision --autogenerate -m "Add user preferences table"

# Review the generated migration in alembic/versions/
# Edit if needed (auto-generate isn't perfect)

# Apply migration
poetry run alembic upgrade head

# Rollback if needed
poetry run alembic downgrade -1
```

### Migration Guidelines

1. **Review auto-generated migrations**: They're not always perfect
2. **Test both upgrade and downgrade**: Ensure migrations are reversible
3. **One logical change per migration**: Don't mix unrelated changes
4. **Add indexes**: Don't forget indexes for foreign keys and queries
5. **Data migrations**: Separate schema and data migrations when needed

## 🧪 Testing Guidelines

### Backend Tests

```python
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_health_check():
    """Test health check endpoint returns healthy status."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
```

### iOS Tests

```swift
import XCTest
@testable import modal

final class AuthenticationServiceTests: XCTestCase {
    func testAuthenticationFlow() async throws {
        let service = AuthenticationService()
        // Test implementation
    }
}
```

## 🔄 Development Workflow

### Making Changes

1. **Read existing code**: Understand patterns before changing
2. **Follow existing structure**: Match file organization and naming
3. **Update documentation**: Keep docs in sync with code
4. **Test changes**: Run tests before committing
5. **Check linting**: Run linters (ruff, SwiftLint)

### Adding New Features

#### Backend API Endpoint

1. Define Pydantic schemas in `schemas/`
2. Add database model in `models/` (if needed)
3. Create/update service in `services/`
4. Add router in `routers/`
5. Create migration: `alembic revision --autogenerate`
6. Add tests
7. Update API documentation

#### iOS View

1. Create view in appropriate `Views/` subdirectory
2. Extract reusable components to `Components/`
3. Create ViewModel if complex state needed
4. Update navigation in parent view
5. Add assets to Assets.xcassets if needed
6. Test on simulator and device

## 📦 Dependencies

### Adding Backend Dependencies

```bash
cd apps/api
poetry add <package>           # Production dependency
poetry add --group dev <package>  # Dev dependency
```

Then rebuild Docker if using containers:
```bash
docker-compose build api
docker-compose up -d api
```

### Adding iOS Dependencies

Add to Xcode project via Swift Package Manager:
1. File → Add Package Dependencies
2. Enter package URL
3. Select version
4. Add to target

## 🌐 Environment Variables

### Backend (.env)

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/modal

# Supabase
SUPABASE_URL=http://localhost:8001
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_key

# Security
JWT_SECRET=generate_with_openssl_rand_base64_32

# Application
DEBUG=false
```

### iOS (SupabaseConfig.swift)

```swift
// Local development
static let supabaseURL = URL(string: "http://localhost:8001")!

// Production
static let supabaseURL = URL(string: "https://your-project.supabase.co")!
```

## 🎨 UI/UX Guidelines

### iOS Design Principles

1. **Native feel**: Use standard iOS patterns and components
2. **Accessibility**: Support VoiceOver, Dynamic Type
3. **Dark mode**: Ensure UI works in both light and dark modes
4. **Loading states**: Show loading indicators for async operations
5. **Error handling**: Display user-friendly error messages
6. **Animations**: Use subtle, purposeful animations

### Component Design

1. **Reusability**: Extract repeated UI into components
2. **Variants**: Use enums for component variants (not multiple components)
3. **Configuration**: Make components configurable via parameters
4. **Documentation**: Document component parameters and usage

## 📚 Documentation Requirements

### Code Documentation

**Always document**:
- Public APIs and interfaces
- Complex algorithms or logic
- Non-obvious decisions
- Workarounds or hacks
- TODOs with context

**Don't document**:
- Obvious code (self-explanatory)
- Every single line
- Implementation details users don't need

### Project Documentation

Keep these files updated:
- `README.md`: Project overview and quick start
- `docs/SETUP.md`: Detailed setup instructions
- `docs/ARCHITECTURE.md`: System design and decisions
- `docs/API.md`: API endpoint documentation
- `CLAUDE.md`: This file, for AI assistants

## ✅ Pre-Commit Checklist

Before committing code:

- [ ] Code follows project style guide
- [ ] All tests pass
- [ ] New code has tests
- [ ] Documentation is updated
- [ ] No secrets or sensitive data in code
- [ ] Linters pass (ruff, black for Python)
- [ ] Builds successfully (Xcode for iOS)
- [ ] Error handling is comprehensive
- [ ] Logging is appropriate
- [ ] No console.log or print statements in production code

## 🚀 Deployment Checklist

### Backend

- [ ] Environment variables configured
- [ ] Database migrations applied
- [ ] Secrets rotated (JWT, Supabase keys)
- [ ] CORS configured for production domain
- [ ] Logging configured
- [ ] Health check endpoint working
- [ ] SSL/TLS enabled
- [ ] Rate limiting configured

### iOS

- [ ] API endpoints point to production
- [ ] OAuth redirect URLs configured
- [ ] Code signing configured
- [ ] App icons and assets included
- [ ] Info.plist configured correctly
- [ ] Privacy policy and terms added
- [ ] App Store metadata prepared
- [ ] TestFlight testing complete

## 🎓 Learning Resources

### FastAPI
- [Official Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/)
- [Pydantic](https://docs.pydantic.dev/)

### SwiftUI
- [Apple SwiftUI Documentation](https://developer.apple.com/documentation/swiftui/)
- [Swift API Design Guidelines](https://swift.org/documentation/api-design-guidelines/)

### Supabase
- [Supabase Documentation](https://supabase.com/docs)
- [Supabase Swift SDK](https://github.com/supabase/supabase-swift)

## 🤝 Collaboration with AI

When working with AI assistants (Claude):

1. **Be specific**: Provide context and requirements clearly
2. **Review changes**: Always review AI-generated code
3. **Test thoroughly**: AI can make mistakes, test everything
4. **Follow patterns**: Point AI to existing code as examples
5. **Iterate**: Don't expect perfect code first try

## 📝 Notes

- This project prioritizes **code quality** and **maintainability**
- **Production-ready** means properly documented, tested, and error-handled
- **Modular** means easily testable, reusable, and understandable
- When in doubt, follow existing patterns in the codebase

