from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, cast

import httpx
import pytest

from kaji.infra.observability import Measurement
from kaji.infra.observability.protocols import record_metric, start_span
from kaji.integrations.fixed_origin import FixedOriginClient
from kaji.integrations.oauth import (
    GoogleOAuthClient,
    OAuthCredentialRecord,
    OAuthTokenSet,
)
from kaji.integrations.registry.github.github import create_github_integration
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.context import ToolInvocation
from kaji.runtime.context import ToolExecutionContext, TurnContext
from kaji.runtime.providers.mock import MockProvider
from kaji.runtime.tools.execution import ToolExecutionController
from kaji.runtime.tools.registry import ToolSpec


@dataclass
class Metrics:
    values: list[Measurement] = field(default_factory=list)

    def record(self, measurement: Measurement) -> None:
        self.values.append(measurement)


@dataclass
class Span:
    name: str
    attributes: dict[str, str]

    def set_attribute(self, name: str, value: str) -> None:
        self.attributes[name] = value

    def record_error(self, error: BaseException) -> None:
        _ = error

    def end(self) -> None:
        return None


@dataclass
class Trace:
    values: list[Span] = field(default_factory=list)

    def start_span(self, name: str, attributes: Any) -> Span:
        span = Span(name, dict(attributes))
        self.values.append(span)
        return span


def context() -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id="poison-principal-secret",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


@pytest.mark.asyncio
async def test_fixed_origin_emits_only_bounded_observability() -> None:
    metrics = Metrics()
    trace = Trace()
    ticks = iter((1.0, 1.001))
    client = FixedOriginClient._for_test(
        "https://api.github.com",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"ok")
        ),
        integration="github",
        metrics_sink=metrics,
        trace_sink=trace,
        monotonic_now=lambda: next(ticks),
    )

    await client.request(
        "/repos/private-owner/private-repo",
        method="GET",
        headers={"authorization": "Bearer private-token"},
        body=None,
        context=context(),
    )
    await client.aclose()

    assert len(metrics.values) == 1
    assert metrics.values[0].name == "kaji.integration.request_ms"
    assert metrics.values[0].value == pytest.approx(1.0)
    assert metrics.values[0].labels == {
        "integration": "github",
        "operation": "read",
        "outcome": "success",
    }
    assert trace.values[0].name == "kaji.integration.request"
    assert trace.values[0].attributes == {
        "integration.name": "github",
        "integration.operation": "read",
        "http.status_family": "2xx",
    }
    encoded = json.dumps([dict(metrics.values[0].labels), trace.values[0].attributes])
    assert all(
        secret not in encoded
        for secret in (
            "private-owner",
            "private-repo",
            "private-token",
            "poison-principal-secret",
        )
    )


class Storage:
    def __init__(self) -> None:
        self.record = OAuthCredentialRecord(
            1,
            "active",
            OAuthTokenSet(
                "private-access-token",
                "private-refresh-token",
                int((time.time() + 3_600) * 1_000),
                ("scope",),
            ),
        ).to_wire()

    def load(self) -> dict[str, object]:
        return self.record

    def save(self, data: dict[str, object]) -> None:
        self.record = data

    def delete(self) -> None:
        return None


@pytest.mark.asyncio
async def test_oauth_emits_bounded_auth_observability() -> None:
    metrics = Metrics()
    trace = Trace()
    storage = Storage()
    oauth = GoogleOAuthClient(
        client_id="client",
        scopes=("scope",),
        token_storage_for=lambda _principal: storage,
        metrics_sink=metrics,
        trace_sink=trace,
    )

    assert await oauth.access_token(context()) == "private-access-token"
    assert metrics.values[0].name == "kaji.integration.auth_ms"
    assert metrics.values[0].labels == {
        "integration": "gmail",
        "operation": "token",
        "outcome": "success",
    }
    assert trace.values[0].name == "kaji.integration.auth"
    assert trace.values[0].attributes == {
        "integration.name": "gmail",
        "integration.operation": "token",
        "http.status_family": "none",
    }
    encoded = json.dumps([dict(metrics.values[0].labels), trace.values[0].attributes])
    assert "private-access-token" not in encoded
    assert "private-refresh-token" not in encoded
    assert "poison-principal-secret" not in encoded


def test_integration_vocabulary_fails_closed() -> None:
    metrics = Metrics()
    trace = Trace()
    record_metric(
        metrics,
        cast(Any, "kaji.integration.request_ms"),
        1,
        integration="private",
        operation="read",
        outcome="success",
    )
    start_span(
        trace,
        "kaji.integration.request",
        {
            "integration.name": "private",
            "integration.operation": "read",
            "http.status_family": "2xx",
        },
    ).end()
    start_span(trace, "kaji.turn", cast(Any, {"principal.id": "secret"})).end()

    assert metrics.values == []
    assert trace.values == []


@pytest.mark.asyncio
async def test_turn_and_tool_spans_never_emit_the_principal() -> None:
    trace = Trace()
    runtime = (
        AgentBuilder().provider(MockProvider(reply="ok")).trace_sink(trace).build()
    )
    await runtime.turn(
        "prompt",
        context=TurnContext(principal_id="poison-principal-secret"),
    )

    invocation = ToolInvocation(name="echo", arguments={}, context=context())

    async def execute(_invocation: ToolInvocation) -> dict[str, bool]:
        return {"ok": True}

    async def started() -> None:
        return None

    controller = ToolExecutionController(trace_sink=trace)
    await controller.execute(
        invocation,
        ToolSpec(name="echo", description="echo", parameters={}, risk="read"),
        execute,
        started,
    )

    names = {span.name for span in trace.values}
    assert {"kaji.turn", "kaji.tool"}.issubset(names)
    assert "poison-principal-secret" not in repr(trace.values)


def test_github_production_factory_forwards_observability_sinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = Metrics()
    trace = Trace()
    captured: dict[str, object] = {}

    def requester(**options: object) -> object:
        captured.update(options)
        return object()

    monkeypatch.setattr(FixedOriginClient, "for_github", staticmethod(requester))

    async def token_for(_context: ToolExecutionContext) -> str:
        return "token"

    integration = create_github_integration(
        token_for=token_for,
        repositories=("octo/widgets",),
        metrics_sink=metrics,
        trace_sink=trace,
    )

    assert integration.namespace == "github"
    assert captured == {"metrics_sink": metrics, "trace_sink": trace}
