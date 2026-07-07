from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CostEntry:
    input_per_1m: float
    output_per_1m: float


COST_TABLE: dict[str, CostEntry] = {
    "gpt-5.5": CostEntry(input_per_1m=5.0, output_per_1m=30.0),
    "gpt-5.4": CostEntry(input_per_1m=2.5, output_per_1m=15.0),
    "gpt-5.4-mini": CostEntry(input_per_1m=0.75, output_per_1m=4.5),
    "gpt-5.4-nano": CostEntry(input_per_1m=0.2, output_per_1m=1.25),
    "gpt-4o": CostEntry(input_per_1m=2.5, output_per_1m=10.0),
    "gpt-4o-mini": CostEntry(input_per_1m=0.15, output_per_1m=0.6),
    "gpt-4-turbo": CostEntry(input_per_1m=10.0, output_per_1m=30.0),
    "gpt-4": CostEntry(input_per_1m=30.0, output_per_1m=60.0),
    "gpt-3.5-turbo": CostEntry(input_per_1m=0.5, output_per_1m=1.5),
    "o1": CostEntry(input_per_1m=15.0, output_per_1m=60.0),
    "o1-mini": CostEntry(input_per_1m=3.0, output_per_1m=12.0),
    "o3-mini": CostEntry(input_per_1m=1.1, output_per_1m=4.4),
    "o3": CostEntry(input_per_1m=10.0, output_per_1m=40.0),
    "gpt-4.1": CostEntry(input_per_1m=2.0, output_per_1m=8.0),
    "gpt-4.1-mini": CostEntry(input_per_1m=0.4, output_per_1m=1.6),
    "gpt-4.1-nano": CostEntry(input_per_1m=0.1, output_per_1m=0.4),
    "claude-3-5-sonnet-20241022": CostEntry(input_per_1m=3.0, output_per_1m=15.0),
    "claude-3-5-sonnet": CostEntry(input_per_1m=3.0, output_per_1m=15.0),
    "claude-3-5-haiku-20241022": CostEntry(input_per_1m=0.8, output_per_1m=4.0),
    "claude-3-5-haiku": CostEntry(input_per_1m=0.8, output_per_1m=4.0),
    "claude-3-opus-20240229": CostEntry(input_per_1m=15.0, output_per_1m=75.0),
    "claude-3-opus": CostEntry(input_per_1m=15.0, output_per_1m=75.0),
    "claude-3-sonnet-20240229": CostEntry(input_per_1m=3.0, output_per_1m=15.0),
    "claude-3-haiku-20240307": CostEntry(input_per_1m=0.25, output_per_1m=1.25),
    "claude-opus-4": CostEntry(input_per_1m=15.0, output_per_1m=75.0),
    "claude-sonnet-4": CostEntry(input_per_1m=3.0, output_per_1m=15.0),
    "claude-haiku-4": CostEntry(input_per_1m=0.8, output_per_1m=4.0),
    "gemini-2.5-flash": CostEntry(input_per_1m=0.15, output_per_1m=0.6),
    "gemini-2.5-pro": CostEntry(input_per_1m=1.25, output_per_1m=10.0),
    "gemini-2.0-flash": CostEntry(input_per_1m=0.1, output_per_1m=0.4),
    "gemini-1.5-flash": CostEntry(input_per_1m=0.075, output_per_1m=0.3),
    "gemini-1.5-pro": CostEntry(input_per_1m=1.25, output_per_1m=5.0),
    "moonshotai/kimi-k2": CostEntry(input_per_1m=0.6, output_per_1m=2.5),
    "moonshot-v1-8k": CostEntry(input_per_1m=0.12, output_per_1m=0.12),
    "moonshot-v1-32k": CostEntry(input_per_1m=0.48, output_per_1m=0.48),
    "moonshot-v1-128k": CostEntry(input_per_1m=1.92, output_per_1m=1.92),
}


def lookup_cost(model: str) -> Optional[CostEntry]:
    if model in COST_TABLE:
        return COST_TABLE[model]
    best_key = ""
    best: Optional[CostEntry] = None
    for key, entry in COST_TABLE.items():
        if model.startswith(key) and len(key) > len(best_key):
            best_key = key
            best = entry
    return best


def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    entry = lookup_cost(model)
    if entry is None:
        return 0
    return round(
        (input_tokens / 1_000_000) * entry.input_per_1m
        + (output_tokens / 1_000_000) * entry.output_per_1m,
        10,
    )
