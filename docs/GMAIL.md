# Gmail Integration

Complete guide for Gmail integration in the Modal app. The app supports two methods: automatic integration via Google Sign-In (recommended) and manual OAuth flow.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [How It Works](#how-it-works)
3. [Automatic Integration (Recommended)](#automatic-integration-recommended)
4. [Manual OAuth Setup](#manual-oauth-setup)
5. [Implementation Details](#implementation-details)
6. [Using Gmail API](#using-gmail-api)
7. [Testing](#testing)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start

### For Users

**If you sign in with Google:**
1. Tap "Sign in with Google"
2. Grant Gmail permissions when prompted
3. ✅ Done! Gmail is automatically connected

**If you want to connect Gmail separately:**
1. Go to Settings > Integrations
2. Tap Gmail
3. Complete OAuth flow
4. ✅ Done! Gmail connected

### For Developers

**Automatic integration** requires no additional setup - it just works when users sign in with Google!

**Manual OAuth** (optional) requires Google Cloud credentials:
1. Follow [Manual OAuth Setup](#manual-oauth-setup) below
2. Add credentials to backend `.env`
3. Restart backend

---

## How It Works

### Two Integration Methods

#### 1. Automatic (via Google Sign-In)
```
User signs in with Google
    ↓
Grants Gmail permissions
    ↓
App receives access token
    ↓
Token synced to backend
    ↓
✅ Gmail connected automatically
```

#### 2. Manual (via Settings)
```
User goes to Settings > Integrations
    ↓
Taps Gmail
    ↓
OAuth popup opens
    ↓
Grants permissions
    ↓
Token exchanged and stored
    ↓
✅ Gmail connected
```

---

## Automatic Integration (Recommended)

### Overview

When you sign in with Google, the app automatically requests Gmail permissions. No separate OAuth flow needed!

### What Gets Requested

The app requests these Gmail scopes during Google Sign-In:

- `https://www.googleapis.com/auth/gmail.readonly` - Read emails
- `https://www.googleapis.com/auth/gmail.send` - Send emails
- `https://www.googleapis.com/auth/gmail.modify` - Mark as read/unread, archive, etc.

### First Sign-In Experience

1. **Google consent screen** shows:
   - "Modal wants to access your Google Account"
   - "See, edit, create, and delete email in Gmail"
   - "Send email on your behalf"

2. After granting permissions:
   - You're signed into the app
   - Gmail is automatically connected
   - Ready to use email features

### How the Flow Works

**iOS Side:**
```swift
// In OnboardingView.swift
let additionalScopes = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify"
]

GIDSignIn.sharedInstance.signIn(
    withPresenting: rootViewController,
    hint: nil,
    additionalScopes: additionalScopes
)

// Get both ID token and access token
let idToken = result.user.idToken?.tokenString
let accessToken = result.user.accessToken.tokenString

// Authenticate with both tokens
try await authService.authenticateWithGoogle(
    idToken: idToken,
    accessToken: accessToken
)
```

**Backend Side:**
```python
# Endpoint: POST /api/v1/integrations/gmail/sync
# Receives Google access token from iOS
# Verifies with Gmail API
# Stores in database
```

### Token Management

**Access Token Lifespan:**
- Google Sign-In tokens expire after ~1 hour
- No refresh token provided (by design)
- App automatically refreshes on next launch via `restorePreviousSignIn`

**Silent Refresh:**
```swift
// In modalApp.swift - runs on launch
GIDSignIn.sharedInstance.restorePreviousSignIn { user, error in
    if let user = user {
        // Fresh token automatically obtained
        let accessToken = user.accessToken.tokenString
        // Sync to backend
    }
}
```

### Advantages

✅ One-step setup for users
✅ Seamless UX - no separate flow
✅ No additional OAuth configuration
✅ Automatic token refresh on app launch

### Limitations

⚠️ Tokens expire after 1 hour
⚠️ No long-lived refresh token
⚠️ Requires user to use Google Sign-In

---

## Manual OAuth Setup

Use this method for users who don't sign in with Google, or when you need long-lived access with refresh tokens.

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Name it "Modal App"

### Step 2: Enable Gmail API

1. Go to **APIs & Services** > **Library**
2. Search for "Gmail API"
3. Click and press **Enable**

### Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Select **External** (unless you have Google Workspace)
3. Fill in required fields:
   - **App name**: Modal
   - **User support email**: Your email
   - **Developer contact**: Your email
4. Click **Save and Continue**
5. On **Scopes** page, click **Add or Remove Scopes**
6. Add these scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/userinfo.email`
7. Click **Save and Continue**
8. On **Test users**, add your Gmail address
9. Click **Save and Continue**

### Step 4: Create OAuth Credentials

**For iOS (optional):**
1. Click **+ Create Credentials** > **OAuth client ID**
2. Select **iOS**
3. Fill in:
   - **Name**: Modal iOS App
   - **Bundle ID**: `com.enkyuan.modal`
4. Click **Create**
5. Save the **Client ID**

**For Backend (required):**
1. Click **+ Create Credentials** > **OAuth client ID**
2. Select **Web application**
3. Fill in:
   - **Name**: Modal Backend
   - **Authorized redirect URIs**: 
     - `modal://gmail/callback`
     - `http://localhost:8080/api/v1/integrations/gmail/callback` (for testing)
4. Click **Create**
5. Save both **Client ID** and **Client Secret**

### Step 5: Configure Backend

Add to your backend `.env` file:

```bash
# Gmail OAuth (for manual flow)
GMAIL_CLIENT_ID=your_web_client_id.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=your_client_secret_here
GMAIL_REDIRECT_URI=modal://gmail/callback
```

### Step 6: Restart Backend

```bash
cd /Users/enkyuan/Desktop/Projects/modal/docker
docker compose restart api
```

Or use the startup script:

```bash
cd /Users/enkyuan/Desktop/Projects/modal
./scripts/startup.sh
```

### Step 7: Test Manual Flow

1. Build and run iOS app
2. Go to **Settings** > **Integrations**
3. Tap **Gmail**
4. OAuth popup should open
5. Sign in and grant permissions
6. Redirected back to app
7. Gmail shows as "Connected"

### Advantages

✅ Works without Google Sign-In
✅ Long-lived access with refresh tokens
✅ Token automatically refreshed by backend
✅ Can connect different Gmail account

### Limitations

⚠️ Requires Google Cloud setup
⚠️ Requires backend configuration
⚠️ More steps for users

---

## Implementation Details

### Backend Components

#### 1. Gmail Service (`apps/api/app/services/gmail.py`)

Complete Gmail API wrapper:

```python
from app.services.gmail import get_gmail_service

# Initialize with access token
gmail = get_gmail_service(access_token, refresh_token)

# Send email
gmail.send_email(
    to="friend@example.com",
    subject="Hello!",
    body="Message from Modal"
)

# Get messages
messages = gmail.get_messages(max_results=10, query="is:unread")

# Get message detail
message = gmail.get_message_detail(message_id)

# Get unread count
count = gmail.get_unread_count()

# Mark as read
gmail.mark_as_read(message_id)

# Get profile
profile = gmail.get_profile()  # Returns email address
```

#### 2. API Endpoints (`apps/api/app/routers/integrations.py`)

**Automatic Integration:**
- `POST /integrations/gmail/sync` - Sync from Google Sign-In

**Manual OAuth:**
- `GET /integrations/gmail/auth` - Get OAuth authorization URL
- `POST /integrations/gmail/exchange` - Exchange code for token

**Common:**
- `POST /integrations/gmail/disconnect` - Disconnect and revoke access

#### 3. Configuration (`apps/api/app/config.py`)

```python
# Gmail OAuth (optional - only for manual flow)
GMAIL_CLIENT_ID: Optional[str] = None
GMAIL_CLIENT_SECRET: Optional[str] = None
GMAIL_REDIRECT_URI: str = "modal://gmail/callback"
```

#### 4. Dependencies (`apps/api/pyproject.toml`)

```toml
google-api-python-client = ">=2.108.0,<3.0.0"
google-auth = ">=2.25.0,<3.0.0"
google-auth-oauthlib = ">=1.2.0,<2.0.0"
google-auth-httplib2 = ">=0.2.0,<1.0.0"
```

### iOS Components

#### 1. IntegrationService (`apps/modal/modal/Services/IntegrationService.swift`)

Already configured with Gmail support:

```swift
enum ServiceType: String {
    case gmail
    // ...
}

// Check if connected
integrationService.isConnected(.gmail)

// Connect manually
try await integrationService.connectService(.gmail, authService: authService)

// Disconnect
try await integrationService.disconnectService(.gmail, authService: authService)
```

#### 2. AuthenticationService (`apps/modal/modal/Services/AuthenticationService.swift`)

Automatic Gmail sync:

```swift
func authenticateWithGoogle(idToken: String, accessToken: String?) async throws {
    // Authenticate with Supabase
    // ...
    
    // Sync Gmail if access token provided
    if let accessToken = accessToken {
        await syncGmailIntegration(accessToken: accessToken)
    }
}
```

#### 3. URL Scheme (Info.plist)

Already configured:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>modal</string>
        </array>
    </dict>
</array>
```

Handles: `modal://gmail/callback`

### Database Schema

The `integrations` table stores Gmail connections:

```sql
{
  id: UUID,
  user_id: UUID,
  service: 'gmail',
  access_token: ENCRYPTED,
  refresh_token: ENCRYPTED (nullable),
  token_expires_at: TIMESTAMP,
  is_active: BOOLEAN,
  metadata: {
    email: 'user@gmail.com',
    source: 'google_signin' | 'oauth'
  },
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP
}
```

---

## Using Gmail API

### Available Methods

Once Gmail is connected, you can use these operations:

#### Send Email

```python
gmail_service.send_email(
    to="recipient@example.com",
    subject="Meeting Tomorrow",
    body="Don't forget our meeting at 3 PM!",
    from_email="me@gmail.com"  # Optional
)
```

#### Get Messages

```python
# Get latest 10 messages
messages = gmail_service.get_messages(max_results=10)

# Get unread messages
unread = gmail_service.get_messages(
    query="is:unread",
    label_ids=["INBOX"]
)

# Search messages
search_results = gmail_service.get_messages(
    query="from:boss@company.com subject:urgent"
)
```

#### Get Message Details

```python
message = gmail_service.get_message_detail(message_id)
# Returns full message with headers and body
```

#### Get Unread Count

```python
count = gmail_service.get_unread_count()
print(f"You have {count} unread messages")
```

#### Mark as Read

```python
gmail_service.mark_as_read(message_id)
```

#### Get User Profile

```python
profile = gmail_service.get_profile()
email = profile.get("emailAddress")
```

### Gmail Scopes

The integration uses these scopes:

- **gmail.readonly** - Read all emails
- **gmail.send** - Send emails
- **gmail.modify** - Mark as read/unread, archive, delete
- **userinfo.email** - Get user's email address

---

## Testing

### Test Automatic Integration

1. **Clean slate:**
   ```bash
   # In Xcode: Device → Erase All Content and Settings
   ```

2. **Sign in with Google:**
   - Watch for Gmail scopes in consent screen
   - Check console: `"✅ Granted scopes: ..."`

3. **Verify backend sync:**
   ```bash
   docker logs modal-api | grep -i gmail
   # Should see: "Successfully synced Gmail integration"
   ```

4. **Check integration status:**
   - Go to Settings > Integrations
   - Gmail should show as "Connected"

### Test Manual OAuth

1. **Prerequisites:**
   - Google Cloud credentials configured
   - `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` set in backend

2. **Connect:**
   - Go to Settings > Integrations
   - Tap Gmail
   - OAuth popup should open
   - Grant permissions
   - Verify connection

### Test Backend Endpoints

**Get OAuth URL:**
```bash
curl -X GET http://localhost:8080/api/v1/integrations/gmail/auth \
  -H "Authorization: Bearer $SUPABASE_TOKEN"
```

**Sync from Google Sign-In:**
```bash
curl -X POST http://localhost:8080/api/v1/integrations/gmail/sync \
  -H "Authorization: Bearer $SUPABASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"access_token\": \"$GOOGLE_ACCESS_TOKEN\"}"
```

**Disconnect:**
```bash
curl -X POST http://localhost:8080/api/v1/integrations/gmail/disconnect \
  -H "Authorization: Bearer $SUPABASE_TOKEN"
```

---

## Troubleshooting

### Gmail Not Showing as Connected

**Symptoms:**
- Signed in with Google
- Granted permissions
- But Gmail shows as "Not Connected"

**Check:**
1. Console logs for `"✅ Granted scopes"`
2. Backend logs: `docker logs modal-api | grep gmail`
3. Database: Query `integrations` table for `service='gmail'`

**Fix:**
- Sign out and sign in again
- Make sure you grant Gmail permissions in consent screen
- Check backend is running: `docker ps`

### "Invalid or Insufficient Gmail Access Token"

**Cause:** Access token expired (1 hour lifetime for Google Sign-In tokens)

**Fix:**
- App automatically refreshes on restart
- Or sign in again to get fresh token

### Manual OAuth Not Working

**Symptoms:**
- Tap Gmail in Settings
- Nothing happens or error occurs

**Check:**
1. `GMAIL_CLIENT_ID` set in backend `.env`
2. `GMAIL_CLIENT_SECRET` set in backend `.env`
3. Backend logs for errors
4. Redirect URI matches: `modal://gmail/callback`

**Fix:**
- Verify Google Cloud Console configuration
- Check authorized redirect URIs match exactly
- Restart backend after adding credentials

### "Access Blocked: This app's request is invalid"

**Cause:** OAuth consent screen not configured or user not added as test user

**Fix:**
1. Go to Google Cloud Console
2. Configure OAuth consent screen
3. Add your email as test user
4. Make sure all required scopes are added

### "redirect_uri_mismatch"

**Cause:** Redirect URI in request doesn't match Google Cloud Console configuration

**Fix:**
1. Check `GMAIL_REDIRECT_URI` in backend `.env`
2. Verify it matches Google Cloud Console > Credentials > Authorized redirect URIs
3. Should be exactly: `modal://gmail/callback`

### Tokens Expire Too Quickly

**For Automatic Integration:**
- Tokens expire after 1 hour (by design)
- App refreshes automatically on launch
- User may need to re-authenticate occasionally

**For Manual OAuth:**
- Use refresh tokens for long-lived access
- Backend automatically refreshes tokens
- No user interaction needed

---

## Comparison

| Feature | Automatic (Google Sign-In) | Manual OAuth |
|---------|----------------------------|--------------|
| **Setup Complexity** | None | Google Cloud configuration |
| **User Steps** | 1 (sign in) | 3 (sign in, go to settings, connect) |
| **Token Type** | Access token only | Access + refresh tokens |
| **Token Lifetime** | 1 hour | Long-lived with refresh |
| **Refresh** | Automatic on app launch | Automatic by backend |
| **Best For** | Seamless UX, testing | Production, different account |

---

## Security

- OAuth 2.0 standard
- CSRF protection via state parameter (manual flow)
- Access tokens stored encrypted in database
- Tokens scoped to Gmail API only
- User can revoke access anytime
- Automatic token expiration
- Token revocation on disconnect

---

## Summary

**You asked:** "If the user signs in with Google, can it just use that account?"

**Answer:** **YES!**

- Automatic Gmail integration via Google Sign-In
- No separate OAuth flow needed
- Just grant permissions once during sign-in
- Gmail access synced to backend automatically
- Works immediately after sign-in

**Both methods are fully implemented and ready to use:**
- ✅ Automatic integration (recommended for users)
- ✅ Manual OAuth (optional for flexibility)

Choose the method that best fits your needs!
