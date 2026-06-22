# Gmail integration setup

This integration uses Google's OAuth 2.0 installed-app flow. You only do
this once.

## 1. Create a Google Cloud project (free)

1. Go to https://console.cloud.google.com/
2. Create a new project (any name).
3. Enable the **Gmail API**: APIs & Services -> Library -> search "Gmail
   API" -> Enable.

## 2. Configure the OAuth consent screen

1. APIs & Services -> OAuth consent screen.
2. User type: **External**.
3. Fill in the required fields (app name, support email).
4. Scopes: add `https://www.googleapis.com/auth/gmail.readonly`.
5. Test users: add your Google account email.

While your app is in "Testing" mode (the default), only test users you
list can authorize it. That's fine for personal automation.

## 3. Create an OAuth client

1. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID.
2. Application type: **Desktop app**.
3. Note the **Client ID** and **Client secret**.

## 4. Wire it up

```bash
export GOOGLE_OAUTH_CLIENT_ID=...
export GOOGLE_OAUTH_CLIENT_SECRET=...
```

Run your agent. The first call opens your browser to Google's consent
screen. After you approve, tokens are saved to
`~/.agentkit/gmail.json` (override with `token_path=` in code).

## What this integration can see

- Read-only access to the authorized account's Gmail.
- No send, modify, or delete -- the scope explicitly excludes those.
- The agent sees message metadata, snippets, and (on `get_message`) full
  payloads.
