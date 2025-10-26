

# Tunneling Guide

How to use tools like ngrok, zrok, etc. to test the iOS app on another device.

## iOS App URLs

Since your tunnel `https://t-rh4czluc.tunn.dev` is forwarding both ports (8000 for Supabase and 8080 for your API), you need to understand how your tunnel routes traffic:

**If the tunnel forwards port 8080 to the API:**

```
// API Configuration (using tunnel)
API_BASE_URL = https:/$()/t-rh4czluc.tunn.dev/api/v1
WEBSOCKET_URL = wss:/$()/t-rh4czluc.tunn.dev/api/v1

// Supabase Configuration (using tunnel - port 8000)
SUPABASE_URL = https:/$()/t-rh4czluc.tunn.dev
SUPABASE_ANON_KEY = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJvbGUiOiJhbm9uIiwiaWF0IjoxNzYxNDU3MTMwLCJleHAiOjQxMDI0NDQ4MDB9.IbhbE_RZibzMyWErtiGYn5DVmawUODGpCanqHEoosbc

```

> **Note:**
>
> -   Use `https://` instead of `http://` (tunnel provides SSL)
> -   Use `wss://` instead of `ws://` for WebSocket (secure WebSocket)
> -   You'll need to clarify with your tunnel provider how it routes to different ports (8000 vs 8080)

Backend Configuration
---------------------

### API Environment

Update the following variables:

```
# API Configuration
API_EXTERNAL_URL=https://t-rh4czluc.tunn.dev

# OAuth - Google (redirect must match Google Console configuration)
GOOGLE_REDIRECT_URI=https://t-rh4czluc.tunn.dev/auth/v1/callback

# Gmail OAuth
GMAIL_REDIRECT_URI=https://t-rh4czluc.tunn.dev/api/v1/integrations/gmail/callback

```

### Supabase Environment

Update the following variables:

```
# Supabase Configuration
API_EXTERNAL_URL=https://t-rh4czluc.tunn.dev

# GoTrue OAuth Configuration - Google
GOTRUE_GOOGLE_REDIRECT_URI=https://t-rh4czluc.tunn.dev/auth/v1/callback

```

Important Considerations
------------------------

### **Port Routing with Tunnel**

You need to understand how your tunnel `t-rh4czluc.tunn.dev` handles multiple ports:

**Option A: Single tunnel for port 8000 (Supabase/Kong)**

-   Kong proxies to your API internally
-   All traffic goes through `https://t-rh4czluc.tunn.dev`
-   Kong routes `/api/v1/*` to your FastAPI backend

**Option B: Separate tunnels/paths for each port**

-   `https://t-rh4czluc.tunn.dev` → port 8000 (Supabase)
-   You might need a different URL or path for port 8080 (API)

### **OAuth Redirect URIs**

> **Note:** You **MUST** update your Google Cloud Console with the new redirect URI:
>
> 1.  Go to [Google Cloud Console](https://console.cloud.google.com/)
> 2.  Navigate to APIs & Services → Credentials
> 3.  Find your OAuth 2.0 Client ID
> 4.  Add to **Authorized redirect URIs**: `https://t-rh4czluc.tunn.dev/auth/v1/callback`

### **Recommended Approach**

Since Kong (port 8000) acts as an API gateway, you should route ALL traffic through port 8000:

```
// Use tunnel for all services (Kong routes to API internally)
API_BASE_URL = https:/$()/t-rh4czluc.tunn.dev/api/v1
WEBSOCKET_URL = wss:/$()/t-rh4czluc.tunn.dev/api/v1
SUPABASE_URL = https:/$()/t-rh4czluc.tunn.dev
```
