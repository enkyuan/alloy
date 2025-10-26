# Modal

## 🚀 Quick Start

### Prerequisites

- **Backend**: Python 3.11+, Poetry
- **iOS**: macOS with Xcode 15.0+, iOS 17.0+ SDK
- **Database**: Docker (for local Supabase) or Supabase Cloud account

### 1. Clone and Setup Environment

```bash
# Clone the repository
git clone <repository-url>
cd modal

# Copy environment files
cp .env.example .env
cp apps/api/.env.example apps/api/.env
cp supabase/.env.example supabase/.env

# Edit .env files with your credentials
```

### 2. Start Supabase (Local Development)

```bash
cd supabase
docker-compose up -d
```

**Important**: Make sure `skip_nonce_check = true` is set for Google OAuth in `supabase/config.toml`.

### 3. Start the Backend API

```bash
cd apps/api

# Install dependencies
poetry install

# Run migrations
poetry run alembic upgrade head

# Start development server
poetry run uvicorn app.main:app --reload --host 0.0.0.0
```

API will be available at:
- **Docs**: http://localhost:8000/api/v1/docs
- **Health**: http://localhost:8000/health

### 4. Configure iOS App

Update Google OAuth credentials in `apps/modal/modal/Info.plist`:
- Add your Google Client ID
- Configure URL schemes

Update Supabase configuration in `apps/modal/modal/Config/SupabaseConfig.swift`:
- Set `supabaseURL` to your Supabase instance
- Set `supabaseAnonKey` to your Supabase anon key

### 5. Run iOS App

```bash
# Open Xcode project
open apps/modal/modal.xcodeproj

# Or use command line
cd apps/modal
xcodebuild -scheme modal -destination 'platform=iOS Simulator,name=iPhone 15 Pro'
```

## 📚 Documentation

- [Setup Guide](docs/SETUP.md) - Detailed setup instructions
- [Docker Guide](docs/DOCKER.md) - Running with Docker Compose
- [Architecture Guide](docs/ARCHITECTURE.md) - System design and patterns
- [API Documentation](docs/API.md) - Backend API reference

## 🏛️ Technology Stack

### Backend
- **FastAPI**: Modern Python web framework
- **SQLAlchemy**: SQL toolkit and ORM
- **Alembic**: Database migrations
- **Pydantic**: Data validation
- **PostgreSQL**: Primary database
- **Supabase**: Authentication and additional services
- **Redis**: Caching (optional)

### Frontend (iOS)
- **SwiftUI**: Declarative UI framework
- **Supabase Swift SDK**: Authentication client
- **Google Sign-In SDK**: Google OAuth
- **Observation**: State management
- **Swift Package Manager**: Dependency management

### Infrastructure
- **Docker**: Containerization
- **Docker Compose**: Multi-container orchestration
- **Kong**: API gateway (Supabase)

## 🧪 Testing

### Backend Tests
```bash
cd apps/api
poetry run pytest
poetry run pytest --cov=app  # With coverage
```

### iOS Tests
```bash
cd apps/modal
xcodebuild test -scheme modal -destination 'platform=iOS Simulator,name=iPhone 15 Pro'
```

## 🚢 Deployment

### Backend Deployment

The FastAPI backend can be deployed to:
- **Railway**: Easiest option with automatic deployments
- **Fly.io**: Good for global distribution
- **AWS ECS/Fargate**: Enterprise-grade with full control
- **DigitalOcean App Platform**: Simple and cost-effective

See [Deployment Guide](docs/DEPLOYMENT.md) for detailed instructions.

### iOS Deployment

1. Archive the app in Xcode (`Product → Archive`)
2. Upload to App Store Connect
3. Submit for TestFlight or App Store review

## 🔧 Development

### Code Style

**Python (Backend)**:
- Follow PEP 8
- Use type hints
- Run `ruff` for linting
- Format with `black`

**Swift (iOS)**:
- Follow Swift API Design Guidelines
- Use MARK comments for organization
- Document public APIs
- Use meaningful variable names

### Project Structure Guidelines

1. **Modular**: Each component should be self-contained
2. **Documented**: All public APIs should have docstrings/comments
3. **Tested**: Write tests for business logic
4. **Type-Safe**: Use type hints (Python) and strong typing (Swift)
5. **Production-Ready**: Handle errors gracefully, log appropriately

### Adding New Features

1. **Backend API**:
   - Add route in `apps/api/app/routers/`
   - Add schemas in `apps/api/app/schemas/`
   - Add business logic in `apps/api/app/services/`
   - Update database models in `apps/api/app/models/`
   - Create migration: `alembic revision --autogenerate`

2. **iOS UI**:
   - Add views in `apps/modal/modal/Views/`
   - Create reusable components in `Views/Components/`
   - Add services in `apps/modal/modal/Services/`
   - Update configuration in `apps/modal/modal/Config/`

## 🐛 Troubleshooting

### Backend Issues

**"Module not found" errors**:
```bash
cd apps/api
poetry install
```

**Database connection errors**:
- Check `DATABASE_URL` in `.env`
- Ensure PostgreSQL is running
- Verify credentials

**Supabase authentication errors**:
- Check `SUPABASE_URL` and keys in `.env`
- Ensure Supabase instance is accessible
- Verify `skip_nonce_check = true` for Google OAuth

### iOS Issues

**Build errors**:
```bash
# Clean build folder
rm -rf ~/Library/Developer/Xcode/DerivedData/
```

**Can't connect to backend**:
- For simulator: Use `http://localhost:8000`
- For device: Use your local IP (e.g., `http://192.168.1.100:8000`)
- Check firewall settings

**Google Sign-In not working**:
- Verify `REVERSED_CLIENT_ID` in `Info.plist`
- Check URL schemes are configured
- Ensure Google Cloud Console OAuth credentials are correct
