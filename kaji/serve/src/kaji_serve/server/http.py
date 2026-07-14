"""Shared HTTP client primitives for external services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import httpx

from kaji_serve.server.errors import (
    ServiceAPIError,
    ServiceNetworkError,
    classify_http_error,
)
from kaji_serve.server.lifecycle import register_close_handler

logger = logging.getLogger(__name__)


class HTTPService:
    """Base reusable HTTP client/service primitives."""

    SERVICE_NAME = "service"
    DEFAULT_TIMEOUT_SECONDS = 10.0
    DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
    DEFAULT_MAX_CONNECTIONS = 60
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
    DEFAULT_KEEPALIVE_EXPIRY_SECONDS = 30.0
    DEFAULT_RETRY_ATTEMPTS = 2
    DEFAULT_RETRY_BACKOFF_SECONDS = 0.2
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
    CIRCUIT_BREAKER_OPEN_SECONDS = 30.0

    def __init__(
        self,
        *,
        max_connections: int | None = None,
        max_keepalive_connections: int | None = None,
        keepalive_expiry_seconds: float | None = None,
        follow_redirects: bool = False,
    ) -> None:
        self._http_client: httpx.AsyncClient | None = None
        self._timeout = httpx.Timeout(
            self.DEFAULT_TIMEOUT_SECONDS,
            connect=self.DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
        self._limits = httpx.Limits(
            max_connections=max_connections or self.DEFAULT_MAX_CONNECTIONS,
            max_keepalive_connections=max_keepalive_connections
            or self.DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=keepalive_expiry_seconds
            or self.DEFAULT_KEEPALIVE_EXPIRY_SECONDS,
        )
        self._follow_redirects = follow_redirects
        self._consecutive_failures = 0
        self._circuit_open_until: datetime | None = None
        register_close_handler(self._registry_key, self.close)

    @property
    def _registry_key(self) -> str:
        return f"{self.__class__.__module__}.{self.__class__.__qualname__}"

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=self._limits,
                follow_redirects=self._follow_redirects,
            )
        return self._http_client

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[httpx.AsyncClient]:
        yield self._get_http_client()

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @staticmethod
    def _auth_headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        now = datetime.now(timezone.utc)
        if now >= self._circuit_open_until:
            self._circuit_open_until = None
            self._consecutive_failures = 0
            return False
        return True

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    def _record_failure(self, *, action: str) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures < self.CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            return

        self._circuit_open_until = datetime.now(timezone.utc) + timedelta(
            seconds=self.CIRCUIT_BREAKER_OPEN_SECONDS
        )
        self._consecutive_failures = 0
        logger.warning(
            "%s circuit opened for %.1fs after repeated failures during %s",
            self.SERVICE_NAME,
            self.CIRCUIT_BREAKER_OPEN_SECONDS,
            action,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        action: str,
        expected_status: Iterable[int] = (200,),
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Mapping[str, Any] | None = None,
        retry_attempts: int | None = None,
    ) -> httpx.Response:
        if self._is_circuit_open():
            raise ServiceNetworkError(
                service=self.SERVICE_NAME,
                action=action,
                message=f"{self.SERVICE_NAME} circuit breaker is open",
            )

        expected_codes = tuple(expected_status)
        attempts = max(retry_attempts or self.DEFAULT_RETRY_ATTEMPTS, 1)

        for attempt in range(1, attempts + 1):
            try:
                response = await self._get_http_client().request(
                    method=method,
                    url=url,
                    headers=dict(headers) if headers else None,  # type: ignore
                    params=dict(params) if params else None,  # type: ignore
                    json=json,
                    data=dict(data) if data else None,  # type: ignore
                )
            except httpx.HTTPError:
                typed_error = ServiceNetworkError(
                    service=self.SERVICE_NAME,
                    action=action,
                    message=f"{self.SERVICE_NAME} {action} request failed",
                )
                if attempt < attempts:
                    logger.warning(
                        "Retrying %s %s after network error (%s/%s)",
                        self.SERVICE_NAME,
                        action,
                        attempt,
                        attempts,
                    )
                    await asyncio.sleep(self.DEFAULT_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                self._record_failure(action=action)
                raise typed_error from None

            if response.status_code in expected_codes:
                self._record_success()
                return response

            typed_error = classify_http_error(
                service=self.SERVICE_NAME,
                action=action,
                status_code=response.status_code,
            )
            should_retry = (
                attempt < attempts
                and response.status_code in self.RETRYABLE_STATUS_CODES
            )
            if should_retry:
                logger.warning(
                    "Retrying %s %s after status %s (%s/%s)",
                    self.SERVICE_NAME,
                    action,
                    response.status_code,
                    attempt,
                    attempts,
                )
                await asyncio.sleep(self.DEFAULT_RETRY_BACKOFF_SECONDS * attempt)
                continue

            logger.warning(
                "%s %s failed with status %s",
                self.SERVICE_NAME,
                action,
                response.status_code,
            )
            if (
                response.status_code in self.RETRYABLE_STATUS_CODES
                or response.status_code >= 500
            ):
                self._record_failure(action=action)
            raise typed_error

        raise ServiceAPIError(
            service=self.SERVICE_NAME,
            action=action,
            message=f"{self.SERVICE_NAME} {action} failed",
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        action: str,
        expected_status: Iterable[int] = (200,),
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Mapping[str, Any] | None = None,
        response_key: str | None = None,
        default: Any = None,
        retry_attempts: int | None = None,
    ) -> Any:
        response = await self._request(
            method=method,
            url=url,
            action=action,
            expected_status=expected_status,
            headers=headers,
            params=params,
            json=json,
            data=data,
            retry_attempts=retry_attempts,
        )
        if not response.content:
            return default

        try:
            payload = response.json()
        except ValueError:
            raise ServiceAPIError(
                service=self.SERVICE_NAME,
                action=action,
                message=f"{self.SERVICE_NAME} {action} returned invalid JSON",
                status_code=response.status_code,
            ) from None

        if response_key is None:
            return payload

        if not isinstance(payload, dict):
            raise ServiceAPIError(
                service=self.SERVICE_NAME,
                action=action,
                message=f"{self.SERVICE_NAME} {action} returned invalid payload shape",
                status_code=response.status_code,
            )
        return payload.get(response_key, default)

    async def _request_no_content(
        self,
        method: str,
        url: str,
        *,
        action: str,
        expected_status: Iterable[int] = (200,),
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Mapping[str, Any] | None = None,
        retry_attempts: int | None = None,
    ) -> None:
        await self._request(
            method=method,
            url=url,
            action=action,
            expected_status=expected_status,
            headers=headers,
            params=params,
            json=json,
            data=data,
            retry_attempts=retry_attempts,
        )
