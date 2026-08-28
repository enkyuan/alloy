"""Whole-turn execution limits and stable timeout errors."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Awaitable, ClassVar, Literal, TypeAlias, cast


TurnPhase: TypeAlias = Literal[
    "queue",
    "provider_open",
    "provider_stream",
    "approval",
    "tool",
]
Outcome: TypeAlias = Literal["not_started", "failed", "unknown"]

_TURN_PHASES = frozenset(
    {"queue", "provider_open", "provider_stream", "approval", "tool"}
)
_OUTCOMES = frozenset({"not_started", "failed", "unknown"})


@dataclass(frozen=True, slots=True)
class TurnExecutionLimits:
    """Runtime-wide bounds for one complete turn and provider response."""

    timeout_seconds: float = 120.0
    provider_cancellation_grace_seconds: float = 5.0
    provider_text_max_bytes: int = 262_144
    provider_tool_arguments_max_bytes: int = 65_536
    provider_response_max_bytes: int = 524_288
    provider_tool_calls_max: int = 64

    def __post_init__(self) -> None:
        for name in ("timeout_seconds", "provider_cancellation_grace_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a positive number")
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
            object.__setattr__(self, name, float(value))
        for name in (
            "provider_text_max_bytes",
            "provider_tool_arguments_max_bytes",
            "provider_response_max_bytes",
            "provider_tool_calls_max",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be a positive integer")
            if value < 1:
                raise ValueError(f"{name} must be a positive integer")


class TurnTimeoutError(TimeoutError):
    """Stable whole-turn timeout classified at the active state-machine phase."""

    code: ClassVar[str] = "TURN_TIMEOUT"

    def __init__(
        self,
        *,
        phase: TurnPhase | str,
        retryable: bool,
        outcome: Outcome | str,
    ) -> None:
        if phase not in _TURN_PHASES:
            raise ValueError(f"unknown turn phase: {phase}")
        if outcome not in _OUTCOMES:
            raise ValueError(f"unknown turn outcome: {outcome}")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")
        self.phase = cast(TurnPhase, phase)
        self.retryable = retryable
        self.outcome = cast(Outcome, outcome)
        super().__init__(f"Turn deadline exceeded during {phase}")


class ProviderCancellationContractViolation(RuntimeError):
    """A provider remained active after the configured cancellation grace."""

    code: ClassVar[str] = "PROVIDER_CANCELLATION_CONTRACT_VIOLATION"
    retryable: ClassVar[bool] = False
    outcome: ClassVar[Outcome] = "unknown"

    def __init__(
        self,
        *,
        settlement: Awaitable[None] | None = None,
        phase: TurnPhase = "provider_stream",
    ) -> None:
        self.phase = phase
        self._settlement: Any = settlement
        super().__init__("Provider did not stop after cancellation")


__all__ = [
    "Outcome",
    "ProviderCancellationContractViolation",
    "TurnExecutionLimits",
    "TurnPhase",
    "TurnTimeoutError",
]
