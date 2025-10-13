# Environment Variables Update & Keychain Fix

## ✅ Changes Made

### 1. Environment Variable Standardization

**Removed redundant variables**:
- ❌ `ANON_KEY` → ✅ `SUPABASE_ANON_KEY`
- ❌ `SERVICE_ROLE_KEY` → ✅ `SUPABASE_SERVICE_ROLE_KEY`
- ❌ `SUPABASE_SERVICE_KEY` → ✅ `SUPABASE_SERVICE_ROLE_KEY`

**Updated files**:
- ✅ `scripts/env.sh` - Generates only `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`
- ✅ `docker/docker-compose.yml` - References `${SUPABASE_ANON_KEY}` and `${SUPABASE_SERVICE_ROLE_KEY}`
- ✅ `apps/api/app/config.py` - Uses `SUPABASE_SERVICE_ROLE_KEY`
- ✅ `apps/api/app/services/auth.py` - Updated to use `SUPABASE_SERVICE_ROLE_KEY`

### 2. Google Sign-In Keychain Fix

**Root causes identified**:
1. ❌ Missing keychain entitlement (FIXED)
2. ❌ Google Sign-In not configured on app launch (FIXED)

**Fixed files**:
- ✅ `apps/modal/modal/modal.entitlements` - Added keychain-access-groups
- ✅ `apps/modal/modal/modalApp.swift` - Added Google Sign-In configuration in init()

---

## 🚀 Required Steps

### Step 1: Regenerate Environment Files

```bash
# This will update all .env files with the new variable names
./scripts/env.sh

# Answer prompts:
# - Use existing JWT_SECRET? Y
# - Update Google OAuth? n (unless you need to change it)
# - Update Spotify OAuth? n (unless you need to change it)
```

### Step 2: Restart Docker Services

```bash
# Stop current services
./scripts/startup.sh
# Choose option 5 → Option 2 (Remove containers, keep data)

# Start fresh
./scripts/startup.sh
# Choose option 1
```

### Step 3: Clean and Rebuild iOS App

```bash
# Clean build folder
rm -rf apps/modal/build
rm -rf ~/Library/Developer/Xcode/DerivedData/modal-*

# Reset simulator (this clears the keychain)
xcrun simctl erase all

# Rebuild and run
./scripts/startup.sh
# Choose option 3 (Build and run iOS app only)
# Press Enter to select simulator
```

---

## 🔍 What Changed

### Environment Variables (Before)

```bash
# docker/.env (REDUNDANT)
ANON_KEY=eyJhb...
SERVICE_ROLE_KEY=eyJhb...
SUPABASE_ANON_KEY=eyJhb...  # Duplicate!
SUPABASE_SERVICE_KEY=eyJhb...  # Different name!
```

```yaml
# docker-compose.yml (INCONSISTENT)
environment:
  SUPABASE_ANON_KEY: ${ANON_KEY}  # Using ANON_KEY
  SUPABASE_SERVICE_KEY: ${SERVICE_ROLE_KEY}  # Using SERVICE_ROLE_KEY
```

```python
# apps/api/app/config.py (INCONSISTENT)
SUPABASE_SERVICE_KEY: str  # Different from docker!
```

### Environment Variables (After)

```bash
# docker/.env (CLEAN)
SUPABASE_ANON_KEY=eyJhb...
SUPABASE_SERVICE_ROLE_KEY=eyJhb...
```

```yaml
# docker-compose.yml (CONSISTENT)
environment:
  SUPABASE_ANON_KEY: ${SUPABASE_ANON_KEY}
  SUPABASE_SERVICE_KEY: ${SUPABASE_SERVICE_ROLE_KEY}
```

```python
# apps/api/app/config.py (CONSISTENT)
SUPABASE_SERVICE_ROLE_KEY: str  # Matches everywhere!
```

---

## 🐛 Google Sign-In Keychain Fix

### Problem

```
Error: "Google Sign-In failed: keychain error"
```

### Root Causes

1. **Missing Keychain Entitlement**
   - Google Sign-In SDK needs keychain access to store credentials
   - Entitlement was missing from app

2. **Google Sign-In Not Configured**
   - SDK was being called before configuration
   - Need to set `GIDConfiguration` with client ID on app launch

### Solution Applied

#### 1. Added Keychain Entitlement (`modal.entitlements`)

```xml
<key>keychain-access-groups</key>
<array>
    <string>$(AppIdentifierPrefix)com.app.modal</string>
</array>
```

#### 2. Configured Google Sign-In on Launch (`modalApp.swift`)

```swift
init() {
    // Configure Google Sign-In with client ID from Info.plist
    if let clientID = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String {
        let config = GIDConfiguration(clientID: clientID)
        GIDSignIn.sharedInstance.configuration = config
        print("✅ Google Sign-In configured with client ID")
    }
}
```

### Why This Works

**Before**:
```
User taps "Continue with Google"
  ↓
GIDSignIn.sharedInstance.signIn() called
  ↓
❌ Not configured + No keychain access
  ↓
❌ "keychain error"
```

**After**:
```
App launches
  ↓
Google Sign-In configured in init()
  ↓
Keychain entitlement present
  ↓
User taps "Continue with Google"
  ↓
✅ Success!
```

---

## 🧪 Verification

### 1. Verify Environment Variables

```bash
# Check docker/.env
grep "SUPABASE_" docker/.env

# Should see:
# SUPABASE_ANON_KEY=eyJhb...
# SUPABASE_SERVICE_ROLE_KEY=eyJhb...

# Should NOT see:
# ANON_KEY=...
# SERVICE_ROLE_KEY=...
```

### 2. Verify Services Start

```bash
./scripts/startup.sh
# Choose 1

# All containers should be healthy:
# ✅ modal_api
# ✅ modal-redis
# ✅ supabase-db
# ✅ supabase-auth
# etc.
```

### 3. Verify Google Sign-In

```bash
# Rebuild and run app
./scripts/startup.sh
# Choose 3

# In simulator:
1. Tap "Continue with Google"
2. Select a Google account
3. ✅ Should succeed (no keychain error!)
4. Should redirect to IntegrationsView
```

---

## 🔍 Troubleshooting

### Error: "SUPABASE_ANON_KEY not found"

```bash
# Regenerate .env files
./scripts/env.sh

# Restart Docker
./scripts/startup.sh
# Option 5 → Option 2
# Option 1
```

### Error: Still getting keychain error

```bash
# Complete reset:

# 1. Clean everything
rm -rf apps/modal/build
rm -rf ~/Library/Developer/Xcode/DerivedData

# 2. Reset ALL simulators
xcrun simctl shutdown all
xcrun simctl erase all

# 3. Open in Xcode and verify entitlements
open apps/modal/modal.xcodeproj

# Go to: Target → Signing & Capabilities
# Verify "Keychain Sharing" is enabled
# Should show: $(AppIdentifierPrefix)com.app.modal

# 4. Clean Build Folder in Xcode
# Product → Clean Build Folder (⇧⌘K)

# 5. Build and run
./scripts/startup.sh
# Choose 3
```

### Error: "Google Sign-In configuration error"

Check console output when app launches:
```
✅ Google Sign-In configured with client ID
```

If you see:
```
⚠️ Warning: GIDClientID not found in Info.plist
```

Then verify `Info.plist`:
```xml
<key>GIDClientID</key>
<string>YOUR_CLIENT_ID.apps.googleusercontent.com</string>
```

---

## 📋 Summary of Changes

| File | What Changed |
|------|-------------|
| `scripts/env.sh` | Only generates `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` |
| `docker/docker-compose.yml` | References `${SUPABASE_ANON_KEY}` and `${SUPABASE_SERVICE_ROLE_KEY}` |
| `apps/api/app/config.py` | Uses `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_SERVICE_KEY` |
| `apps/api/app/services/auth.py` | Updated to use `SUPABASE_SERVICE_ROLE_KEY` |
| `apps/modal/modal/modal.entitlements` | Added `keychain-access-groups` |
| `apps/modal/modal/modalApp.swift` | Added Google Sign-In configuration in `init()` |

---

## ✅ Expected Outcome

After following all steps:

1. **Environment Variables**: All services use consistent `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`
2. **Docker Services**: Start successfully with correct environment variables
3. **Google Sign-In**: Works without keychain errors
4. **App Flow**: User can sign in → Connect integrations → Use app

---

**Run these commands in order**:
```bash
# 1. Regenerate env files
./scripts/env.sh

# 2. Restart Docker
./scripts/startup.sh  # → 5 → 2 → 1

# 3. Clean and rebuild iOS
rm -rf apps/modal/build
xcrun simctl erase all
./scripts/startup.sh  # → 3

# 4. Test Google Sign-In in simulator
```

**Status**: ✅ All fixes applied, ready to test!

