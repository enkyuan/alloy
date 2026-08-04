"""Gmail tools backed by the provider-fixed bounded REST client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast

from kaji.integrations.fixed_origin import FixedOriginClient
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
)
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.integrations.base import Integration
from kaji.runtime.tools.registry import ToolHandler, ToolSpec

from .client import GmailClient


class _GmailClientLike(Protocol):
    async def list_messages(
        self,
        context: ToolExecutionContext,
        *,
        query: str | None = None,
        max_results: int = 10,
    ) -> Mapping[str, object]: ...
    async def get_message(
        self,
        context: ToolExecutionContext,
        *,
        message_id: str,
    ) -> Mapping[str, object]: ...
    async def send_message(
        self,
        context: ToolExecutionContext,
        *,
        raw: str,
    ) -> Mapping[str, object]: ...


def _parameters(
    properties: dict[str, object], required: list[str]
) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            name="list_messages",
            description="List messages in the authenticated user's mailbox.",
            parameters=_parameters(
                {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1_024,
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 10,
                    },
                },
                [],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
        ToolSpec(
            name="get_message",
            description="Get a message from the authenticated user's mailbox.",
            parameters=_parameters(
                {
                    "message_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                },
                ["message_id"],
            ),
            risk="read",
            parallel_safe=True,
            timeout_ms=10_000,
        ),
        ToolSpec(
            name="send_message",
            description=(
                "Send an email as the authenticated user. `raw` is the complete "
                "RFC 2822 message, base64url-encoded."
            ),
            parameters=_parameters(
                {
                    "raw": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1_048_576,
                    },
                },
                ["raw"],
            ),
            risk="external_effect",
            parallel_safe=False,
            timeout_ms=15_000,
        ),
    )


class GmailIntegration(Integration):
    def __init__(
        self,
        client: _GmailClientLike,
        *,
        close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._close = close
        self._close_lock = asyncio.Lock()

    @property
    def namespace(self) -> str:
        return "gmail"

    def tools(self) -> list[tuple[ToolSpec, ToolHandler]]:
        pairs: list[tuple[ToolSpec, ToolHandler]] = []
        for spec in _specs():
            method = cast(
                Callable[..., Awaitable[Mapping[str, object]]],
                getattr(self._client, spec.name),
            )

            async def handler(
                context: ToolExecutionContext,
                arguments: dict[str, Any],
                *,
                _method: Callable[..., Awaitable[Mapping[str, object]]] = method,
            ) -> dict[str, object]:
                return dict(await _method(context, **arguments))

            pairs.append((spec, handler))
        return pairs

    async def aclose(self) -> None:
        async with self._close_lock:
            close = self._close
            if close is None:
                return
            await close()
            self._close = None


def create_gmail_integration(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    metrics_sink: MetricsSink = NOOP_METRICS,
    trace_sink: TraceSink = NOOP_TRACE,
) -> GmailIntegration:
    http = FixedOriginClient.for_gmail(
        metrics_sink=metrics_sink,
        trace_sink=trace_sink,
    )
    return GmailIntegration(
        GmailClient(token_for=token_for, http=http),
        close=http.aclose,
    )


def _create_gmail_integration_for_test(
    *,
    token_for: Callable[[ToolExecutionContext], Awaitable[str]],
    http: FixedOriginClient,
) -> GmailIntegration:
    return GmailIntegration(GmailClient(token_for=token_for, http=http))


class _InspectionClient:
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[Mapping[str, object]]]:
        async def reject(*_args: object, **_kwargs: object) -> Mapping[str, object]:
            raise RuntimeError("inspection dependencies must not execute")

        return reject


def inspect_integration() -> GmailIntegration:
    return GmailIntegration(cast(_GmailClientLike, _InspectionClient()))
