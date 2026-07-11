"""Dependency-free, low-cardinality observability contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from types import MappingProxyType
from typing import Literal, Mapping, Protocol, TypeAlias, runtime_checkable

from kaji.core.safe_logging import log_no_throw


logger = logging.getLogger(__name__)

MetricName: TypeAlias = Literal[
    "kaji.turn.queue_wait_ms",
    "kaji.turn.duration_ms",
    "kaji.turn.iterations",
    "kaji.provider.duration_ms",
    "kaji.provider.retries",
    "kaji.replay.input_events",
    "kaji.context.messages",
    "kaji.context.characters",
    "kaji.tool.queue_wait_ms",
    "kaji.tool.active",
    "kaji.tool.duration_ms",
    "kaji.journal.failures",
    "kaji.subscriber.lag_events",
    "kaji.subscriber.overflow",
]

SpanName: TypeAlias = Literal["kaji.turn", "kaji.provider", "kaji.tool"]
TraceAttributeName: TypeAlias = Literal[
    "principal.id",
    "session.id",
    "turn.id",
    "request.id",
    "trace.id",
    "tool.call_id",
    "provider.family",
]

MetricUnit: TypeAlias = Literal["ms", "count", "gauge"]

_METRIC_LABELS: dict[str, frozenset[str]] = {
    "kaji.turn.queue_wait_ms": frozenset(),
    "kaji.turn.duration_ms": frozenset({"outcome"}),
    "kaji.turn.iterations": frozenset({"outcome"}),
    "kaji.provider.duration_ms": frozenset({"provider_family", "status"}),
    "kaji.provider.retries": frozenset({"provider_family"}),
    "kaji.replay.input_events": frozenset(),
    "kaji.context.messages": frozenset(),
    "kaji.context.characters": frozenset(),
    "kaji.tool.queue_wait_ms": frozenset({"outcome"}),
    "kaji.tool.active": frozenset(),
    "kaji.tool.duration_ms": frozenset({"outcome", "error_code"}),
    "kaji.journal.failures": frozenset({"stage"}),
    "kaji.subscriber.lag_events": frozenset(),
    "kaji.subscriber.overflow": frozenset({"stage"}),
}

_METRIC_UNITS: dict[str, MetricUnit] = {
    "kaji.turn.queue_wait_ms": "ms",
    "kaji.turn.duration_ms": "ms",
    "kaji.turn.iterations": "count",
    "kaji.provider.duration_ms": "ms",
    "kaji.provider.retries": "count",
    "kaji.replay.input_events": "count",
    "kaji.context.messages": "count",
    "kaji.context.characters": "count",
    "kaji.tool.queue_wait_ms": "ms",
    "kaji.tool.active": "gauge",
    "kaji.tool.duration_ms": "ms",
    "kaji.journal.failures": "count",
    "kaji.subscriber.lag_events": "count",
    "kaji.subscriber.overflow": "count",
}

_LABEL_VALUES: dict[str, frozenset[str]] = {
    "outcome": frozenset(
        {
            "acquired",
            "completed",
            "failed",
            "cancelled",
            "timeout",
            "not_started",
            "unknown",
        }
    ),
    "provider_family": frozenset({"openai", "anthropic", "custom"}),
    "status": frozenset({"success", "error", "cancelled"}),
    "stage": frozenset({"append", "publish", "lag", "overflow"}),
    "error_code": frozenset(
        {
            "NONE",
            "OTHER",
            "INVALID_TOOL_SCHEMA",
            "INVALID_TOOL_ARGUMENTS",
            "UNCLASSIFIED_TOOL_RISK",
            "MISSING_TOOL_IDENTITY",
            "TOOL_NOT_ALLOWED",
            "APPROVAL_UNAVAILABLE",
            "APPROVAL_REJECTED",
            "APPROVAL_TIMEOUT",
            "TOOL_CANCELLED",
            "TOOL_TIMEOUT",
            "TOOL_EXECUTION_FAILED",
            "TOOL_START_RECORD_FAILED",
            "IDEMPOTENCY_CAPACITY_EXCEEDED",
            "IDEMPOTENCY_CONFLICT",
        }
    ),
}

_TRACE_ATTRIBUTES = frozenset(
    {
        "principal.id",
        "session.id",
        "turn.id",
        "request.id",
        "trace.id",
        "tool.call_id",
        "provider.family",
    }
)
_SPAN_NAMES = frozenset({"kaji.turn", "kaji.provider", "kaji.tool"})


@dataclass(frozen=True, slots=True)
class Measurement:
    """One validated measurement with a closed metric and label vocabulary."""

    name: MetricName
    value: float
    labels: Mapping[str, str] = field(default_factory=dict)
    unit: MetricUnit = field(init=False)

    def __post_init__(self) -> None:
        if self.name not in _METRIC_LABELS:
            raise ValueError(f"unsupported metric name: {self.name}")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("metric value must be a finite number")
        value = float(self.value)
        if not math.isfinite(value):
            raise ValueError("metric value must be a finite number")
        labels = dict(self.labels)
        expected = _METRIC_LABELS[self.name]
        if frozenset(labels) != expected:
            raise ValueError(f"{self.name} labels must be exactly {sorted(expected)!r}")
        for key, label in labels.items():
            if label not in _LABEL_VALUES[key]:
                raise ValueError(f"unsupported {key} label: {label}")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "labels", MappingProxyType(labels))
        object.__setattr__(self, "unit", _METRIC_UNITS[self.name])


@runtime_checkable
class MetricsSink(Protocol):
    """Receives validated measurements synchronously."""

    def record(self, measurement: Measurement) -> None: ...


@runtime_checkable
class SpanHandle(Protocol):
    def set_attribute(self, name: TraceAttributeName, value: str) -> None: ...

    def record_error(self, error: BaseException) -> None: ...

    def end(self) -> None: ...


@runtime_checkable
class TraceSink(Protocol):
    """Starts spans whose attributes use a closed correlation vocabulary."""

    def start_span(
        self,
        name: SpanName,
        attributes: Mapping[TraceAttributeName, str],
    ) -> SpanHandle: ...


class _NoopMetrics:
    __slots__ = ()

    def record(self, measurement: Measurement) -> None:
        _ = measurement


class _NoopSpan:
    __slots__ = ()

    def set_attribute(self, name: TraceAttributeName, value: str) -> None:
        _ = (name, value)

    def record_error(self, error: BaseException) -> None:
        _ = error

    def end(self) -> None:
        return None


class _NoopTrace:
    __slots__ = ()

    def start_span(
        self,
        name: SpanName,
        attributes: Mapping[TraceAttributeName, str],
    ) -> SpanHandle:
        _ = (name, attributes)
        return _NOOP_SPAN


NOOP_METRICS: MetricsSink = _NoopMetrics()
_NOOP_SPAN: SpanHandle = _NoopSpan()
NOOP_TRACE: TraceSink = _NoopTrace()


class _SafeSpan:
    """Protect runtime behavior from throwing or multiply-ended sink spans."""

    __slots__ = ("_ended", "_inner")

    def __init__(self, inner: SpanHandle) -> None:
        self._inner = inner
        self._ended = False

    def set_attribute(self, name: TraceAttributeName, value: str) -> None:
        if self._ended:
            return
        if name not in _TRACE_ATTRIBUTES or type(value) is not str:
            return
        try:
            self._inner.set_attribute(name, value)
        except Exception:
            log_no_throw(
                logger,
                logging.ERROR,
                "Observability trace span failed to set attribute",
                exc_info=True,
            )

    def record_error(self, error: BaseException) -> None:
        if self._ended:
            return
        try:
            self._inner.record_error(error)
        except Exception:
            log_no_throw(
                logger,
                logging.ERROR,
                "Observability trace span failed to record error",
                exc_info=True,
            )

    def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        try:
            self._inner.end()
        except Exception:
            log_no_throw(
                logger,
                logging.ERROR,
                "Observability trace span failed to end",
                exc_info=True,
            )


def record_metric(
    sink: MetricsSink,
    name: MetricName,
    value: float,
    /,
    **labels: str,
) -> None:
    """Best-effort delivery; invalid or throwing sinks never affect runtime work."""
    if sink is NOOP_METRICS:
        return
    try:
        sink.record(Measurement(name=name, value=value, labels=labels))
    except Exception:
        log_no_throw(
            logger,
            logging.ERROR,
            "Observability metric sink failed for %s",
            name,
            exc_info=True,
        )


def start_span(
    sink: TraceSink,
    name: SpanName,
    attributes: Mapping[TraceAttributeName, str],
) -> SpanHandle:
    """Best-effort span creation with closed, detached attributes."""
    if sink is NOOP_TRACE:
        return _NOOP_SPAN
    if not isinstance(name, str) or name not in _SPAN_NAMES:
        return _NOOP_SPAN
    try:
        resolved = dict(attributes)
    except Exception:
        return _NOOP_SPAN
    if any(
        key not in _TRACE_ATTRIBUTES or type(value) is not str
        for key, value in resolved.items()
    ):
        return _NOOP_SPAN
    try:
        return _SafeSpan(sink.start_span(name, MappingProxyType(resolved)))
    except Exception:
        log_no_throw(
            logger,
            logging.ERROR,
            "Observability trace sink failed for %s",
            name,
            exc_info=True,
        )
        return _NOOP_SPAN


def span_record_error(span: SpanHandle, error: BaseException) -> None:
    span.record_error(error)


def span_end(span: SpanHandle) -> None:
    span.end()


def provider_family(provider: object) -> str:
    """Normalize concrete provider types to the closed metric label set."""
    name = type(provider).__name__.lower()
    for family in ("openai", "anthropic"):
        if family in name:
            return family
    return "custom"


def metric_error_code(code: str | None) -> str:
    """Map extension/private failure codes to the bounded public label value."""
    if code is None:
        return "NONE"
    return code if code in _LABEL_VALUES["error_code"] else "OTHER"


__all__ = [
    "Measurement",
    "MetricName",
    "MetricsSink",
    "NOOP_METRICS",
    "NOOP_TRACE",
    "SpanHandle",
    "SpanName",
    "TraceAttributeName",
    "TraceSink",
]
