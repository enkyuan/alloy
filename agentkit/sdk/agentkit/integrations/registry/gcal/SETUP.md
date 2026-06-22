# Google Calendar integration setup

Same OAuth 2.0 installed-app flow as the Gmail integration. If you've
already done the Google Cloud project + consent screen + OAuth client
setup for Gmail, you can reuse the same client ID + secret -- just enable
the Calendar API and add the calendar scope to the consent screen.

## 1. Enable the Google Calendar API

1. https://console.cloud.google.com/
2. Pick your existing project (or create one).
3. APIs & Services -> Library -> "Google Calendar API" -> Enable.

## 2. OAuth consent screen

If you set this up for Gmail, just add the calendar scope:

- Scopes -> add `https://www.googleapis.com/auth/calendar.readonly`.

If this is your first Google integration, follow the Gmail SETUP.md
"OAuth consent screen" section first.

## 3. OAuth client

Reuse the same Desktop-app OAuth client ID + secret you used for Gmail.

```bash
export GOOGLE_OAUTH_CLIENT_ID=...
export GOOGLE_OAUTH_CLIENT_SECRET=...
```

Note: tokens persist to `~/.agentkit/gcal.json` by default -- a separate
file from Gmail because the scopes differ.

## What this integration can see

- Read-only access to the authorized account's calendars.
- No create, modify, or delete; the scope explicitly excludes those.
