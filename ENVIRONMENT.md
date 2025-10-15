# 🔐 Environment Setup

## Quick Start

Your iOS app now uses `.xcconfig` files for environment configuration (like `.env` for Swift).

### First Time Setup:

```bash
cd apps/modal
cp Config.xcconfig.example Config.xcconfig
# Edit Config.xcconfig with your values
```

### Link in Xcode:

1. Open `modal.xcodeproj`
2. Select project → Info tab → Configurations
3. Set `Config.xcconfig` for Debug and Release configurations

See `apps/modal/ENV_SETUP.md` for detailed instructions.

## ✅ What's Updated

All services now use `Environment` config instead of hardcoded URLs:

- `AuthenticationService.swift`
- `IntegrationService.swift`  
- `WebSocketSTTService.swift`
- `SpeechToTextService.swift`
- `SupabaseConfig.swift`

## 🔒 Security

- ✅ `Config.xcconfig` is in `.gitignore` (safe for secrets)
- ✅ `Config.xcconfig.example` is committed (template)
- ✅ No hardcoded URLs in code

## 📝 Current Variables

```
API_BASE_URL
WEBSOCKET_URL
SUPABASE_URL
SUPABASE_ANON_KEY
DEBUG_LOGGING
```

Update these in `apps/modal/Config.xcconfig` and rebuild.
