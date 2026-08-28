"""Bounded HTTP for provider-owned, constructor-fixed HTTPS origins."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
import math
import time
from types import MappingProxyType
from typing import Literal
from urllib.parse import unquote, urlsplit

import httpx

from kaji.integrations.errors import IntegrationPolicyError, IntegrationTransportError
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
    record_metric,
    start_span,
)
from kaji.runtime.agents.cancellation import CancelledError
from kaji.runtime.context import ToolExecutionContext


_DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
_MAX_RESPONSE_HEADER_FIELDS = 64
_MAX_RESPONSE_HEADER_BYTES = 64 * 1024
_FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True, slots=True)
class _FixedOriginPolicy:
    origin: str
    integration: Literal["github", "gmail"]
    timeout_seconds: float = 10.0
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    allowed_methods: tuple[str, ...] = ("GET", "POST")


@dataclass(frozen=True, slots=True)
class IntegrationResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def _policy_error() -> IntegrationPolicyError:
    return IntegrationPolicyError()


def _response_limit() -> IntegrationTransportError:
    return IntegrationTransportError(
        "INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded"
    )


def _validated_origin(value: str) -> str:
    if not isinstance(value, str):
        raise _policy_error()
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise _policy_error()
    origin = f"https://{parsed.hostname.lower()}"
    if parsed.port is not None:
        origin += f":{parsed.port}"
    return origin


def _validate_policy(policy: _FixedOriginPolicy) -> tuple[str, frozenset[str]]:
    origin = _validated_origin(policy.origin)
    if (
        isinstance(policy.timeout_seconds, bool)
        or not isinstance(policy.timeout_seconds, (int, float))
        or not math.isfinite(float(policy.timeout_seconds))
        or policy.timeout_seconds <= 0
    ):
        raise _policy_error()
    if (
        isinstance(policy.max_response_bytes, bool)
        or not isinstance(policy.max_response_bytes, int)
        or policy.max_response_bytes < 1
    ):
        raise _policy_error()
    methods = tuple(policy.allowed_methods)
    if not methods or any(method not in {"GET", "POST"} for method in methods):
        raise _policy_error()
    return origin, frozenset(methods)


def _validated_target(origin: str, path_and_query: str) -> str:
    if (
        not isinstance(path_and_query, str)
        or not path_and_query.startswith("/")
        or path_and_query.startswith("//")
        or "\\" in path_and_query
        or "#" in path_and_query
    ):
        raise _policy_error()
    path = path_and_query.split("?", 1)[0]
    try:
        decoded_path = unquote(path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        raise _policy_error() from None
    if decoded_path.startswith("//") or "\\" in decoded_path:
        raise _policy_error()
    target = origin + path_and_query
    parsed = urlsplit(target)
    if f"{parsed.scheme}://{parsed.netloc}" != origin:
        raise _policy_error()
    return target


def _validated_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise _policy_error()
    result: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise _policy_error()
        normalized = name.strip().lower()
        if (
            not normalized
            or normalized in _FORBIDDEN_REQUEST_HEADERS
            or normalized.startswith("proxy-")
            or "\r" in name
            or "\n" in name
            or "\r" in value
            or "\n" in value
        ):
            raise _policy_error()
        result[normalized] = value
    return result


def _bounded_response_headers(headers: httpx.Headers) -> Mapping[str, str]:
    items = headers.multi_items()
    if len(items) > _MAX_RESPONSE_HEADER_FIELDS:
        raise _response_limit()
    size = sum(len(name.encode()) + len(value.encode()) for name, value in items)
    if size > _MAX_RESPONSE_HEADER_BYTES:
        raise _response_limit()
    content_lengths = headers.get_list("content-length")
    if content_lengths:
        if len(content_lengths) != 1 or not content_lengths[0].isdigit():
            raise _response_limit()
    return MappingProxyType({name.lower(): value for name, value in items})


class FixedOriginClient:
    """Pooled client whose production construction fixes one provider origin."""

    def __init__(
        self,
        policy: _FixedOriginPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
        monotonic_now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._origin, self._allowed_methods = _validate_policy(policy)
        self._policy = policy
        self._metrics_sink = metrics_sink
        self._trace_sink = trace_sink
        self._monotonic_now = monotonic_now
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=None,
            follow_redirects=False,
            trust_env=False,
        )

    @classmethod
    def for_github(
        cls,
        *,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
    ) -> FixedOriginClient:
        return cls(
            _FixedOriginPolicy("https://api.github.com", "github"),
            metrics_sink=metrics_sink,
            trace_sink=trace_sink,
        )

    @classmethod
    def for_gmail(
        cls,
        *,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
    ) -> FixedOriginClient:
        return cls(
            _FixedOriginPolicy("https://gmail.googleapis.com", "gmail"),
            metrics_sink=metrics_sink,
            trace_sink=trace_sink,
        )

    @classmethod
    def _for_test(
        cls,
        origin: str,
        *,
        transport: httpx.AsyncBaseTransport,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        allowed_methods: tuple[str, ...] = ("GET", "POST"),
        integration: Literal["github", "gmail"] = "github",
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
        monotonic_now: Callable[[], float] = time.monotonic,
    ) -> FixedOriginClient:
        return cls(
            _FixedOriginPolicy(
                origin,
                integration,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
                allowed_methods=allowed_methods,
            ),
            transport=transport,
            metrics_sink=metrics_sink,
            trace_sink=trace_sink,
            monotonic_now=monotonic_now,
        )

    async def request(
        self,
        path_and_query: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
        context: ToolExecutionContext,
    ) -> IntegrationResponse:
        started = self._monotonic_now()
        operation_label = "read" if method == "GET" else "mutation"
        span = start_span(
            self._trace_sink,
            "kaji.integration.request",
            {
                "integration.name": self._policy.integration,
                "integration.operation": operation_label,
                "http.status_family": "none",
            },
        )
        outcome = "error"
        try:
            if method not in self._allowed_methods or (
                body is not None and not isinstance(body, bytes)
            ):
                raise _policy_error()
            target = _validated_target(self._origin, path_and_query)
            request_headers = _validated_request_headers(headers)
            context.cancellation_token.raise_if_cancelled()
            remaining = self._policy.timeout_seconds
            if context.deadline_monotonic is not None:
                remaining = min(
                    remaining,
                    context.deadline_monotonic - time.monotonic(),
                )
            if remaining <= 0:
                raise TimeoutError("Integration request timed out")

            request_task = asyncio.create_task(
                self._request_once(target, method, request_headers, body)
            )
            cancelled = asyncio.create_task(context.cancellation_token.wait())
            try:
                done, _ = await asyncio.wait(
                    {request_task, cancelled},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if request_task in done:
                    response = request_task.result()
                    span.set_attribute(
                        "http.status_family",
                        (
                            f"{response.status // 100}xx"
                            if 100 <= response.status <= 599
                            else "none"
                        ),
                    )
                    outcome = "success" if 200 <= response.status < 300 else "error"
                    return response
                request_task.cancel()
                with suppress(asyncio.CancelledError):
                    await request_task
                if cancelled in done or context.cancellation_token.is_cancelled:
                    raise CancelledError("Integration request cancelled")
                raise TimeoutError("Integration request timed out")
            finally:
                cancelled.cancel()
                with suppress(asyncio.CancelledError):
                    await cancelled
        except BaseException as error:
            if isinstance(error, (asyncio.CancelledError, CancelledError)):
                outcome = "cancelled"
            span.record_error(error)
            raise
        finally:
            record_metric(
                self._metrics_sink,
                "kaji.integration.request_ms",
                max(0.0, (self._monotonic_now() - started) * 1_000),
                integration=self._policy.integration,
                operation=operation_label,
                outcome=outcome,
            )
            span.end()

    async def _request_once(
        self,
        target: str,
        method: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> IntegrationResponse:
        async with self._client.stream(
            method,
            target,
            headers=headers,
            content=body,
        ) as response:
            bounded_headers = _bounded_response_headers(response.headers)
            if 300 <= response.status_code < 400:
                raise IntegrationTransportError(
                    "INTEGRATION_REDIRECT_REJECTED", "redirect_rejected"
                )
            content_length = bounded_headers.get("content-length")
            if (
                content_length is not None
                and int(content_length) > self._policy.max_response_bytes
            ):
                raise _response_limit()
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._policy.max_response_bytes:
                    raise _response_limit()
                chunks.append(chunk)
            return IntegrationResponse(
                status=response.status_code,
                headers=bounded_headers,
                body=b"".join(chunks),
            )

    async def aclose(self) -> None:
        await self._client.aclose()
