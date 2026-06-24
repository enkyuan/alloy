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

from kaji.integrations.oauth import (
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
        access_token="a",
        refresh_token="r",
        expires_at=time.time() + 3600,
        scopes=("s",),
    )
    client._save_tokens(tok)  # type: ignore[attr-defined]
    mode = tokens_path.stat().st_mode & 0o777
    # Best-effort permission setting; on platforms where chmod is a noop
    # this assertion would be too strict, but darwin / linux honor it.
    assert mode == 0o600


# ---------------------------------------------------------------------------
# TokenStorage protocol + backends
# ---------------------------------------------------------------------------


def test_file_token_storage_roundtrips(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage

    storage = FileTokenStorage(tmp_path / "tokens.json")
    payload = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_at": 1.0,
        "scopes": ["s"],
    }
    storage.save(payload)
    assert storage.load() == payload


def test_file_token_storage_returns_none_when_missing(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage

    storage = FileTokenStorage(tmp_path / "does_not_exist.json")
    assert storage.load() is None


def test_file_token_storage_writes_chmod_0600(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage

    path = tmp_path / "tokens.json"
    storage = FileTokenStorage(path)
    storage.save({"access_token": "a"})
    assert path.stat().st_mode & 0o777 == 0o600


def test_keyring_token_storage_uses_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    from kaji.integrations.oauth import KeyringTokenStorage

    fake_store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service: str, account: str, secret: str) -> None:
            fake_store[(service, account)] = secret

        @staticmethod
        def get_password(service: str, account: str):
            return fake_store.get((service, account))

    monkeypatch.setattr("kaji.integrations.oauth.keyring", FakeKeyring, raising=False)

    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    payload = {"access_token": "a", "refresh_token": "r", "expires_at": 1.0}
    storage.save(payload)
    assert storage.load() == payload


def test_keyring_token_storage_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.integrations.oauth import KeyringTokenStorage

    class FakeKeyring:
        @staticmethod
        def get_password(_service: str, _account: str):
            return None

    monkeypatch.setattr("kaji.integrations.oauth.keyring", FakeKeyring, raising=False)

    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    assert storage.load() is None


def test_keyring_token_storage_raises_clear_error_without_keyring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kaji.integrations.oauth import KeyringTokenStorage

    monkeypatch.setattr("kaji.integrations.oauth.keyring", None, raising=False)
    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    # Assert the exact install instruction so a refactor that shortens the
    # message degrades the test, not the user's stderr.
    msg_re = r"pip install 'kaji\[oauth-keyring\]'"
    with pytest.raises(OAuthError, match=msg_re):
        storage.save({"a": 1})
    with pytest.raises(OAuthError, match=msg_re):
        storage.load()


def test_keyring_token_storage_returns_none_on_corrupt_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt keyring entry triggers re-consent, matching the file
    backend's behaviour. Without the fix, json.JSONDecodeError escaped
    the storage and crashed ensure_authorized()."""
    from kaji.integrations.oauth import KeyringTokenStorage

    class CorruptKeyring:
        @staticmethod
        def get_password(_service: str, _account: str):
            return "{not json"

    monkeypatch.setattr(
        "kaji.integrations.oauth.keyring", CorruptKeyring, raising=False
    )

    storage = KeyringTokenStorage(service_name="kaji-test", account="gmail")
    assert storage.load() is None


def test_client_accepts_custom_token_storage(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage

    storage = FileTokenStorage(tmp_path / "tok.json")
    client = GoogleOAuthClient(
        client_id="id",
        client_secret="sec",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        token_path=tmp_path / "ignored.json",
        token_storage=storage,
    )
    assert client._token_storage is storage  # type: ignore[attr-defined]


def test_client_defaults_to_file_token_storage(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage

    client = _client(tmp_path)
    assert isinstance(client._token_storage, FileTokenStorage)  # type: ignore[attr-defined]


def test_client_requires_token_path_or_token_storage() -> None:
    """Omitting both backends is a config error: the helper has nowhere to
    persist tokens and would re-prompt on every call."""
    with pytest.raises(OAuthError, match=r"token_path.*token_storage"):
        GoogleOAuthClient(
            client_id="id",
            client_secret="sec",
            scopes=["s"],
        )


def test_client_accepts_token_storage_without_token_path(tmp_path: Path) -> None:
    """token_path is no longer required when an explicit token_storage is
    provided. The client should construct cleanly and route through the
    given storage."""
    from kaji.integrations.oauth import FileTokenStorage

    storage = FileTokenStorage(tmp_path / "via_storage.json")
    client = GoogleOAuthClient(
        client_id="id",
        client_secret="sec",
        scopes=["s"],
        token_storage=storage,
    )
    assert client.token_path is None
    assert client._token_storage is storage  # type: ignore[attr-defined]


def test_token_storage_protocol_is_runtime_checkable(tmp_path: Path) -> None:
    from kaji.integrations.oauth import FileTokenStorage, TokenStorage

    assert isinstance(FileTokenStorage(tmp_path / "x.json"), TokenStorage)


def test_client_round_trips_through_custom_storage(tmp_path: Path) -> None:
    """The client's _load_tokens / _save_tokens go through storage, not the
    legacy file path, when a token_storage is provided."""
    from kaji.integrations.oauth import FileTokenStorage

    storage_path = tmp_path / "via_storage.json"
    storage = FileTokenStorage(storage_path)
    client = GoogleOAuthClient(
        client_id="id",
        client_secret="sec",
        scopes=["s"],
        token_path=tmp_path / "legacy_path_should_not_be_used.json",
        token_storage=storage,
    )
    tok = _Tokens(
        access_token="a",
        refresh_token="r",
        expires_at=time.time() + 3600,
        scopes=("s",),
    )
    client._save_tokens(tok)  # type: ignore[attr-defined]
    assert storage_path.exists()
    assert not (tmp_path / "legacy_path_should_not_be_used.json").exists()
    loaded = client._load_tokens()  # type: ignore[attr-defined]
    assert loaded is not None and loaded.access_token == "a"
