"""In-process recording sink for development and tests."""

from __future__ import annotations

from collections import defaultdict

from kaji.infra.observability.protocols import Measurement

__all__ = ["InMemoryMetrics"]


class InMemoryMetrics:
    """Thread-unsafe counter registry suitable for unit tests."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self.measurements: list[Measurement] = []

    def record(self, measurement: Measurement) -> None:
        self.measurements.append(measurement)
        if measurement.unit == "gauge":
            self._counters[measurement.name] = measurement.value
        else:
            self._counters[measurement.name] += measurement.value

    def increment(self, name: str, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self._counters[name] += amount

    def get(self, name: str) -> float:
        return self._counters[name]

    def reset(self) -> None:
        self._counters.clear()
        self.measurements.clear()
