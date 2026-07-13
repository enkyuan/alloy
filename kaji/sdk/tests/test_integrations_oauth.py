from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import pytest

from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationPolicyError,
)
from kaji.integrations.oauth import (
    DisconnectResult,
    FileTokenStorage,
    GoogleOAuthClient,
    OAuthCredentialRecord,
    OAuthError,
    OAuthTokenSet,
    _OAuthHttpResponse,
    _create_google_oauth_client_for_test,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.context import ToolExecutionContext


SCOPES = ("scope/a", "scope/b")


class Clock:
    wall = 1_700_000_000.0
    monotonic = 100.0

    def now_wall_seconds(self) -> float:
        return self.wall

    def now_monotonic(self) -> float:
        return self.monotonic


def context(
    principal_id: str = "user-123",
    *,
    cancellation: CancellationToken | None = None,
    deadline: float | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id=principal_id,
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=cancellation or CancellationToken(),
        deadline_monotonic=deadline,
        db=None,
        metadata={},
    )


def record(
    *,
    access: str = "access",
    refresh: str = "refresh",
    expires: int = 1_700_003_600_000,
    scopes: tuple[str, ...] = SCOPES,
    state: Literal["active", "revocation_pending"] = "active",
) -> OAuthCredentialRecord:
    return OAuthCredentialRecord(
        schema_version=1,
        state=state,
        tokens=OAuthTokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_at_epoch_ms=expires,
            granted_scopes=scopes,
        ),
    )


class MemoryStore:
    def __init__(self, records: dict[str, OAuthCredentialRecord] | None = None) -> None:
        self.records = dict(records or {})
        self.calls: list[tuple[str, str]] = []

    async def load(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> OAuthCredentialRecord | None:
        cancellation.raise_if_cancelled()
        self.calls.append(("load", principal_id))
        return self.records.get(principal_id)

    async def save(
        self,
        principal_id: str,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        cancellation.raise_if_cancelled()
        self.calls.append(("save", principal_id))
        self.records[principal_id] = record

    async def delete(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        cancellation.raise_if_cancelled()
        self.calls.append(("delete", principal_id))
        self.records.pop(principal_id, None)


class PausingStore(MemoryStore):
    def __init__(self, records: dict[str, OAuthCredentialRecord]) -> None:
        super().__init__(records)
        self.delete_entered = asyncio.Event()
        self.release_delete = asyncio.Event()

    async def delete(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        self.delete_entered.set()
        await self.release_delete.wait()
        await super().delete(principal_id, cancellation, deadline_monotonic)


class PausingSaveStore(MemoryStore):
    def __init__(self, records: dict[str, OAuthCredentialRecord]) -> None:
        super().__init__(records)
        self.save_entered = asyncio.Event()
        self.save_cancelled = asyncio.Event()
        self.deadlines: list[float | None] = []

    async def save(
        self,
        principal_id: str,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None:
        del principal_id, record, cancellation
        self.deadlines.append(deadline_monotonic)
        self.save_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.save_cancelled.set()
            raise


class Http:
    def __init__(self, responses: list[_OAuthHttpResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.deadlines: list[float] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.pause = False

    async def post_form(
        self,
        endpoint: str,
        form: dict[str, str],
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> _OAuthHttpResponse:
        self.calls.append((endpoint, dict(form)))
        self.deadlines.append(deadline_monotonic)
        self.entered.set()
        try:
            if self.pause:
                release = asyncio.create_task(self.release.wait())
                cancelled = asyncio.create_task(cancellation.wait())
                done, _ = await asyncio.wait(
                    {release, cancelled}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in (release, cancelled):
                    if task not in done:
                        task.cancel()
                cancellation.raise_if_cancelled()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return self.responses.pop(0)


class Callback:
    redirect_uri = "http://127.0.0.1:43117/oauth/callback"

    def __init__(self, code: str = "auth-code") -> None:
        self.code = code
        self.state: str | None = None
        self.closed = False

    async def wait_for_code(
        self,
        expected_state: str,
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> str:
        cancellation.raise_if_cancelled()
        self.state = expected_state
        return self.code

    async def close(self) -> None:
        self.closed = True


class CallbackFactory:
    def __init__(self, callback: Callback) -> None:
        self.callback = callback
        self.calls = 0

    async def open(
        self, cancellation: CancellationToken, deadline_monotonic: float
    ) -> Callback:
        cancellation.raise_if_cancelled()
        self.calls += 1
        return self.callback


class Browser:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def open(
        self, url: str, cancellation: CancellationToken, deadline_monotonic: float
    ) -> None:
        cancellation.raise_if_cancelled()
        self.urls.append(url)


def client(
    *,
    store: MemoryStore,
    http: Http | None = None,
    callback: Callback | None = None,
    browser: Browser | None = None,
    client_id: str | None = "client-id",
    client_secret: str | None = None,
    clock: Clock | None = None,
    operation_seconds: float = 30,
) -> GoogleOAuthClient:
    callback = callback or Callback()
    browser = browser or Browser()
    return _create_google_oauth_client_for_test(
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
        credential_store=store,
        http=http or Http(),
        callback_factory=CallbackFactory(callback),
        browser=browser,
        clock=clock or Clock(),
        random_bytes=lambda count: bytes(range(count)),
        operation_seconds=operation_seconds,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal", ["", " user", "user@example.com", "üser", "a" * 129]
)
async def test_principal_is_rejected_before_every_dependency(principal: str) -> None:
    store = MemoryStore()
    http = Http()
    callback = Callback()
    browser = Browser()
    oauth = client(store=store, http=http, callback=callback, browser=browser)

    if principal not in {"", " user"}:
        with pytest.raises(IntegrationPolicyError):
            await oauth.access_token(context(principal))
    with pytest.raises(IntegrationPolicyError):
        await oauth.connect(principal, CancellationToken())
    with pytest.raises(IntegrationPolicyError):
        await oauth.disconnect(principal, CancellationToken())

    assert store.calls == []
    assert http.calls == []
    assert browser.urls == []


@pytest.mark.asyncio
async def test_access_without_grant_never_starts_consent() -> None:
    store = MemoryStore()
    callback = Callback()
    browser = Browser()
    oauth = client(store=store, callback=callback, browser=browser)

    with pytest.raises(IntegrationAuthRequiredError) as captured:
        await oauth.access_token(context())

    assert captured.value.reason_code == "gmail_grant_missing"
    assert browser.urls == []
    assert callback.state is None


@pytest.mark.asyncio
async def test_fresh_token_is_principal_bound_and_never_calls_http() -> None:
    store = MemoryStore({"user-123": record()})
    http = Http()
    oauth = client(store=store, http=http, client_id=None)
    assert await oauth.access_token(context()) == "access"
    assert http.calls == []


@pytest.mark.asyncio
async def test_pending_or_scope_drift_never_yields_a_token() -> None:
    pending = MemoryStore({"user-123": record(state="revocation_pending")})
    with pytest.raises(IntegrationAuthRequiredError):
        await client(store=pending, client_id=None).access_token(context())

    drift = MemoryStore({"user-123": record(scopes=("scope/a",))})
    with pytest.raises(IntegrationAuthRequiredError) as captured:
        await client(store=drift, client_id=None).access_token(context())
    assert captured.value.reason_code == "gmail_scope_drift"
    assert "user-123" not in drift.records


@pytest.mark.asyncio
async def test_refresh_is_single_flight_and_preserves_omitted_fields() -> None:
    store = MemoryStore({"user-123": record(access="old", expires=1)})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                json.dumps(
                    {"access_token": "new", "expires_in": 3600, "token_type": "Bearer"}
                ).encode(),
            )
        ]
    )
    http.pause = True
    oauth = client(store=store, http=http)
    first = asyncio.create_task(oauth.access_token(context()))
    await http.entered.wait()
    second = asyncio.create_task(oauth.access_token(context()))
    await asyncio.sleep(0)
    http.release.set()

    assert await first == "new"
    assert await second == "new"
    assert len(http.calls) == 1
    saved = store.records["user-123"].tokens
    assert saved.refresh_token == "refresh"
    assert saved.granted_scopes == SCOPES


@pytest.mark.asyncio
async def test_refreshes_for_different_principals_overlap() -> None:
    store = MemoryStore(
        {
            "user-a": record(access="old-a", refresh="refresh-a", expires=1),
            "user-b": record(access="old-b", refresh="refresh-b", expires=1),
        }
    )
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new-a","expires_in":3600,"token_type":"Bearer"}',
            ),
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new-b","expires_in":3600,"token_type":"Bearer"}',
            ),
        ]
    )
    http.pause = True
    oauth = client(store=store, http=http)
    first = asyncio.create_task(oauth.access_token(context("user-a")))
    second = asyncio.create_task(oauth.access_token(context("user-b")))
    for _ in range(10):
        if len(http.calls) == 2:
            break
        await asyncio.sleep(0)
    assert len(http.calls) == 2
    http.release.set()
    assert set(await asyncio.gather(first, second)) == {"new-a", "new-b"}


@pytest.mark.asyncio
async def test_cancelled_refresh_waiter_does_not_cancel_another_waiter() -> None:
    store = MemoryStore({"user-123": record(expires=1)})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","expires_in":3600,"token_type":"Bearer"}',
            )
        ]
    )
    http.pause = True
    oauth = client(store=store, http=http)
    first_cancellation = CancellationToken()
    first = asyncio.create_task(
        oauth.access_token(context(cancellation=first_cancellation))
    )
    await http.entered.wait()
    second = asyncio.create_task(oauth.access_token(context()))
    await asyncio.sleep(0)
    first_cancellation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    assert len(http.calls) == 1
    http.release.set()
    assert await second == "new"


@pytest.mark.asyncio
async def test_last_refresh_waiter_cancels_shared_operation() -> None:
    store = MemoryStore({"user-123": record(expires=1)})
    http = Http()
    http.pause = True
    cancellation = CancellationToken()
    pending = asyncio.create_task(
        client(store=store, http=http).access_token(context(cancellation=cancellation))
    )
    await http.entered.wait()
    cancellation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert http.cancelled.is_set()


@pytest.mark.asyncio
async def test_refresh_deadline_cancels_a_stalled_save_and_reaps_the_flight() -> None:
    store = PausingSaveStore({"user-123": record(access="old", expires=1)})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","expires_in":3600,"token_type":"Bearer"}',
            )
        ]
    )
    pending = asyncio.create_task(
        client(store=store, http=http, operation_seconds=0.01).access_token(context())
    )
    await store.save_entered.wait()

    with pytest.raises(TimeoutError, match="OAuth operation timed out"):
        await pending

    assert store.save_cancelled.is_set()
    assert http.deadlines == store.deadlines == [100.01]
    assert store.records["user-123"].tokens.access_token == "old"


@pytest.mark.asyncio
async def test_invalid_grant_deletes_local_record() -> None:
    store = MemoryStore({"user-123": record(expires=1)})
    http = Http([_OAuthHttpResponse(400, b'{"error":"invalid_grant"}')])
    with pytest.raises(IntegrationAuthRequiredError):
        await client(store=store, http=http).access_token(context())
    assert "user-123" not in store.records


@pytest.mark.asyncio
async def test_refresh_scope_drift_deletes_local_record() -> None:
    store = MemoryStore({"user-123": record(expires=1)})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","expires_in":3600,"token_type":"Bearer","scope":"scope/a"}',
            )
        ]
    )
    with pytest.raises(IntegrationAuthRequiredError) as captured:
        await client(store=store, http=http).access_token(context())
    assert captured.value.reason_code == "gmail_scope_drift"
    assert "user-123" not in store.records


@pytest.mark.asyncio
async def test_scope_drift_delete_finishes_before_new_connect_save() -> None:
    store = PausingStore({"user-123": record(scopes=("scope/a",))})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","refresh_token":"new-refresh","expires_in":3600,"token_type":"Bearer","scope":"scope/a scope/b"}',
            )
        ]
    )
    oauth = client(store=store, http=http)
    stale = asyncio.create_task(oauth.access_token(context()))
    await store.delete_entered.wait()
    reconnect = asyncio.create_task(oauth.connect("user-123", CancellationToken()))
    await asyncio.sleep(0)
    assert http.calls == []
    store.release_delete.set()
    with pytest.raises(IntegrationAuthRequiredError):
        await stale
    await reconnect
    assert store.records["user-123"].tokens.access_token == "new"


@pytest.mark.asyncio
async def test_confirmed_revoke_uses_internal_cleanup_after_caller_cancel() -> None:
    caller_cancellation = CancellationToken()

    class CancellingHttp(Http):
        async def post_form(
            self,
            endpoint: str,
            form: dict[str, str],
            cancellation: CancellationToken,
            deadline_monotonic: float,
        ) -> _OAuthHttpResponse:
            response = await super().post_form(
                endpoint, form, cancellation, deadline_monotonic
            )
            caller_cancellation.cancel()
            return response

    store = MemoryStore({"user-123": record()})
    result = await client(
        store=store,
        http=CancellingHttp([_OAuthHttpResponse(200, b"")]),
        client_id=None,
    ).disconnect("user-123", caller_cancellation)
    assert result == DisconnectResult("deleted", True)
    assert "user-123" not in store.records


@pytest.mark.asyncio
async def test_confirmed_revoke_delete_survives_caller_task_cancellation() -> None:
    store = PausingStore({"user-123": record()})
    oauth = client(
        store=store,
        http=Http([_OAuthHttpResponse(200, b"")]),
        client_id=None,
    )
    disconnect = asyncio.create_task(oauth.disconnect("user-123", CancellationToken()))
    await store.delete_entered.wait()
    disconnect.cancel()
    await asyncio.sleep(0)
    assert not disconnect.done()

    with pytest.raises(IntegrationAuthRequiredError):
        await oauth.access_token(context())

    store.release_delete.set()
    with pytest.raises(asyncio.CancelledError):
        await disconnect
    with pytest.raises(IntegrationAuthRequiredError):
        await client(store=store, client_id=None).access_token(context())


@pytest.mark.asyncio
async def test_public_client_composes_with_async_credential_store() -> None:
    store = MemoryStore({"user-123": record(expires=9_000_000_000_000_000)})
    oauth = GoogleOAuthClient(
        client_id=None,
        scopes=SCOPES,
        credential_store=store,
    )
    assert await oauth.access_token(context()) == "access"


@pytest.mark.asyncio
async def test_connect_uses_fixed_endpoint_pkce_and_closes_callback() -> None:
    store = MemoryStore()
    callback = Callback()
    browser = Browser()
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                json.dumps(
                    {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                        "scope": "scope/b scope/a",
                    }
                ).encode(),
            )
        ]
    )
    oauth = client(store=store, http=http, callback=callback, browser=browser)
    await oauth.connect("user-123", CancellationToken())

    assert callback.closed
    auth = urlparse(browser.urls[0])
    assert (
        f"{auth.scheme}://{auth.netloc}{auth.path}"
        == "https://accounts.google.com/o/oauth2/v2/auth"
    )
    query = parse_qs(auth.query)
    verifier = base64.urlsafe_b64encode(bytes(range(64))).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == [challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [callback.redirect_uri]
    endpoint, form = http.calls[0]
    assert endpoint == "https://oauth2.googleapis.com/token"
    assert form["code_verifier"] == verifier
    assert "client_secret" not in form
    assert store.records["user-123"].state == "active"


@pytest.mark.asyncio
async def test_connect_blocks_access_to_the_old_token_until_new_save_finishes() -> None:
    store = MemoryStore({"user-123": record(access="old")})
    http = Http(
        [
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","refresh_token":"new-refresh","expires_in":3600,"token_type":"Bearer","scope":"scope/a scope/b"}',
            )
        ]
    )
    http.pause = True
    oauth = client(store=store, http=http)
    connecting = asyncio.create_task(oauth.connect("user-123", CancellationToken()))
    await http.entered.wait()

    with pytest.raises(IntegrationAuthRequiredError):
        await oauth.access_token(context())

    http.release.set()
    await connecting
    assert await oauth.access_token(context()) == "new"


@pytest.mark.asyncio
async def test_failed_connect_restores_old_token_and_releases_slot() -> None:
    store = MemoryStore({"user-123": record(access="old")})
    oauth = client(store=store, http=Http([_OAuthHttpResponse(400, b"")]))

    with pytest.raises(OAuthError):
        await oauth.connect("user-123", CancellationToken())

    assert oauth._slots == {}
    assert await oauth.access_token(context()) == "old"
    assert oauth._slots == {}


@pytest.mark.asyncio
async def test_cancelled_connect_restores_old_token_and_releases_slot() -> None:
    store = MemoryStore({"user-123": record(access="old")})
    http = Http()
    http.pause = True
    oauth = client(store=store, http=http)
    cancellation = CancellationToken()
    connecting = asyncio.create_task(oauth.connect("user-123", cancellation))
    await http.entered.wait()
    cancellation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await connecting

    assert oauth._slots == {}
    assert await oauth.access_token(context()) == "old"
    assert oauth._slots == {}


@pytest.mark.asyncio
async def test_disconnect_needs_no_client_id_and_confirms_revoke_before_delete() -> (
    None
):
    store = MemoryStore({"user-123": record()})
    http = Http([_OAuthHttpResponse(200, b"")])
    result = await client(store=store, http=http, client_id=None).disconnect(
        "user-123", CancellationToken()
    )
    assert result == DisconnectResult(local_state="deleted", remote_revoked=True)
    assert http.calls == [
        ("https://oauth2.googleapis.com/revoke", {"token": "refresh"})
    ]
    assert "user-123" not in store.records


@pytest.mark.asyncio
async def test_ambiguous_revoke_persists_pending_and_force_local_deletes() -> None:
    store = MemoryStore({"user-123": record()})
    http = Http([_OAuthHttpResponse(503, b"private-provider-body")])
    oauth = client(store=store, http=http, client_id=None)
    result = await oauth.disconnect("user-123", CancellationToken())
    assert result == DisconnectResult(
        local_state="revocation_pending", remote_revoked=False
    )
    assert store.records["user-123"].state == "revocation_pending"
    forced = await oauth.disconnect("user-123", CancellationToken(), force_local=True)
    assert forced == DisconnectResult(local_state="deleted", remote_revoked=False)
    assert "user-123" not in store.records


@pytest.mark.asyncio
async def test_connect_waits_for_disconnect_before_old_token_can_be_used() -> None:
    store = MemoryStore({"user-123": record()})
    http = Http(
        [
            _OAuthHttpResponse(200, b""),
            _OAuthHttpResponse(
                200,
                b'{"access_token":"new","refresh_token":"new-refresh","expires_in":3600,"token_type":"Bearer","scope":"scope/a scope/b"}',
            ),
        ]
    )
    http.pause = True
    browser = Browser()
    oauth = client(store=store, http=http, browser=browser)
    disconnect = asyncio.create_task(oauth.disconnect("user-123", CancellationToken()))
    await http.entered.wait()
    reconnect = asyncio.create_task(oauth.connect("user-123", CancellationToken()))
    await asyncio.sleep(0)
    assert browser.urls == []
    with pytest.raises(IntegrationAuthRequiredError):
        await oauth.access_token(context())
    http.release.set()
    assert await disconnect == DisconnectResult("deleted", True)
    await reconnect
    assert await oauth.access_token(context()) == "new"


def test_file_store_uses_canonical_wire_atomic_mode_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    storage = FileTokenStorage(path)
    payload = record().to_wire()
    storage.save(payload)
    assert storage.load() == payload
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["schemaVersion"] == 1
    assert not list(tmp_path.glob("*.tmp"))
    storage.delete()
    assert not path.exists()


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b'{"schemaVersion":2}', b"x" * (16 * 1024 + 1)],
)
def test_file_store_rejects_corrupt_unknown_and_oversize(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "tokens.json"
    path.write_bytes(payload)
    with pytest.raises(Exception) as captured:
        FileTokenStorage(path).load()
    assert "not-json" not in str(captured.value)


def test_file_store_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("secret")
    link = tmp_path / "tokens.json"
    link.symlink_to(target)
    with pytest.raises(Exception):
        FileTokenStorage(link).load()
    with pytest.raises(Exception):
        FileTokenStorage(link).save(record().to_wire())
    assert target.read_text() == "secret"


def test_file_store_rejects_a_symlink_swapped_at_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "tokens.json"
    victim = tmp_path / "victim.json"
    path.write_text(json.dumps(record(access="original").to_wire()))
    victim_payload = json.dumps(record(access="victim").to_wire())
    victim.write_text(victim_payload)
    original_path_open = Path.open
    original_os_open = os.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        path.unlink()
        path.symlink_to(victim)

    def swapping_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            swap()
        return original_path_open(self, *args, **kwargs)

    def swapping_os_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(file) == path:
            swap()
        return original_os_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapping_path_open)
    monkeypatch.setattr(os, "open", swapping_os_open)

    with pytest.raises(Exception):
        FileTokenStorage(path).load()
    assert victim.read_text() == victim_payload


def test_credential_wire_is_lower_camel_and_closed() -> None:
    wire = record().to_wire()
    assert set(wire) == {"schemaVersion", "state", "tokens"}
    tokens = wire["tokens"]
    assert isinstance(tokens, dict)
    assert set(tokens) == {
        "accessToken",
        "refreshToken",
        "expiresAtEpochMs",
        "grantedScopes",
        "tokenType",
    }
    with pytest.raises(Exception):
        OAuthCredentialRecord.from_wire({**wire, "unknown": True})
