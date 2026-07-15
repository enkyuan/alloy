from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import logging
from typing import Any, cast

import pytest

from kaji.infra.events.errors import EventDeliveryError, EventStoreCapacityError
from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.infra.events.schemas import (
    SessionCreated,
    StoredKajiEvent,
    UserMessage,
    require_stored_event,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.observability import (
    InMemoryMetrics,
    Measurement,
    NOOP_METRICS,
    NOOP_TRACE,
    trace_span,
)
from kaji.infra.observability.protocols import (
    metric_error_code,
    record_metric,
    start_span,
)
from kaji.infra.observability.tracing import Span
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import ToolExecutionContext, ToolInvocation
from kaji.runtime.providers.mock import MockProvider
from kaji.runtime.sessions import EventTimeline
from kaji.runtime.tools.execution import ToolExecutionController
from kaji.runtime.tools.registry import ToolSpec


def test_in_memory_metrics_increment_and_reset():
    metrics = InMemoryMetrics()
    metrics.increment("requests")
    metrics.increment("requests", 2)
    assert metrics.get("requests") == 3
    metrics.reset()
    assert metrics.get("requests") == 0


def test_in_memory_metrics_rejects_negative_increment():
    metrics = InMemoryMetrics()
    with pytest.raises(ValueError, match="non-negative"):
        metrics.increment("bad", -1)


def test_measurements_have_canonical_units_and_closed_labels() -> None:
    measurement = Measurement(
        "kaji.turn.duration_ms",
        2,
        {"outcome": "completed"},
    )
    assert measurement.unit == "ms"
    with pytest.raises(ValueError, match="labels must be exactly"):
        Measurement(
            "kaji.turn.duration_ms",
            2,
            {"outcome": "completed", "session_id": "secret-session"},
        )

    metrics = InMemoryMetrics()
    metrics.record(Measurement("kaji.tool.active", 1))
    metrics.record(Measurement("kaji.tool.active", 0))
    assert metrics.get("kaji.tool.active") == 0
    with pytest.raises(ValueError, match="provider_family"):
        Measurement(
            "kaji.provider.duration_ms",
            2,
            {"provider_family": "secret-provider", "status": "success"},
        )
    assert (
        Measurement(
            "kaji.tool.duration_ms",
            2,
            {"outcome": "timeout", "error_code": "TURN_TIMEOUT"},
        ).labels["error_code"]
        == "TURN_TIMEOUT"
    )
    assert metric_error_code("TURN_TIMEOUT") == "TURN_TIMEOUT"


def test_throwing_observability_handles_are_best_effort_and_idempotent() -> None:
    class ThrowingMetrics:
        def record(self, measurement: Measurement) -> None:
            raise RuntimeError("metrics unavailable")

    class ThrowingSpan:
        ends = 0

        def set_attribute(self, name: str, value: str) -> None:
            raise RuntimeError("span unavailable")

        def record_error(self, error: BaseException) -> None:
            raise RuntimeError("span unavailable")

        def end(self) -> None:
            self.ends += 1
            raise RuntimeError("span unavailable")

    class Trace:
        def __init__(self) -> None:
            self.span = ThrowingSpan()

        def start_span(self, name: str, attributes: object) -> ThrowingSpan:
            return self.span

    record_metric(ThrowingMetrics(), "kaji.context.messages", 1)
    trace = Trace()
    span = start_span(trace, "kaji.turn", {"session.id": "session"})  # type: ignore[arg-type]
    span.set_attribute("turn.id", "turn")
    span.record_error(RuntimeError("private"))
    span.end()
    span.end()
    assert trace.span.ends == 1


def test_throwing_logger_does_not_break_observability_isolation() -> None:
    class ExplodingLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("logging unavailable")

    class ThrowingMetrics:
        def record(self, measurement: Measurement) -> None:
            raise RuntimeError("metrics unavailable")

    logger = logging.getLogger("kaji.infra.observability.protocols")
    previous_handlers = logger.handlers[:]
    previous_propagate = logger.propagate
    logger.handlers = [ExplodingLogHandler()]
    logger.propagate = False
    try:
        record_metric(ThrowingMetrics(), "kaji.context.messages", 1)
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagate


def test_trace_vocabulary_drops_dynamic_names_attributes_and_values() -> None:
    class RecordingSpan:
        def __init__(self) -> None:
            self.attributes: list[tuple[str, str]] = []

        def set_attribute(self, name: str, value: str) -> None:
            self.attributes.append((name, value))

        def record_error(self, error: BaseException) -> None:
            _ = error

        def end(self) -> None:
            return None

    class RecordingTrace:
        def __init__(self) -> None:
            self.starts = 0
            self.span = RecordingSpan()

        def start_span(self, name: str, attributes: object) -> RecordingSpan:
            self.starts += 1
            return self.span

    trace = RecordingTrace()
    dropped = start_span(
        trace,
        cast(Any, "prompt.secret"),
        {},
    )
    dropped.set_attribute("turn.id", "turn")
    assert trace.starts == 0

    span = start_span(
        trace,
        "kaji.turn",
        {"session.id": "session"},
    )
    span.set_attribute(cast(Any, "prompt"), "secret")
    span.set_attribute("turn.id", cast(Any, {"arguments": "secret"}))
    span.set_attribute("turn.id", "turn")
    assert trace.span.attributes == [("turn.id", "turn")]


def test_exact_noop_sinks_skip_measurement_and_span_allocation() -> None:
    record_metric(
        NOOP_METRICS,
        cast(Any, "dynamic.metric"),
        float("nan"),
        dynamic="secret",
    )
    span = start_span(
        NOOP_TRACE,
        cast(Any, "dynamic.span"),
        cast(Any, object()),
    )
    span.end()


def test_trace_span_records_duration():
    with trace_span("unit.test") as span:
        span.attributes["key"] = "value"
        assert isinstance(span, Span)
    assert span.end_time is not None
    assert span.duration_ms is not None
    assert span.duration_ms >= 0


def test_event_timeline_orders_and_projects_state():
    events = [
        require_stored_event(
            SessionCreated(session_id="s1", timestamp=2.0, sequence=1)
        ),
        require_stored_event(
            UserMessage(session_id="s1", content="hi", timestamp=1.0, sequence=2)
        ),
    ]
    timeline = EventTimeline(events)
    assert timeline.event_types() == ["session.created", "user.message"]
    assert timeline.sequences() == [1, 2]
    state = timeline.to_session_state()
    assert state.session_id == "s1"
    assert state.is_active is True


def test_event_timeline_empty_raises():
    with pytest.raises(ValueError, match="empty timeline"):
        EventTimeline([]).to_session_state()


def test_event_timeline_preserves_sequence_order_over_timestamps():
    events = [
        require_stored_event(
            SessionCreated(session_id="s1", timestamp=2.0, sequence=1)
        ),
        require_stored_event(
            UserMessage(session_id="s1", content="hi", timestamp=1.0, sequence=2)
        ),
    ]
    timeline = EventTimeline(events)
    assert timeline.event_types() == ["session.created", "user.message"]
    assert timeline.sequences() == [1, 2]


@pytest.mark.asyncio
async def test_runtime_records_closed_metrics_without_prompt_or_argument_labels() -> (
    None
):
    metrics = InMemoryMetrics()
    prompt_secret = "prompt-secret-must-not-be-a-label"
    runtime = (
        AgentBuilder().provider(MockProvider(reply="ok")).metrics_sink(metrics).build()
    )

    result = await runtime.turn(prompt_secret)

    names = {measurement.name for measurement in metrics.measurements}
    assert {
        "kaji.turn.queue_wait_ms",
        "kaji.turn.duration_ms",
        "kaji.turn.iterations",
        "kaji.provider.duration_ms",
        "kaji.provider.retries",
        "kaji.replay.input_events",
        "kaji.context.messages",
        "kaji.context.characters",
    }.issubset(names)
    serialized = repr(metrics.measurements)
    assert prompt_secret not in serialized
    assert result.session_id not in serialized
    provider = next(
        measurement
        for measurement in metrics.measurements
        if measurement.name == "kaji.provider.duration_ms"
    )
    assert provider.labels == {"provider_family": "custom", "status": "success"}


@pytest.mark.asyncio
async def test_tool_and_journal_metrics_cover_runtime_infrastructure() -> None:
    metrics = InMemoryMetrics()
    controller = ToolExecutionController(metrics_sink=metrics)
    token = CancellationToken()
    context = ToolExecutionContext(
        principal_id="principal-secret",
        session_id="session-secret",
        turn_id="turn-secret",
        request_id="request-secret",
        trace_id="trace-secret",
        tool_call_id="call-secret",
        idempotency_key="session-secret:call-secret",
        cancellation_token=token,
        deadline_monotonic=None,
        db=None,
        metadata={},
    )
    invocation = ToolInvocation(
        name="never-a-metric-label",
        arguments={"secret": "argument-secret"},
        context=context,
    )

    async def execute(call: ToolInvocation) -> dict[str, bool]:
        return {"ok": True}

    async def started() -> None:
        return None

    outcome = await controller.execute(
        invocation,
        ToolSpec(
            name="never-a-metric-label",
            description="tool",
            parameters={},
            risk="read",
        ),
        execute,
        started,
    )
    assert outcome.succeeded
    names = [measurement.name for measurement in metrics.measurements]
    assert "kaji.tool.queue_wait_ms" in names
    assert "kaji.tool.active" in names
    assert "kaji.tool.duration_ms" in names
    assert "argument-secret" not in repr(metrics.measurements)
    assert "call-secret" not in repr(metrics.measurements)

    class BrokenStore(InMemoryEventStore):
        async def append(self, event: Any) -> Any:
            raise RuntimeError("store unavailable")

    journal = InMemoryEventJournal(BrokenStore(), metrics_sink=metrics)
    with pytest.raises(EventDeliveryError):
        await journal.commit(SessionCreated(session_id="broken"))
    failure = next(
        measurement
        for measurement in reversed(metrics.measurements)
        if measurement.name == "kaji.journal.failures"
    )
    assert failure.labels == {"stage": "append"}


@pytest.mark.asyncio
async def test_split_journal_records_outbox_and_queued_publish_failures() -> None:
    class ToggleBus:
        failing = True

        async def publish(self, event: object) -> str:
            if self.failing:
                raise RuntimeError("publish unavailable")
            return "ok"

        def subscribe(self, session_id: str, *, after_sequence: int = 0) -> Any:
            raise AssertionError("not used")

    metrics = InMemoryMetrics()
    bus = ToggleBus()
    journal = SplitEventJournal(
        InMemoryEventStore(),
        bus,
        max_pending_events=1,
        metrics_sink=metrics,
    )
    with pytest.raises(EventDeliveryError):
        await journal.commit(SessionCreated(session_id="session"))
    with pytest.raises(EventStoreCapacityError, match="outbox is full"):
        await journal.commit(SessionCreated(session_id="session"))
    assert metrics.measurements[-1].name == "kaji.journal.failures"
    assert metrics.measurements[-1].labels == {"stage": "append"}

    queued_metrics = InMemoryMetrics()
    bus = ToggleBus()
    queued = SplitEventJournal(
        InMemoryEventStore(),
        bus,
        max_pending_events=2,
        metrics_sink=queued_metrics,
    )
    with pytest.raises(EventDeliveryError):
        await queued.commit(SessionCreated(session_id="session"))
    bus.failing = False
    with pytest.raises(EventDeliveryError):
        await queued.commit(SessionCreated(session_id="session"))
    assert queued_metrics.measurements[-1].name == "kaji.journal.failures"
    assert queued_metrics.measurements[-1].labels == {"stage": "publish"}


@pytest.mark.asyncio
async def test_stable_journal_records_live_subscriber_lag() -> None:
    metrics = InMemoryMetrics()
    journal = InMemoryEventJournal(
        InMemoryEventStore(),
        metrics_sink=metrics,
    )
    subscription = cast(
        AsyncGenerator[StoredKajiEvent, None],
        journal.subscribe("session"),
    )

    async def receive_one() -> StoredKajiEvent:
        try:
            return await anext(subscription)
        finally:
            await subscription.aclose()

    next_event = asyncio.create_task(receive_one())
    await asyncio.sleep(0)
    await journal.commit(SessionCreated(session_id="session"))
    await next_event

    lag = [
        measurement.value
        for measurement in metrics.measurements
        if measurement.name == "kaji.subscriber.lag_events"
    ]
    assert lag[-1] == 1


@pytest.mark.asyncio
async def test_throwing_sinks_do_not_fail_a_turn() -> None:
    class ThrowingMetrics:
        def record(self, measurement: Measurement) -> None:
            raise RuntimeError("metrics unavailable")

    class ThrowingSpan:
        def set_attribute(self, name: str, value: str) -> None:
            raise RuntimeError("trace unavailable")

        def record_error(self, error: BaseException) -> None:
            raise RuntimeError("trace unavailable")

        def end(self) -> None:
            raise RuntimeError("trace unavailable")

    class ThrowingTrace:
        def start_span(self, name: str, attributes: object) -> ThrowingSpan:
            return ThrowingSpan()

    runtime = (
        AgentBuilder()
        .provider(MockProvider(reply="still works"))
        .metrics_sink(ThrowingMetrics())
        .trace_sink(ThrowingTrace())  # type: ignore[arg-type]
        .build()
    )
    assert (await runtime.turn("hello")).text == "still works"


@pytest.mark.asyncio
async def test_throwing_sinks_do_not_fail_tools_journals_or_subscribers() -> None:
    class ThrowingMetrics:
        def record(self, measurement: Measurement) -> None:
            raise RuntimeError("metrics unavailable")

    class ThrowingSpan:
        def set_attribute(self, name: str, value: str) -> None:
            raise RuntimeError("trace unavailable")

        def record_error(self, error: BaseException) -> None:
            raise RuntimeError("trace unavailable")

        def end(self) -> None:
            raise RuntimeError("trace unavailable")

    class ThrowingTrace:
        def start_span(self, name: str, attributes: object) -> ThrowingSpan:
            return ThrowingSpan()

    metrics = ThrowingMetrics()
    token = CancellationToken()
    context = ToolExecutionContext(
        principal_id="principal",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=token,
        deadline_monotonic=None,
        db=None,
        metadata={},
    )
    invocation = ToolInvocation(name="echo", arguments={}, context=context)

    async def execute(call: ToolInvocation) -> dict[str, bool]:
        return {"ok": call.name == "echo"}

    async def started() -> None:
        return None

    controller = ToolExecutionController(
        metrics_sink=metrics,
        trace_sink=ThrowingTrace(),  # type: ignore[arg-type]
    )
    outcome = await controller.execute(
        invocation,
        ToolSpec(name="echo", description="echo", parameters={}, risk="read"),
        execute,
        started,
    )
    assert outcome.result == {"ok": True}

    journal = InMemoryEventJournal(metrics_sink=metrics)
    subscription = cast(
        AsyncGenerator[StoredKajiEvent, None],
        journal.subscribe("session"),
    )

    async def receive_one() -> StoredKajiEvent:
        try:
            return await anext(subscription)
        finally:
            await subscription.aclose()

    next_event = asyncio.create_task(receive_one())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    committed = await journal.commit(SessionCreated(session_id="session"))
    assert await next_event == committed
