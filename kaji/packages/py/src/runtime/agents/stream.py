"""Linear, scalar-safe provider response accumulation for one runtime call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kaji.runtime.providers.base import (
    ProviderResponseBudget,
    ResponseBudgetDiagnostics,
)
from kaji.runtime.providers.types import ModelResponseChunk, ProviderResponseLimits


@dataclass(frozen=True, slots=True)
class DeltaAccumulatorDiagnostics:
    input_fragments: int
    output_chunks: int
    join_operations: int


class DeltaAccumulator:
    """Coalesce text into nonempty chunks without splitting Unicode scalars."""

    def __init__(self, max_chunk_bytes: int = 4_096) -> None:
        if (
            isinstance(max_chunk_bytes, bool)
            or not isinstance(max_chunk_bytes, int)
            or max_chunk_bytes < 1
        ):
            raise ValueError("max_chunk_bytes must be a positive integer")
        self.max_chunk_bytes = max_chunk_bytes
        self._pending: list[str] = []
        self._pending_bytes = 0
        self._total_bytes = 0
        self._input_fragments = 0
        self._output_chunks = 0
        self._join_operations = 0

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def diagnostics(self) -> DeltaAccumulatorDiagnostics:
        return DeltaAccumulatorDiagnostics(
            input_fragments=self._input_fragments,
            output_chunks=self._output_chunks,
            join_operations=self._join_operations,
        )

    def push(self, delta: str) -> tuple[str, ...]:
        if not isinstance(delta, str):
            raise TypeError("delta must be a string")
        if not delta:
            return ()
        self._input_fragments += 1
        emitted: list[str] = []
        for scalar in delta:
            scalar_bytes = len(scalar.encode("utf-8"))
            if (
                self._pending
                and self._pending_bytes + scalar_bytes > self.max_chunk_bytes
            ):
                emitted.append(self._drain())
            self._pending.append(scalar)
            self._pending_bytes += scalar_bytes
            self._total_bytes += scalar_bytes
            if self._pending_bytes == self.max_chunk_bytes:
                emitted.append(self._drain())
        return tuple(emitted)

    def flush(self) -> str | None:
        return self._drain() if self._pending else None

    def _drain(self) -> str:
        self._join_operations += 1
        self._output_chunks += 1
        chunk = "".join(self._pending)
        self._pending.clear()
        self._pending_bytes = 0
        return chunk


@dataclass(frozen=True, slots=True)
class StreamDiagnostics:
    input_fragments: int
    durable_delta_events: int
    delta_join_operations: int
    response_join_operations: int
    text_bytes: int
    total_response_bytes: int
    tool_calls: int
    raw_fragments: int
    tool_argument_join_operations: int


class RuntimeStreamAccumulator:
    """Runtime second boundary for normalized custom-provider chunks."""

    def __init__(self, limits: ProviderResponseLimits) -> None:
        self._budget = ProviderResponseBudget(limits)
        self._deltas = DeltaAccumulator()
        self._response_parts: list[str] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._content: str | None = None
        self._response_joins = 0
        self._provider_diagnostics = ResponseBudgetDiagnostics(0, 0, 0, 0, 0)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self._tool_calls

    @property
    def diagnostics(self) -> StreamDiagnostics:
        delta = self._deltas.diagnostics
        budget = self._budget.diagnostics
        return StreamDiagnostics(
            input_fragments=delta.input_fragments,
            durable_delta_events=delta.output_chunks,
            delta_join_operations=delta.join_operations,
            response_join_operations=self._response_joins,
            text_bytes=budget.text_bytes,
            total_response_bytes=budget.total_response_bytes,
            tool_calls=budget.tool_calls,
            raw_fragments=self._provider_diagnostics.raw_fragments,
            tool_argument_join_operations=(
                self._provider_diagnostics.tool_argument_join_operations
            ),
        )

    def set_provider_diagnostics(self, diagnostics: ResponseBudgetDiagnostics) -> None:
        self._provider_diagnostics = diagnostics

    def accept(self, chunk: ModelResponseChunk) -> tuple[str, ...]:
        accepted = self._budget.accept_normalized(chunk.delta, chunk.tool_calls)
        if accepted.delta:
            self._response_parts.append(accepted.delta)
        self._tool_calls.extend(accepted.tool_calls)
        return self._deltas.push(accepted.delta)

    def flush(self) -> str | None:
        return self._deltas.flush()

    def content(self) -> str:
        if self._content is None:
            self._response_joins += 1
            self._content = "".join(self._response_parts)
        return self._content
