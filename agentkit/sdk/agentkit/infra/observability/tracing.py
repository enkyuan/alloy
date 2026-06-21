"""Lightweight tracing helpers (OpenTelemetry integration point)."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass
class Span:
    """A single trace span."""

    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000.0


@contextmanager
def trace_span(
    name: str, *, trace_id: str | None = None
) -> Generator[Span, None, None]:
    span = Span(name=name, trace_id=trace_id or uuid.uuid4().hex[:16])
    try:
        yield span
    finally:
        span.end_time = time.time()


TraceSpan = trace_span
