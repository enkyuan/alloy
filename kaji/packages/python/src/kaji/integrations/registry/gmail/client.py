"""Bounded Gmail REST client for the authenticated user's mailbox."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Mapping, Sequence
import json
import math
import re
import time
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote

from kaji.infra.events.errors import DurableJsonLimitError, InvalidDurableValueError
from kaji.infra.events.json import canonical_json, durable_json_snapshot
from kaji.infra.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationExecutionError,
    IntegrationPolicyError,
    IntegrationRateLimitedError,
    IntegrationTransportError,
    IntegrationTransientReadError,
)
from kaji.integrations.fixed_origin import IntegrationResponse
from kaji.runtime.agents.cancellation import CancelledError
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools.execution import ToolExecutionError

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_LIST_RESULT_BYTES = 32 * 1024
_MAX_BODY_BYTES = 48 * 1024
_MAX_HEADER_VALUE_BYTES = 2 * 1024
_MAX_RAW_MESSAGE_BYTES = 1_048_576
_MAX_TOKEN_CHARACTERS = 4_096
_MAX_PAGE_TOKEN_BYTES = 2_048
_MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
# base64url alphabet (RFC 4648 §5), unpadded — provider payloads must match exactly.
_BASE64URL = re.compile(r"[A-Za-z0-9_-]*")
# Header names we surface, lowercased. Everything else is dropped as noise.
_SURFACED_HEADERS = ("from", "to", "cc", "subject", "date")

_Sleep = Callable[[float], Awaitable[None]]
_Monotonic = Callable[[], float]
_Route = Literal["list_messages", "get_message", "send_message"]


class _GmailHttp(Protocol):
    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: ToolExecutionContext,
    ) -> IntegrationResponse: ...


class _ProviderShapeError(ValueError):
    pass


class _UnknownMutationError(IntegrationTransportError):
    def __init__(self) -> None:
        super().__init__("TOOL_EXECUTION_FAILED", "gmail_mutation_unknown")


def _policy_error() -> IntegrationPolicyError:
    return IntegrationPolicyError()


def _auth_error() -> IntegrationAuthRequiredError:
    return IntegrationAuthRequiredError("gmail_grant_missing")


def _api_error() -> IntegrationExecutionError:
    return IntegrationExecutionError("api_rejected")


def _transient_error() -> IntegrationTransientReadError:
    return IntegrationTransientReadError()


def _rate_error() -> IntegrationRateLimitedError:
    return IntegrationRateLimitedError()


def _require_message_id(value: object) -> str:
    # Caller-supplied id: a bad value is caller error -> policy.
    if not isinstance(value, str) or not _MESSAGE_ID.fullmatch(value):
        raise _policy_error()
    return value


def _provider_message_id(value: object) -> str:
    # Provider-returned id: a bad value is a provider-shape problem -> transient
    # read, matching the TypeScript client's providerMessageId().
    if not isinstance(value, str) or not _MESSAGE_ID.fullmatch(value):
        raise _ProviderShapeError()
    return value


def _policy_string(value: object, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise _policy_error()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _policy_error() from None
    return value


def _policy_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _policy_error()
    return value


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise _ProviderShapeError() from None


def _truncate_utf8(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise _ProviderShapeError() from None
    if len(encoded) <= maximum:
        return value
    return encoded[:maximum].decode("utf-8", errors="ignore")


def _object(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise _ProviderShapeError()
    return cast(dict[str, Any], value)


def _array(value: object) -> list[Any]:
    if type(value) is not list:
        raise _ProviderShapeError()
    return cast(list[Any], value)


def _provider_character_string(value: object, *, minimum: int = 0, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise _ProviderShapeError()
    _utf8_size(value)
    return value


def _provider_integer(
    value: object, *, minimum: int = 0, maximum: int = _MAX_SAFE_INTEGER
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _ProviderShapeError()
    return value


def _normalized_token(value: object) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise _auth_error()
    token = value.strip()
    if not token or len(token) > _MAX_TOKEN_CHARACTERS:
        raise _auth_error()
    try:
        token.encode("utf-8")
    except UnicodeEncodeError:
        raise _auth_error() from None
    return token


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        delay = float(raw)
    except ValueError:
        return None
    if not math.isfinite(delay) or not 0 <= delay <= 2:
        return None
    return delay


def _is_rate_limited(response: IntegrationResponse) -> bool:
    return response.status == 429 or (
        response.status == 403 and _retry_after(response.headers) is not None
    )


def _b64url_decode(value: str) -> bytes:
    """Decode Gmail's base64url (RFC 4648 §5, unpadded) payloads, strictly.

    ``urlsafe_b64decode`` silently drops non-alphabet bytes, so pre-check the
    alphabet before decoding to reject malformed provider payloads.
    """
    if not _BASE64URL.fullmatch(value):
        raise _ProviderShapeError()
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        raise _ProviderShapeError() from None


def _validate_list_input(
    query: object, page_size: object, page_token: object = None
) -> None:
    _policy_integer(page_size, minimum=1, maximum=100)
    if query is not None:
        _policy_string(query, minimum=1, maximum=1_024)
    if page_token is not None:
        _policy_string(page_token, minimum=1, maximum=_MAX_PAGE_TOKEN_BYTES)


def _validate_raw_message(raw: object) -> str:
    # `raw` is the caller's RFC 2822 message, already base64url-encoded. We keep
    # it opaque (Gmail parses it) but bound size and confirm it decodes. Decode
    # failures here are caller error -> policy, not provider shape. Reject
    # non-alphabet input strictly (urlsafe_b64decode would silently drop it).
    value = _policy_string(raw, minimum=1, maximum=_MAX_RAW_MESSAGE_BYTES)
    if not _BASE64URL.fullmatch(value):
        raise _policy_error()
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        raise _policy_error() from None
    if not decoded or len(decoded) > _MAX_RAW_MESSAGE_BYTES:
        raise _policy_error()
    return value


def _route_for(
    *,
    method: Literal["GET", "POST"],
    path: str,
    query: Mapping[str, str | int] | None,
    body: Mapping[str, object] | None,
    mutation: bool,
) -> _Route:
    base = "/gmail/v1/users/me/messages"
    if method == "GET" and not mutation and path == base:
        if (
            query is None
            or set(query) - {"q", "maxResults", "pageToken"}
            or body is not None
        ):
            raise _policy_error()
        _validate_list_input(
            query.get("q"), query.get("maxResults"), query.get("pageToken")
        )
        return "list_messages"
    if method == "POST" and mutation and path == base + "/send":
        if query is not None or body is None or set(body) != {"raw"}:
            raise _policy_error()
        _validate_raw_message(body["raw"])
        return "send_message"
    if method == "GET" and not mutation and path.startswith(base + "/"):
        if body is not None or (query is not None and set(query) - {"format"}):
            raise _policy_error()
        _require_message_id(path.removeprefix(base + "/"))
        if query and query.get("format") != "full":
            raise _policy_error()
        return "get_message"
    raise _policy_error()


class GmailClient:
    def __init__(
        self,
        *,
        token_for: Callable[[ToolExecutionContext], Awaitable[str]],
        http: _GmailHttp,
        _sleep: _Sleep = asyncio.sleep,
        _monotonic: _Monotonic = time.monotonic,
    ) -> None:
        if not callable(token_for) or not callable(_sleep) or not callable(_monotonic):
            raise _policy_error()
        self._token_for = token_for
        self._http = http
        self._sleep = _sleep
        self._monotonic = _monotonic

    async def list_messages(
        self,
        context: ToolExecutionContext,
        *,
        query: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
    ) -> Mapping[str, object]:
        _validate_list_input(query, max_results, page_token)
        request_query: dict[str, str | int] = {"maxResults": max_results}
        if query is not None:
            request_query["q"] = query
        if page_token is not None:
            request_query["pageToken"] = page_token
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                path="/gmail/v1/users/me/messages",
                query=request_query,
            ),
        )

    async def get_message(
        self,
        context: ToolExecutionContext,
        *,
        message_id: str,
    ) -> Mapping[str, object]:
        identifier = _require_message_id(message_id)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="GET",
                path=f"/gmail/v1/users/me/messages/{identifier}",
                query={"format": "full"},
            ),
        )

    async def send_message(
        self,
        context: ToolExecutionContext,
        *,
        raw: str,
    ) -> Mapping[str, object]:
        _validate_raw_message(raw)
        return cast(
            Mapping[str, object],
            await self.request_json(
                context,
                method="POST",
                path="/gmail/v1/users/me/messages/send",
                body={"raw": raw},
                mutation=True,
            ),
        )

    async def request_json(
        self,
        context: ToolExecutionContext,
        *,
        method: Literal["GET", "POST"],
        path: str,
        query: Mapping[str, str | int] | None = None,
        body: Mapping[str, object] | None = None,
        mutation: bool = False,
    ) -> Mapping[str, object] | Sequence[object]:
        route = _route_for(
            method=method, path=path, query=query, body=body, mutation=mutation
        )
        path_and_query = path + _query_string(query)
        request_body = (
            None
            if body is None
            else canonical_json(body, subject="integration request body").encode()
        )
        headers = {"accept": "application/json"}

        context.cancellation_token.raise_if_cancelled()
        try:
            token = await self._token_for(context)
        except asyncio.CancelledError:
            raise
        except ToolExecutionError:
            raise
        except Exception:
            raise _auth_error() from None
        context.cancellation_token.raise_if_cancelled()
        headers["authorization"] = f"Bearer {_normalized_token(token)}"
        if request_body is not None:
            headers["content-type"] = "application/json"

        response: IntegrationResponse
        for attempt in range(2):
            try:
                response = await self._http.request(
                    path_and_query,
                    method=method,
                    headers=headers,
                    body=request_body,
                    context=context,
                )
            except (asyncio.CancelledError, TimeoutError):
                raise
            except ToolExecutionError:
                raise
            except Exception:
                if mutation:
                    raise _UnknownMutationError() from None
                raise _transient_error() from None

            if _is_rate_limited(response):
                delay = _retry_after(response.headers)
                if (
                    method == "GET"
                    and attempt == 0
                    and delay is not None
                    and self._deadline_allows(context, delay)
                ):
                    await self._sleep_before_retry(context, delay)
                    continue
                raise _rate_error()
            break
        else:  # pragma: no cover - bounded loop always breaks or raises
            raise _rate_error()

        if response.status == 401:
            raise _auth_error()
        if response.status == 403:
            raise _api_error()
        if not 200 <= response.status < 300:
            if mutation and response.status >= 500:
                raise _UnknownMutationError()
            if response.status in {404, 422} or 400 <= response.status < 500:
                raise _api_error()
            if mutation:
                raise _UnknownMutationError()
            raise _transient_error()

        try:
            decoded = response.body.decode("utf-8", errors="strict")
            document = json.loads(
                decoded,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            normalized = self._normalize(route, document)
            # ponytail: Python bounds the message result at the shared 64K
            # durable-tool-result limit. The TS SDK uses its own 60K model-result
            # convention (registry/gmail/client.ts); the 4K gap is a deliberate
            # per-SDK ceiling, not a bug. Unify only if a conformance case requires
            # an exact cross-SDK byte boundary.
            return cast(
                Mapping[str, object] | Sequence[object],
                durable_json_snapshot(
                    normalized,
                    subject="tool_result",
                    max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
                ),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            _ProviderShapeError,
            InvalidDurableValueError,
            DurableJsonLimitError,
        ):
            if mutation:
                raise _UnknownMutationError() from None
            raise _transient_error() from None

    def _deadline_allows(self, context: ToolExecutionContext, delay: float) -> bool:
        return (
            context.deadline_monotonic is None
            or context.deadline_monotonic - self._monotonic() > delay
        )

    async def _sleep_before_retry(
        self, context: ToolExecutionContext, delay: float
    ) -> None:
        context.cancellation_token.raise_if_cancelled()

        async def sleep() -> None:
            await self._sleep(delay)

        sleeping = asyncio.create_task(sleep())
        cancelled = asyncio.create_task(context.cancellation_token.wait())
        try:
            done, _ = await asyncio.wait(
                {sleeping, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done or context.cancellation_token.is_cancelled:
                sleeping.cancel()
                raise CancelledError("Integration request cancelled")
            await sleeping
        finally:
            for task in (sleeping, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleeping, cancelled, return_exceptions=True)

    def _normalize(self, route: _Route, document: object) -> object:
        if route == "list_messages":
            return self._normalize_list(document)
        if route == "get_message":
            return self._normalize_message(document)
        return self._normalize_send(document)

    def _normalize_list(self, document: object) -> object:
        root = _object(document)
        raw_messages = root.get("messages")
        rows = [] if raw_messages is None else _array(raw_messages)
        items: list[dict[str, object]] = []
        for value in rows[:100]:
            message = _object(value)
            items.append(
                {
                    "id": _provider_message_id(message.get("id")),
                    "thread_id": _provider_message_id(message.get("threadId")),
                }
            )
        result: dict[str, object] = {"messages": items}
        estimate = root.get("resultSizeEstimate")
        if estimate is not None:
            result["result_size_estimate"] = _provider_integer(estimate)
        next_page_token = root.get("nextPageToken")
        if next_page_token is not None:
            result["next_page_token"] = _provider_character_string(
                next_page_token, minimum=1, maximum=_MAX_PAGE_TOKEN_BYTES
            )
        try:
            return durable_json_snapshot(
                result, subject="tool_result", max_bytes=_MAX_LIST_RESULT_BYTES
            )
        except (InvalidDurableValueError, DurableJsonLimitError):
            raise _ProviderShapeError() from None

    def _normalize_message(self, document: object) -> object:
        root = _object(document)
        payload = _object(root.get("payload"))
        headers: dict[str, str] = {}
        for value in _array(payload.get("headers", [])):
            header = _object(value)
            name = _provider_character_string(
                header.get("name"), minimum=1, maximum=256
            )
            lowered = name.lower()
            if lowered in _SURFACED_HEADERS and lowered not in headers:
                headers[lowered] = _truncate_utf8(
                    _provider_character_string(
                        header.get("value"), maximum=_MAX_HEADER_VALUE_BYTES
                    ),
                    _MAX_HEADER_VALUE_BYTES,
                )
        body_text, truncated = self._extract_body(payload)
        return {
            "id": _provider_message_id(root.get("id")),
            "thread_id": _provider_message_id(root.get("threadId")),
            "snippet": _truncate_utf8(
                _provider_character_string(
                    root.get("snippet", ""), maximum=_MAX_RAW_MESSAGE_BYTES
                ),
                1_024,
            ),
            "headers": headers,
            "body": body_text,
            "body_truncated": truncated,
        }

    def _extract_body(self, payload: dict[str, Any]) -> tuple[str, bool]:
        """Return the first text/plain part's decoded body, bounded.

        Gmail nests parts arbitrarily; we do one depth-bounded walk and take the
        first text/plain leaf. HTML-only mail yields an empty body.
        """
        for part in self._walk_parts(payload, depth=0):
            if part.get("mimeType") != "text/plain":
                continue
            body = part.get("body")
            if type(body) is not dict:
                continue
            data = body.get("data")
            if not isinstance(data, str) or not data:
                continue
            decoded = _b64url_decode(data)
            if len(decoded) > _MAX_BODY_BYTES:
                try:
                    text = decoded[:_MAX_BODY_BYTES].decode("utf-8", errors="ignore")
                except UnicodeDecodeError:  # pragma: no cover - errors=ignore
                    raise _ProviderShapeError() from None
                return _truncate_utf8(text, _MAX_BODY_BYTES), True
            try:
                text = decoded.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise _ProviderShapeError() from None
            return text, False
        return "", False

    def _walk_parts(self, part: dict[str, Any], *, depth: int) -> list[dict[str, Any]]:
        # ponytail: depth cap 10 stops a hostile deeply-nested MIME tree; real
        # mail nests 2-3 levels. Raise if Gmail ever legitimately exceeds it.
        if depth > 10:
            raise _ProviderShapeError()
        result = [part]
        raw_parts = part.get("parts")
        if raw_parts is not None:
            for child in _array(raw_parts):
                result.extend(self._walk_parts(_object(child), depth=depth + 1))
        return result

    def _normalize_send(self, document: object) -> object:
        message = _object(document)
        return {
            "id": _provider_message_id(message.get("id")),
            "thread_id": _provider_message_id(message.get("threadId")),
        }


def _encode_component(value: str | int) -> str:
    try:
        return quote(str(value), safe="-._~", encoding="utf-8", errors="strict")
    except UnicodeError:
        raise _policy_error() from None


def _query_string(query: Mapping[str, str | int] | None) -> str:
    if query is None or not query:
        return ""
    if not isinstance(query, Mapping):
        raise _policy_error()
    pairs: list[str] = []
    for key in sorted(query):
        value = query[key]
        if not isinstance(key, str) or not key or type(value) not in {str, int}:
            raise _policy_error()
        pairs.append(f"{_encode_component(key)}={_encode_component(value)}")
    return "?" + "&".join(pairs)
