"""OAuth 2.0 installed-app helper for Google integrations.

Implements the standard "installed application" flow described at
https://developers.google.com/identity/protocols/oauth2/native-app:

    1. Open the consent URL in the user's browser.
    2. Run a short-lived HTTP server on ``http://localhost:<port>``.
    3. Capture the ``code`` query param when Google redirects back.
    4. Exchange the code for access + refresh tokens.
    5. Persist them to disk at a user-controlled path.
    6. Refresh on expiry.

This module ships with the SDK and is used by both the Gmail and Google
Calendar integrations under :mod:`agentkit.integrations.registry`.

What the SDK does NOT do: register a Google Cloud project for you. You
must create one (free), enable the API you want, and obtain a client
ID + client secret. Each integration's ``SETUP.md`` walks through this
once.
"""

from __future__ import annotations

import http.server
import json
import logging
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import httpx


logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Tokens are considered "expiring soon" this many seconds before their
# nominal expiry to avoid a race between check + use.
_REFRESH_BUFFER_SECONDS = 60


class OAuthError(RuntimeError):
    """Raised when the OAuth flow fails (missing creds, refresh failure,
    user denied consent, etc.)."""


@dataclass
class _Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    scopes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scopes"] = list(self.scopes)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_Tokens":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data["expires_at"]),
            scopes=tuple(data.get("scopes") or ()),
        )


class GoogleOAuthClient:
    """OAuth 2.0 installed-application flow for Google APIs.

    ``client_id`` and ``client_secret`` come from your Google Cloud OAuth
    consent screen; see each integration's SETUP.md.

    ``scopes`` declares the access you need; the user's consent screen
    shows them this list. Use the most restrictive scope possible
    (e.g. ``gmail.readonly`` rather than ``gmail.modify``).

    ``token_path`` is where refresh + access tokens are persisted. Treat
    the file like a secret: do not check it in.

    ``callback_port`` is the localhost port the helper listens on while
    capturing the auth code. Defaults to 0 (OS picks a free port).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        scopes: list[str] | tuple[str, ...],
        token_path: str | Path,
        callback_port: int = 0,
        open_browser: bool = True,
    ) -> None:
        if not client_id or not client_secret:
            raise OAuthError(
                "GoogleOAuthClient requires client_id and client_secret. "
                "See the integration's SETUP.md for the Google Cloud step."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = tuple(scopes)
        self.token_path = Path(token_path).expanduser()
        self.callback_port = callback_port
        self.open_browser = open_browser
        self._tokens: Optional[_Tokens] = None
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_authorized(self) -> None:
        """Ensure we have a valid access token, running the consent flow if not.

        Idempotent: subsequent calls are cheap.
        """
        if self._tokens is None:
            self._tokens = self._load_tokens()
        if self._tokens is None:
            self._tokens = await self._run_installed_flow()
            self._save_tokens(self._tokens)
        elif self._is_expiring(self._tokens):
            self._tokens = await self._refresh(self._tokens)
            self._save_tokens(self._tokens)

    async def access_token(self) -> str:
        """Return a currently-valid access token, refreshing if needed."""
        await self.ensure_authorized()
        assert self._tokens is not None
        return self._tokens.access_token

    async def authorized_headers(self) -> dict[str, str]:
        token = await self.access_token()
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_expiring(self, tokens: _Tokens) -> bool:
        return tokens.expires_at - time.time() < _REFRESH_BUFFER_SECONDS

    def _load_tokens(self) -> Optional[_Tokens]:
        if not self.token_path.exists():
            return None
        try:
            data = json.loads(self.token_path.read_text())
            return _Tokens.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load tokens from %s: %s", self.token_path, e)
            return None

    def _save_tokens(self, tokens: _Tokens) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(tokens.to_dict(), indent=2))
        # Best-effort chmod 0600 so the file isn't world-readable.
        try:
            self.token_path.chmod(0o600)
        except OSError:
            pass

    async def _run_installed_flow(self) -> _Tokens:
        """Run the localhost-callback consent flow."""
        state = secrets.token_urlsafe(24)
        code, redirect_uri = _capture_auth_code(
            client_id=self.client_id,
            scopes=self.scopes,
            state=state,
            port=self.callback_port,
            open_browser=self.open_browser,
        )
        return await self._exchange_code(code, redirect_uri)

    async def _exchange_code(self, code: str, redirect_uri: str) -> _Tokens:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if resp.status_code != 200:
                raise OAuthError(
                    f"Token exchange failed ({resp.status_code}): {resp.text}"
                )
            payload = resp.json()
        return _tokens_from_payload(payload, fallback_scopes=self.scopes)

    async def _refresh(self, tokens: _Tokens) -> _Tokens:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "refresh_token": tokens.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code != 200:
                raise OAuthError(
                    f"Token refresh failed ({resp.status_code}): {resp.text}"
                )
            payload = resp.json()
        # Refresh responses don't always echo refresh_token; preserve the old.
        payload.setdefault("refresh_token", tokens.refresh_token)
        return _tokens_from_payload(payload, fallback_scopes=tokens.scopes)


def _tokens_from_payload(
    payload: dict[str, Any],
    fallback_scopes: tuple[str, ...],
) -> _Tokens:
    expires_in = float(payload.get("expires_in", 3600))
    scope_str = payload.get("scope")
    scopes = tuple(scope_str.split()) if scope_str else fallback_scopes
    return _Tokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=time.time() + expires_in,
        scopes=scopes,
    )


def _capture_auth_code(
    *,
    client_id: str,
    scopes: tuple[str, ...],
    state: str,
    port: int,
    open_browser: bool,
) -> tuple[str, str]:
    """Spin up a localhost server, open the consent URL, capture the code.

    Returns ``(code, redirect_uri)``. The redirect_uri must be passed back
    to the token endpoint or the exchange will fail.
    """
    received: dict[str, str] = {}
    server_ready = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        # Silence default per-request logging to stderr; we surface our own.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            parsed = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            if params.get("state") != state:
                self._reply(400, "<h1>State mismatch -- aborting.</h1>")
                received["error"] = "state_mismatch"
                return
            if "error" in params:
                self._reply(400, f"<h1>Consent denied: {params['error']}</h1>")
                received["error"] = params["error"]
                return
            if "code" not in params:
                self._reply(400, "<h1>No code in callback.</h1>")
                received["error"] = "no_code"
                return
            received["code"] = params["code"]
            self._reply(
                200,
                "<h1>agentkit: consent captured. You can close this tab.</h1>",
            )

        def _reply(self, status: int, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    actual_port = httpd.server_address[1]
    redirect_uri = f"http://127.0.0.1:{actual_port}/oauth/callback"

    def serve() -> None:
        server_ready.set()
        # Handle exactly one request, then shut down.
        httpd.handle_request()
        httpd.server_close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    server_ready.wait()

    auth_url = _build_auth_url(client_id, scopes, state, redirect_uri)
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass
    print(f"Open this URL to authorize agentkit:\n  {auth_url}\n")

    # Block until the handler runs (the server thread services one request).
    thread.join(timeout=300)
    if thread.is_alive():
        httpd.shutdown()
        raise OAuthError("OAuth consent timed out after 5 minutes.")

    if "error" in received:
        raise OAuthError(f"OAuth consent failed: {received['error']}")
    if "code" not in received:
        raise OAuthError("OAuth flow ended without a code.")
    return received["code"], redirect_uri


def _build_auth_url(
    client_id: str,
    scopes: tuple[str, ...],
    state: str,
    redirect_uri: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        # Force refresh-token issuance so the user doesn't have to re-consent
        # after the first access token expires.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
