"""Principal-bound Google installed-app OAuth with deterministic test seams."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Collection
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
import secrets
from typing import Any, Literal, Protocol, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from kaji.integrations.errors import (
    IntegrationAuthError,
    IntegrationAuthRequiredError,
    IntegrationExecutionError,
    IntegrationPolicyError,
)
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
    record_metric,
    start_span,
)
from kaji.runtime.agents.cancellation import CancelledError, CancellationToken
from kaji.runtime.context import ToolExecutionContext
from kaji.core.determinism import Clock, SYSTEM_CLOCK


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_CREDENTIAL_BYTES = 16 * 1024
_MAX_PROVIDER_BYTES = 64 * 1024
_MAX_TOKEN_CHARACTERS = 8_192
_MAX_SCOPE_CHARACTERS = 2_048
_MAX_SCOPES = 64
_REFRESH_BUFFER_MS = 60_000
_CALLBACK_SECONDS = 5 * 60
_OPERATION_SECONDS = 30
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class OAuthError(RuntimeError):
    """Redacted non-certified OAuth failure."""

    def __init__(self) -> None:
        super().__init__("OAuth operation failed")


class _OAuthScopeDrift(OAuthError):
    pass


def _policy_error() -> IntegrationPolicyError:
    return IntegrationPolicyError()


def _auth_required(reason: Literal["gmail_grant_missing", "gmail_scope_drift"]):
    return IntegrationAuthRequiredError(reason)


def _auth_error(reason: Literal["keychain_corrupt"] = "keychain_corrupt"):
    return IntegrationAuthError(reason)


def _require_principal(value: object) -> str:
    if not isinstance(value, str) or not _PRINCIPAL.fullmatch(value):
        raise _policy_error()
    return value


def _bounded_string(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _auth_error()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _auth_error() from None
    return value


def _normalize_scopes(value: Collection[str]) -> tuple[str, ...]:
    try:
        scopes = tuple(sorted(set(value)))
    except (TypeError, ValueError):
        raise _policy_error() from None
    if (
        not scopes
        or len(scopes) > _MAX_SCOPES
        or any(
            not isinstance(scope, str)
            or not scope
            or len(scope) > _MAX_SCOPE_CHARACTERS
            or any(character.isspace() for character in scope)
            for scope in scopes
        )
    ):
        raise _policy_error()
    return scopes


@dataclass(frozen=True, slots=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str
    expires_at_epoch_ms: int
    granted_scopes: tuple[str, ...]
    token_type: Literal["Bearer"] = "Bearer"

    def __post_init__(self) -> None:
        _bounded_string(self.access_token, maximum=_MAX_TOKEN_CHARACTERS)
        _bounded_string(self.refresh_token, maximum=_MAX_TOKEN_CHARACTERS)
        if (
            type(self.expires_at_epoch_ms) is not int
            or not 1 <= self.expires_at_epoch_ms <= _MAX_SAFE_INTEGER
            or self.token_type != "Bearer"
        ):
            raise _auth_error()
        normalized = _normalize_record_scopes(self.granted_scopes)
        if normalized != self.granted_scopes:
            raise _auth_error()


@dataclass(frozen=True, slots=True)
class OAuthCredentialRecord:
    schema_version: Literal[1]
    state: Literal["active", "revocation_pending"]
    tokens: OAuthTokenSet

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.state not in {
            "active",
            "revocation_pending",
        }:
            raise _auth_error()

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "state": self.state,
            "tokens": {
                "accessToken": self.tokens.access_token,
                "refreshToken": self.tokens.refresh_token,
                "expiresAtEpochMs": self.tokens.expires_at_epoch_ms,
                "grantedScopes": list(self.tokens.granted_scopes),
                "tokenType": "Bearer",
            },
        }

    @classmethod
    def from_wire(cls, value: object) -> OAuthCredentialRecord:
        try:
            if type(value) is not dict or set(value) != {
                "schemaVersion",
                "state",
                "tokens",
            }:
                raise ValueError
            document = cast(dict[str, object], value)
            tokens = document["tokens"]
            if type(tokens) is not dict or set(tokens) != {
                "accessToken",
                "refreshToken",
                "expiresAtEpochMs",
                "grantedScopes",
                "tokenType",
            }:
                raise ValueError
            token_document = cast(dict[str, object], tokens)
            scopes = token_document["grantedScopes"]
            if type(scopes) is not list:
                raise ValueError
            return cls(
                schema_version=cast(Literal[1], document["schemaVersion"]),
                state=cast(Literal["active", "revocation_pending"], document["state"]),
                tokens=OAuthTokenSet(
                    access_token=cast(str, token_document["accessToken"]),
                    refresh_token=cast(str, token_document["refreshToken"]),
                    expires_at_epoch_ms=cast(int, token_document["expiresAtEpochMs"]),
                    granted_scopes=cast(tuple[str, ...], tuple(scopes)),
                    token_type=cast(Literal["Bearer"], token_document["tokenType"]),
                ),
            )
        except (KeyError, TypeError, ValueError, IntegrationAuthError):
            raise _auth_error() from None


def _normalize_record_scopes(value: object) -> tuple[str, ...]:
    if type(value) not in {tuple, list}:
        raise _auth_error()
    scopes = cast(tuple[object, ...] | list[object], value)
    if (
        not scopes
        or len(scopes) > _MAX_SCOPES
        or any(
            not isinstance(scope, str)
            or not scope
            or len(scope) > _MAX_SCOPE_CHARACTERS
            or any(character.isspace() for character in scope)
            for scope in scopes
        )
    ):
        raise _auth_error()
    normalized = tuple(sorted(set(cast(Collection[str], scopes))))
    if len(normalized) != len(scopes):
        raise _auth_error()
    return normalized


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    local_state: Literal["deleted", "revocation_pending", "missing"]
    remote_revoked: bool


def _canonical_wire(data: object) -> tuple[OAuthCredentialRecord, bytes]:
    record = OAuthCredentialRecord.from_wire(data)
    encoded = json.dumps(
        record.to_wire(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(encoded) > _MAX_CREDENTIAL_BYTES:
        raise _auth_error()
    return record, encoded


class CredentialStore(Protocol):
    """Principal-scoped asynchronous OAuth credential persistence."""

    async def load(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> OAuthCredentialRecord | None: ...

    async def save(
        self,
        principal_id: str,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None: ...

    async def delete(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _OAuthHttpResponse:
    status: int
    body: bytes


class _OAuthTransport(Protocol):
    async def post_form(
        self,
        endpoint: str,
        form: dict[str, str],
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> _OAuthHttpResponse: ...


class _HttpxOAuthTransport:
    async def post_form(
        self,
        endpoint: str,
        form: dict[str, str],
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> _OAuthHttpResponse:
        if endpoint not in {GOOGLE_TOKEN_URL, GOOGLE_REVOKE_URL}:
            raise _policy_error()
        cancellation.raise_if_cancelled()

        async def request() -> _OAuthHttpResponse:
            async with httpx.AsyncClient(
                timeout=_OPERATION_SECONDS, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream("POST", endpoint, data=form) as response:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_PROVIDER_BYTES:
                            raise OAuthError()
                        chunks.append(chunk)
                    return _OAuthHttpResponse(response.status_code, b"".join(chunks))

        operation = asyncio.create_task(request())
        cancelled = asyncio.create_task(cancellation.wait())
        try:
            remaining = deadline_monotonic - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("OAuth operation timed out")
            done, _ = await asyncio.wait(
                {operation, cancelled},
                timeout=min(_OPERATION_SECONDS, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                operation.cancel()
                cancellation.raise_if_cancelled()
            if operation not in done:
                operation.cancel()
                raise TimeoutError("OAuth operation timed out")
            return await operation
        except (asyncio.CancelledError, TimeoutError):
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise
        except Exception:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise OAuthError() from None
        finally:
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)


class _AuthorizationCallback(Protocol):
    redirect_uri: str

    async def wait_for_code(
        self,
        expected_state: str,
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> str: ...

    async def close(self) -> None: ...


class _CallbackFactory(Protocol):
    async def open(
        self, cancellation: CancellationToken, deadline_monotonic: float
    ) -> _AuthorizationCallback: ...


class _Browser(Protocol):
    async def open(
        self,
        url: str,
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> None: ...


class _SystemBrowser:
    async def open(
        self,
        url: str,
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> None:
        cancellation.raise_if_cancelled()
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/open",
                url,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            waiter = asyncio.create_task(process.wait())
            cancelled = asyncio.create_task(cancellation.wait())
            remaining = deadline_monotonic - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("OAuth browser timed out")
            done, _ = await asyncio.wait(
                {waiter, cancelled},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                cancellation.raise_if_cancelled()
            if waiter not in done:
                raise TimeoutError("OAuth browser timed out")
            if await waiter != 0:
                raise OAuthError()
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)
        except (asyncio.CancelledError, TimeoutError):
            if process is not None:
                await self._terminate(process)
            raise
        except Exception:
            if process is not None:
                await self._terminate(process)
            raise OAuthError() from None
        cancellation.raise_if_cancelled()

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            await process.wait()
            return
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 0.25)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


class _LoopbackCallback:
    def __init__(
        self,
        server: asyncio.AbstractServer,
        future: asyncio.Future[tuple[str, str]],
        writers: set[asyncio.StreamWriter],
    ) -> None:
        self._server = server
        self._future = future
        self._writers = writers
        sockets = getattr(server, "sockets", None) or ()
        if len(sockets) != 1:
            raise OAuthError()
        self.redirect_uri = (
            f"http://127.0.0.1:{sockets[0].getsockname()[1]}/oauth/callback"
        )

    async def wait_for_code(
        self,
        expected_state: str,
        cancellation: CancellationToken,
        deadline_monotonic: float,
    ) -> str:
        cancelled = asyncio.create_task(cancellation.wait())
        try:
            remaining = deadline_monotonic - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("OAuth callback timed out")
            done, _ = await asyncio.wait(
                {self._future, cancelled},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                cancellation.raise_if_cancelled()
            if self._future not in done:
                raise TimeoutError("OAuth callback timed out")
            state, code = self._future.result()
            if not hmac.compare_digest(state, expected_state):
                raise OAuthError()
            if not code:
                raise OAuthError()
            return code
        finally:
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    async def close(self) -> None:
        self._server.close()
        await self._server.wait_closed()
        writers = tuple(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers), return_exceptions=True
            )


class _LoopbackCallbackFactory:
    async def open(
        self, cancellation: CancellationToken, deadline_monotonic: float
    ) -> _AuthorizationCallback:
        cancellation.raise_if_cancelled()
        future: asyncio.Future[tuple[str, str]] = (
            asyncio.get_running_loop().create_future()
        )
        writers: set[asyncio.StreamWriter] = set()

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            writers.add(writer)
            try:
                raw = await reader.readuntil(b"\r\n\r\n")
                if len(raw) > 8_192:
                    raise ValueError
                first = raw.split(b"\r\n", 1)[0].decode("ascii")
                method, target, _version = first.split(" ", 2)
                parsed = urlparse(target)
                query = parse_qs(parsed.query, strict_parsing=True)
                state = query.get("state", [""])[0]
                code = query.get("code", [""])[0]
                valid = method == "GET" and parsed.path == "/oauth/callback"
                if not valid or "error" in query:
                    state, code = "", ""
                if not future.done():
                    future.set_result((state[:256], code[:8_192]))
                status = b"200 OK" if valid and code else b"400 Bad Request"
            except Exception:
                if not future.done():
                    future.set_result(("", ""))
                status = b"400 Bad Request"
            finally:
                try:
                    writer.write(
                        b"HTTP/1.1 "
                        + status
                        + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                    await writer.drain()
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                    writers.discard(writer)

        try:
            server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=8_193)
        except Exception:
            raise OAuthError() from None
        return _LoopbackCallback(server, future, writers)


@dataclass(slots=True)
class _OwnedOperation:
    task: asyncio.Task[None]
    cancellation: CancellationToken
    generation: int


@dataclass(slots=True)
class _RefreshFlight:
    task: asyncio.Task[str]
    cancellation: CancellationToken
    generation: int
    waiters: int = 0


class _PrincipalSlot:
    def __init__(self) -> None:
        self.gate = asyncio.Lock()
        self.generation = 0
        self.blocked = False
        self.connect: _OwnedOperation | None = None
        self.refresh: _RefreshFlight | None = None
        self.disconnect: asyncio.Task[Any] | None = None
        self.references = 0


def _check_scope(
    cancellation: CancellationToken,
    deadline_monotonic: float | None,
    clock: Clock,
) -> None:
    cancellation.raise_if_cancelled()
    if deadline_monotonic is not None and deadline_monotonic <= clock.now_monotonic():
        raise TimeoutError("OAuth operation timed out")


class GoogleOAuthClient:
    """Google OAuth client whose only consent entry point is :meth:`connect`."""

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None = None,
        scopes: Collection[str],
        credential_store: CredentialStore,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
    ) -> None:
        self._initialize(
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
            credential_store=credential_store,
            http=_HttpxOAuthTransport(),
            callback_factory=_LoopbackCallbackFactory(),
            browser=_SystemBrowser(),
            clock=SYSTEM_CLOCK,
            random_bytes=secrets.token_bytes,
            metrics_sink=metrics_sink,
            trace_sink=trace_sink,
        )

    def _initialize(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        scopes: Collection[str],
        credential_store: CredentialStore,
        http: _OAuthTransport,
        callback_factory: _CallbackFactory,
        browser: _Browser,
        clock: Clock,
        random_bytes: Callable[[int], bytes],
        operation_seconds: float = _OPERATION_SECONDS,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
    ) -> None:
        if client_id is not None and (
            not isinstance(client_id, str) or not client_id or len(client_id) > 4_096
        ):
            client_id = None
        if client_secret is not None and (
            not isinstance(client_secret, str)
            or not client_secret
            or len(client_secret) > 8_192
        ):
            raise _policy_error()
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = _normalize_scopes(scopes)
        self._store = credential_store
        self._http = http
        self._callback_factory = callback_factory
        self._browser = browser
        self._clock = clock
        self._random_bytes = random_bytes
        self._operation_seconds = operation_seconds
        self._metrics_sink = metrics_sink
        self._trace_sink = trace_sink
        self._slots: dict[str, _PrincipalSlot] = {}
        self._slots_gate = asyncio.Lock()

    async def connect(self, principal_id: str, cancellation: CancellationToken) -> None:
        principal_id = _require_principal(principal_id)
        _check_scope(cancellation, None, self._clock)
        client_id = self._required_client_id()
        slot = await self._acquire_slot(principal_id)
        try:
            while True:
                pending_disconnect: asyncio.Task[Any] | None = None
                async with slot.gate:
                    if slot.disconnect is not None:
                        pending_disconnect = slot.disconnect
                    else:
                        slot.generation += 1
                        slot.blocked = True
                        generation = slot.generation
                        previous: list[asyncio.Task[Any]] = []
                        if slot.connect is not None:
                            slot.connect.cancellation.cancel()
                            slot.connect.task.cancel()
                            previous.append(slot.connect.task)
                        if slot.refresh is not None:
                            slot.refresh.cancellation.cancel()
                            slot.refresh.task.cancel()
                            previous.append(slot.refresh.task)
                        internal = CancellationToken()
                        task = asyncio.create_task(
                            self._run_connect_after(
                                principal_id,
                                slot,
                                generation,
                                client_id,
                                internal,
                                tuple(previous),
                            )
                        )
                        operation = _OwnedOperation(task, internal, generation)
                        slot.connect = operation
                if pending_disconnect is None:
                    break
                await self._await_owned(pending_disconnect, cancellation, None)
            try:
                await self._await_owned(task, cancellation, None)
            except BaseException:
                internal.cancel()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                async with slot.gate:
                    if (
                        slot.connect is operation
                        and slot.generation == operation.generation
                    ):
                        slot.blocked = False
                raise
            finally:
                async with slot.gate:
                    if slot.connect is operation:
                        slot.connect = None
        finally:
            await self._release_slot(principal_id, slot)

    async def access_token(self, context: ToolExecutionContext) -> str:
        started = self._clock.now_monotonic()
        span = start_span(
            self._trace_sink,
            "kaji.integration.auth",
            {
                "integration.name": "gmail",
                "integration.operation": "token",
                "http.status_family": "none",
            },
        )
        outcome = "error"
        try:
            token = await self._access_token(context)
            outcome = "success"
            return token
        except BaseException as error:
            if isinstance(error, (asyncio.CancelledError, CancelledError)):
                outcome = "cancelled"
            span.record_error(error)
            raise
        finally:
            record_metric(
                self._metrics_sink,
                "kaji.integration.auth_ms",
                max(0.0, (self._clock.now_monotonic() - started) * 1_000),
                integration="gmail",
                operation="token",
                outcome=outcome,
            )
            span.end()

    async def _access_token(self, context: ToolExecutionContext) -> str:
        principal_id = _require_principal(context.principal_id)
        _check_scope(
            context.cancellation_token, context.deadline_monotonic, self._clock
        )
        slot = await self._acquire_slot(principal_id)
        try:
            if slot.blocked:
                raise _auth_required("gmail_grant_missing")
            async with slot.gate:
                if slot.blocked:
                    raise _auth_required("gmail_grant_missing")
                generation = slot.generation
            record = await self._store.load(
                principal_id,
                context.cancellation_token,
                context.deadline_monotonic,
            )
            if record is None or record.state == "revocation_pending":
                raise _auth_required("gmail_grant_missing")
            if not set(record.tokens.granted_scopes).issuperset(self._scopes):
                await self._delete_if_current(
                    principal_id,
                    slot,
                    generation,
                    context.cancellation_token,
                    context.deadline_monotonic,
                )
                raise _auth_required("gmail_scope_drift")
            if (
                record.tokens.expires_at_epoch_ms
                > int(self._clock.now_wall_seconds() * 1_000) + _REFRESH_BUFFER_MS
            ):
                async with slot.gate:
                    if slot.blocked or slot.generation != generation:
                        raise _auth_required("gmail_grant_missing")
                    return record.tokens.access_token
            return await self._join_refresh(
                principal_id, slot, generation, record, context
            )
        finally:
            await self._release_slot(principal_id, slot)

    async def authorized_headers(self, context: ToolExecutionContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.access_token(context)}"}

    async def disconnect(
        self,
        principal_id: str,
        cancellation: CancellationToken,
        *,
        force_local: bool = False,
    ) -> DisconnectResult:
        principal_id = _require_principal(principal_id)
        _check_scope(cancellation, None, self._clock)
        slot = await self._acquire_slot(principal_id)
        current = asyncio.current_task()
        assert current is not None
        async with slot.gate:
            previous_disconnect = slot.disconnect
            slot.disconnect = current
        try:
            if previous_disconnect is not None and previous_disconnect is not current:
                await self._await_owned(previous_disconnect, cancellation, None)
            async with slot.gate:
                slot.generation += 1
                slot.blocked = True
                generation = slot.generation
                operations: list[asyncio.Task[object]] = []
                if slot.connect is not None:
                    slot.connect.cancellation.cancel()
                    slot.connect.task.cancel()
                    operations.append(cast(asyncio.Task[object], slot.connect.task))
                if slot.refresh is not None:
                    slot.refresh.cancellation.cancel()
                    slot.refresh.task.cancel()
                    operations.append(cast(asyncio.Task[object], slot.refresh.task))
            if operations:
                await asyncio.gather(*operations, return_exceptions=True)
            record = await self._store.load(principal_id, cancellation, None)
            if record is None:
                await self._unblock_if_current(slot, generation)
                return DisconnectResult("missing", False)
            if force_local:
                await self._delete_blocked_if_current(
                    principal_id, slot, generation, cancellation, None
                )
                await self._unblock_if_current(slot, generation)
                return DisconnectResult("deleted", False)
            pending = OAuthCredentialRecord(
                schema_version=1,
                state="revocation_pending",
                tokens=record.tokens,
            )
            cleanup = CancellationToken()
            deadline = self._clock.now_monotonic() + _OPERATION_SECONDS
            try:
                response = await self._http.post_form(
                    GOOGLE_REVOKE_URL,
                    {"token": record.tokens.refresh_token},
                    cancellation,
                    deadline,
                )
            except asyncio.CancelledError:
                await self._await_disconnect_cleanup(
                    asyncio.create_task(
                        self._complete_disconnect(
                            principal_id,
                            slot,
                            generation,
                            pending,
                            cleanup,
                            remote_revoked=False,
                        )
                    )
                )
                raise
            except Exception:
                return await self._await_disconnect_cleanup(
                    asyncio.create_task(
                        self._complete_disconnect(
                            principal_id,
                            slot,
                            generation,
                            pending,
                            cleanup,
                            remote_revoked=False,
                        )
                    )
                )
            return await self._await_disconnect_cleanup(
                asyncio.create_task(
                    self._complete_disconnect(
                        principal_id,
                        slot,
                        generation,
                        pending,
                        cleanup,
                        remote_revoked=response.status == 200,
                    )
                )
            )
        finally:
            async with slot.gate:
                if slot.disconnect is current:
                    slot.disconnect = None
            await self._release_slot(principal_id, slot)

    def _required_client_id(self) -> str:
        if self._client_id is None:
            raise _auth_required("gmail_grant_missing")
        return self._client_id

    async def _run_connect_after(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        client_id: str,
        cancellation: CancellationToken,
        previous: tuple[asyncio.Task[Any], ...],
    ) -> None:
        if previous:
            await asyncio.gather(*previous, return_exceptions=True)
        cancellation.raise_if_cancelled()
        async with slot.gate:
            current = asyncio.current_task()
            if (
                slot.generation != generation
                or slot.connect is None
                or slot.connect.task is not current
            ):
                raise _auth_required("gmail_grant_missing")
        await self._run_connect(principal_id, slot, generation, client_id, cancellation)
        async with slot.gate:
            current = asyncio.current_task()
            if (
                slot.generation != generation
                or slot.connect is None
                or slot.connect.task is not current
            ):
                raise _auth_required("gmail_grant_missing")
            slot.blocked = False

    async def _run_connect(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        client_id: str,
        cancellation: CancellationToken,
    ) -> None:
        deadline = self._clock.now_monotonic() + _CALLBACK_SECONDS
        callback = await self._callback_factory.open(cancellation, deadline)
        try:
            state = _base64url(self._random_bytes(32))
            verifier = _base64url(self._random_bytes(64))
            if not 43 <= len(verifier) <= 128:
                raise OAuthError()
            challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
            params = {
                "client_id": client_id,
                "redirect_uri": callback.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._scopes),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            authorization_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
            await self._browser.open(authorization_url, cancellation, deadline)
            code = await callback.wait_for_code(state, cancellation, deadline)
            code = _bounded_provider_string(code, 8_192)
            form = {
                "code": code,
                "code_verifier": verifier,
                "client_id": client_id,
                "redirect_uri": callback.redirect_uri,
                "grant_type": "authorization_code",
            }
            if self._client_secret is not None:
                form["client_secret"] = self._client_secret
            response = await self._http.post_form(
                GOOGLE_TOKEN_URL,
                form,
                cancellation,
                self._clock.now_monotonic() + _OPERATION_SECONDS,
            )
            if response.status != 200:
                raise OAuthError()
            tokens = self._tokens_from_response(
                response.body, fallback=None, require_scope=True
            )
            record = OAuthCredentialRecord(1, "active", tokens)
            await self._save_if_current(
                principal_id,
                slot,
                generation,
                record,
                cancellation,
                self._clock.now_monotonic() + _OPERATION_SECONDS,
                allow_blocked_active=True,
            )
        except (asyncio.CancelledError, TimeoutError):
            raise
        except (IntegrationAuthRequiredError, IntegrationPolicyError):
            raise
        except Exception:
            raise OAuthError() from None
        finally:
            await callback.close()

    async def _join_refresh(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        record: OAuthCredentialRecord,
        context: ToolExecutionContext,
    ) -> str:
        async with slot.gate:
            if slot.blocked or slot.generation != generation:
                raise _auth_required("gmail_grant_missing")
            flight = slot.refresh
            if flight is None or flight.generation != generation:
                internal = CancellationToken()
                deadline = self._clock.now_monotonic() + self._operation_seconds
                task = asyncio.create_task(
                    self._run_refresh(
                        principal_id,
                        slot,
                        generation,
                        record,
                        internal,
                        deadline,
                    )
                )
                flight = _RefreshFlight(task, internal, generation)
                slot.refresh = flight
            flight.waiters += 1
        try:
            return await self._await_owned(
                flight.task,
                context.cancellation_token,
                context.deadline_monotonic,
            )
        finally:
            cancel = False
            async with slot.gate:
                flight.waiters -= 1
                cancel = flight.waiters == 0 and not flight.task.done()
            if cancel:
                flight.cancellation.cancel()
                flight.task.cancel()
                await asyncio.gather(flight.task, return_exceptions=True)

    async def _run_refresh(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline: float,
    ) -> str:
        task = asyncio.current_task()
        try:
            try:
                async with asyncio.timeout(self._operation_seconds):
                    client_id = self._required_client_id()
                    form = {
                        "refresh_token": record.tokens.refresh_token,
                        "client_id": client_id,
                        "grant_type": "refresh_token",
                    }
                    if self._client_secret is not None:
                        form["client_secret"] = self._client_secret
                    response = await self._http.post_form(
                        GOOGLE_TOKEN_URL,
                        form,
                        cancellation,
                        deadline,
                    )
                    if response.status != 200:
                        if _provider_error_code(response.body) == "invalid_grant":
                            await self._delete_if_current(
                                principal_id,
                                slot,
                                generation,
                                cancellation,
                                deadline,
                            )
                            raise _auth_required("gmail_grant_missing")
                        raise IntegrationExecutionError("api_rejected")
                    try:
                        tokens = self._tokens_from_response(
                            response.body, fallback=record.tokens, require_scope=False
                        )
                    except _OAuthScopeDrift:
                        await self._delete_if_current(
                            principal_id,
                            slot,
                            generation,
                            cancellation,
                            deadline,
                        )
                        raise _auth_required("gmail_scope_drift") from None
                    updated = OAuthCredentialRecord(1, "active", tokens)
                    await self._save_if_current(
                        principal_id,
                        slot,
                        generation,
                        updated,
                        cancellation,
                        deadline,
                    )
                    return tokens.access_token
            except TimeoutError:
                cancellation.cancel()
                raise TimeoutError("OAuth operation timed out") from None
        finally:
            cancellation.cancel()
            async with slot.gate:
                if slot.refresh is not None and slot.refresh.task is task:
                    slot.refresh = None

    def _tokens_from_response(
        self,
        body: bytes,
        *,
        fallback: OAuthTokenSet | None,
        require_scope: bool,
    ) -> OAuthTokenSet:
        value = _provider_json(body)
        access_token = _bounded_provider_string(value.get("access_token"), 8_192)
        token_type = value.get("token_type")
        if token_type != "Bearer":
            raise OAuthError()
        refresh_value = value.get("refresh_token")
        if refresh_value is None and fallback is not None:
            refresh_token = fallback.refresh_token
        else:
            refresh_token = _bounded_provider_string(refresh_value, 8_192)
        expires = value.get("expires_in")
        if (
            isinstance(expires, bool)
            or not isinstance(expires, (int, float))
            or not math.isfinite(float(expires))
            or not 0 < float(expires) <= 604_800
        ):
            raise OAuthError()
        scope_value = value.get("scope")
        if scope_value is None:
            if require_scope or fallback is None:
                raise OAuthError()
            granted = fallback.granted_scopes
        else:
            if not isinstance(scope_value, str):
                raise OAuthError()
            granted = _normalize_provider_scopes(scope_value)
            if not set(granted).issuperset(self._scopes):
                if fallback is not None:
                    raise _OAuthScopeDrift()
                raise OAuthError()
        expiry = int(self._clock.now_wall_seconds() * 1_000 + float(expires) * 1_000)
        return OAuthTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_epoch_ms=expiry,
            granted_scopes=granted,
        )

    async def _save_if_current(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        record: OAuthCredentialRecord,
        cancellation: CancellationToken,
        deadline: float | None,
        *,
        allow_blocked_active: bool = False,
    ) -> None:
        async with slot.gate:
            if slot.generation != generation or (
                slot.blocked and record.state == "active" and not allow_blocked_active
            ):
                raise _auth_required("gmail_grant_missing")
            await self._store.save(principal_id, record, cancellation, deadline)

    async def _complete_disconnect(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        pending: OAuthCredentialRecord,
        cleanup: CancellationToken,
        *,
        remote_revoked: bool,
    ) -> DisconnectResult:
        deadline = self._clock.now_monotonic() + self._operation_seconds
        if remote_revoked:
            try:
                await self._delete_blocked_if_current(
                    principal_id, slot, generation, cleanup, deadline
                )
            except (Exception, asyncio.CancelledError):
                await self._save_if_current(
                    principal_id, slot, generation, pending, cleanup, deadline
                )
                await self._unblock_if_current(slot, generation)
                return DisconnectResult("revocation_pending", True)
            await self._unblock_if_current(slot, generation)
            return DisconnectResult("deleted", True)
        await self._save_if_current(
            principal_id, slot, generation, pending, cleanup, deadline
        )
        await self._unblock_if_current(slot, generation)
        return DisconnectResult("revocation_pending", False)

    async def _await_disconnect_cleanup(
        self, task: asyncio.Task[DisconnectResult]
    ) -> DisconnectResult:
        caller_cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                caller_cancelled = True
        result = task.result()
        if caller_cancelled:
            raise asyncio.CancelledError
        return result

    async def _unblock_if_current(self, slot: _PrincipalSlot, generation: int) -> None:
        async with slot.gate:
            if slot.generation == generation:
                slot.blocked = False

    async def _delete_if_current(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        cancellation: CancellationToken,
        deadline: float | None,
    ) -> None:
        async with slot.gate:
            if slot.generation != generation or slot.blocked:
                raise _auth_required("gmail_grant_missing")
            await self._store.delete(principal_id, cancellation, deadline)

    async def _delete_blocked_if_current(
        self,
        principal_id: str,
        slot: _PrincipalSlot,
        generation: int,
        cancellation: CancellationToken,
        deadline: float | None,
    ) -> None:
        async with slot.gate:
            if slot.generation != generation or not slot.blocked:
                raise _auth_required("gmail_grant_missing")
            await self._store.delete(principal_id, cancellation, deadline)

    async def _await_owned(
        self,
        task: asyncio.Task[Any],
        cancellation: CancellationToken,
        deadline_monotonic: float | None,
    ) -> Any:
        cancellation.raise_if_cancelled()
        waiter = asyncio.ensure_future(asyncio.shield(task))
        cancelled = asyncio.create_task(cancellation.wait())
        remaining = (
            None
            if deadline_monotonic is None
            else max(0.0, deadline_monotonic - self._clock.now_monotonic())
        )
        try:
            done, _ = await asyncio.wait(
                {waiter, cancelled},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                cancellation.raise_if_cancelled()
            if waiter not in done:
                raise TimeoutError("OAuth operation timed out")
            return await waiter
        finally:
            waiter.cancel()
            cancelled.cancel()
            await asyncio.gather(waiter, cancelled, return_exceptions=True)

    async def _acquire_slot(self, principal_id: str) -> _PrincipalSlot:
        async with self._slots_gate:
            slot = self._slots.get(principal_id)
            if slot is None:
                slot = _PrincipalSlot()
                self._slots[principal_id] = slot
            slot.references += 1
            return slot

    async def _release_slot(self, principal_id: str, slot: _PrincipalSlot) -> None:
        async with self._slots_gate:
            slot.references -= 1
            if (
                slot.references == 0
                and slot.connect is None
                and slot.refresh is None
                and slot.disconnect is None
                and not slot.blocked
                and self._slots.get(principal_id) is slot
            ):
                del self._slots[principal_id]


def _create_google_oauth_client_for_test(
    *,
    client_id: str | None,
    client_secret: str | None,
    scopes: Collection[str],
    credential_store: CredentialStore,
    http: _OAuthTransport,
    callback_factory: _CallbackFactory,
    browser: _Browser,
    clock: Clock,
    random_bytes: Callable[[int], bytes],
    operation_seconds: float = _OPERATION_SECONDS,
) -> GoogleOAuthClient:
    client = object.__new__(GoogleOAuthClient)
    client._initialize(
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        credential_store=credential_store,
        http=http,
        callback_factory=callback_factory,
        browser=browser,
        clock=clock,
        random_bytes=random_bytes,
        operation_seconds=operation_seconds,
    )
    return client


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _bounded_provider_string(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise OAuthError()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise OAuthError() from None
    return value


def _provider_json(body: bytes) -> dict[str, object]:
    if len(body) > _MAX_PROVIDER_BYTES:
        raise OAuthError()
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OAuthError() from None
    if type(value) is not dict:
        raise OAuthError()
    return cast(dict[str, object], value)


def _provider_error_code(body: bytes) -> str | None:
    try:
        value = _provider_json(body)
    except OAuthError:
        return None
    error = value.get("error")
    return cast(str, error) if error in {"invalid_grant"} else None


def _normalize_provider_scopes(value: str) -> tuple[str, ...]:
    scopes = tuple(sorted(set(value.split())))
    if (
        not scopes
        or len(scopes) > _MAX_SCOPES
        or any(not scope or len(scope) > _MAX_SCOPE_CHARACTERS for scope in scopes)
    ):
        raise OAuthError()
    return scopes


__all__ = [
    "CredentialStore",
    "DisconnectResult",
    "GoogleOAuthClient",
    "OAuthCredentialRecord",
    "OAuthError",
    "OAuthTokenSet",
]
