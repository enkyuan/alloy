"""Tests for the Google OAuth installed-app helper.

The localhost-callback consent flow is interactive (opens a browser) and
not exercised here. We test the parts that ARE deterministic:

- token persistence to disk
- "fresh tokens" path
- expiring-token detection
- refresh exchange
- error surfaces (missing creds, refresh failure)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from agentkit.integrations.oauth import (
    GoogleOAuthClient,
    OAuthError,
    _Tokens,
)


def _write_tokens(path: Path, **overrides) -> None:
    base = {
        "access_token": "valid-access",
        "refresh_token": "valid-refresh",
        "expires_at": time.time() + 3600,
        "scopes": ["scope/a"],
    }
    base.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(base))


def _client(tmp_path: Path, **overrides) -> GoogleOAuthClient:
    defaults = {
        "client_id": "cid",
        "client_secret": "csec",
        "scopes": ["scope/a"],
        "token_path": tmp_path / "tokens.json",
        "open_browser": False,
    }
    defaults.update(overrides)
    return GoogleOAuthClient(**defaults)


def test_requires_client_id_and_secret(tmp_path: Path) -> None:
    with pytest.raises(OAuthError, match="client_id and client_secret"):
        GoogleOAuthClient(
            client_id="",
            client_secret="csec",
            scopes=["a"],
            token_path=tmp_path / "t.json",
        )


@pytest.mark.asyncio
async def test_loads_existing_tokens_when_fresh(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    _write_tokens(tokens_path)
    client = _client(tmp_path, token_path=tokens_path)
    token = await client.access_token()
    assert token == "valid-access"


@pytest.mark.asyncio
async def test_authorized_headers_carries_bearer(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    _write_tokens(tokens_path)
    client = _client(tmp_path, token_path=tokens_path)
    headers = await client.authorized_headers()
    assert headers["Authorization"] == "Bearer valid-access"


@pytest.mark.asyncio
async def test_refreshes_when_token_is_expiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens_path = tmp_path / "tokens.json"
    _write_tokens(tokens_path, expires_at=time.time() - 1, access_token="old-access")

    refreshed_payload = {
        "access_token": "new-access",
        # Google's refresh response may or may not include refresh_token; this
        # test omits it to confirm the helper preserves the existing one.
        "expires_in": 3600,
        "scope": "scope/a",
    }

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://oauth2.googleapis.com/token"
        body = dict(httpx.QueryParams(request.content.decode()))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "valid-refresh"
        return httpx.Response(200, json=refreshed_payload)

    # Patch the AsyncClient constructor used inside _refresh.
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(transport))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = _client(tmp_path, token_path=tokens_path)
    token = await client.access_token()
    assert token == "new-access"

    # Refresh-token was preserved (not echoed by Google in this response).
    saved = json.loads(tokens_path.read_text())
    assert saved["refresh_token"] == "valid-refresh"
    assert saved["access_token"] == "new-access"


@pytest.mark.asyncio
async def test_refresh_failure_raises_oauth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens_path = tmp_path / "tokens.json"
    _write_tokens(tokens_path, expires_at=time.time() - 1)

    def transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error":"invalid_grant"}')

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(transport))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    client = _client(tmp_path, token_path=tokens_path)
    with pytest.raises(OAuthError, match="Token refresh failed"):
        await client.access_token()


def test_corrupt_token_file_is_ignored(tmp_path: Path) -> None:
    """A malformed tokens file should not crash the helper at load time;
    the next call to ensure_authorized just re-runs the consent flow."""
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text("not json")
    # Just confirm the load returns None rather than raising.
    client = _client(tmp_path, token_path=tokens_path)
    assert client._load_tokens() is None  # type: ignore[attr-defined]


def test_tokens_persist_chmod_0600(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    client = _client(tmp_path, token_path=tokens_path)
    tok = _Tokens(
        access_token="a", refresh_token="r", expires_at=time.time() + 3600, scopes=("s",)
    )
    client._save_tokens(tok)  # type: ignore[attr-defined]
    mode = tokens_path.stat().st_mode & 0o777
    # Best-effort permission setting; on platforms where chmod is a noop
    # this assertion would be too strict, but darwin / linux honor it.
    assert mode == 0o600
