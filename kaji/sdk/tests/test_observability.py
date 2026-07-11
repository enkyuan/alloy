import pytest

from kaji.infra.events.schemas import SessionCreated, UserMessage, require_stored_event
from kaji.infra.observability import EventTimeline, InMemoryMetrics, TraceSpan
from kaji.infra.observability.tracing import Span


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
    with TraceSpan("unit.test") as span:
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
