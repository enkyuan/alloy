import pytest

from sdk.events.schemas import SessionCreated, UserMessage
from sdk.observability import EventTimeline, InMemoryMetrics, trace_span
from sdk.observability.tracing import Span


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


def test_trace_span_records_duration():
    with trace_span("unit.test") as span:
        span.attributes["key"] = "value"
        assert isinstance(span, Span)
    assert span.end_time is not None
    assert span.duration_ms is not None
    assert span.duration_ms >= 0


def test_event_timeline_orders_and_projects_state():
    events = [
        UserMessage(session_id="s1", content="hi", timestamp=2.0),
        SessionCreated(session_id="s1", timestamp=1.0),
    ]
    timeline = EventTimeline(events)
    assert timeline.event_types() == ["session.created", "user.message"]
    state = timeline.to_session_state()
    assert state.session_id == "s1"
    assert state.is_active is True


def test_event_timeline_empty_raises():
    with pytest.raises(ValueError, match="empty timeline"):
        EventTimeline([]).to_session_state()
