from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import math
import re
from typing import Optional


@dataclass(frozen=True)
class CostEntry:
    input_per_1m: float
    output_per_1m: float


COST_TABLE: dict[str, CostEntry] = {
    "gpt-5.4-mini": CostEntry(input_per_1m=0.75, output_per_1m=4.5),
    "claude-sonnet-4-6": CostEntry(input_per_1m=3.0, output_per_1m=15.0),
    "gemini-2.5-flash": CostEntry(input_per_1m=0.3, output_per_1m=2.5),
    "gemini-3.5-flash": CostEntry(input_per_1m=1.5, output_per_1m=9.0),
}

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_TOKENS_PER_RATE_UNIT = Decimal(1_000_000)
_USD_QUANTUM = Decimal("0.0000000001")
_MAX_RATE_SIGNIFICANT_DIGITS = 32
_MAX_RATE_FRACTIONAL_DIGITS = 32
_MAX_RATE_ABSOLUTE_EXPONENT = 32
_MAX_RATE_TEXT_LENGTH = 65
_MAX_RATE_INTEGER = 10**_MAX_RATE_SIGNIFICANT_DIGITS - 1
_DECIMAL_RATE = re.compile(r"^(0|[1-9][0-9]*)(?:\.([0-9]*[1-9]))?$")
_SCIENTIFIC_RATE = re.compile(r"^([1-9])(?:\.([0-9]*[1-9]))?e(-?[1-9][0-9]*)$")
_SNAPSHOT_SUFFIX = re.compile(r"-(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{8}|[0-9]{3})$")


def lookup_cost(model: str) -> Optional[CostEntry]:
    exact = COST_TABLE.get(model)
    if exact is not None:
        return exact
    base = _SNAPSHOT_SUFFIX.sub("", model)
    return COST_TABLE.get(base) if base != model else None


def _validate_token_count(name: str, value: int) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not 0 <= value <= _MAX_SAFE_INTEGER:
        raise ValueError(f"{name} must be between 0 and {_MAX_SAFE_INTEGER}, inclusive")


def _bounded_exponent(value: str) -> int:
    digits = value.removeprefix("+").removeprefix("-")
    normalized = digits.lstrip("0") or "0"
    if len(normalized) > 2:
        raise ValueError("cost rate exponent exceeds 32")
    magnitude = int(normalized)
    if magnitude > _MAX_RATE_ABSOLUTE_EXPONENT:
        raise ValueError("cost rate exponent exceeds 32")
    return -magnitude if value.startswith("-") else magnitude


def _numeric_rate_text(value: int | float) -> str:
    if type(value) not in (int, float) or (
        isinstance(value, float) and not math.isfinite(value)
    ):
        raise TypeError("cost rate must be a finite number or canonical decimal string")
    if value < 0:
        raise ValueError("cost rate must be non-negative")
    if type(value) is int and value > _MAX_RATE_INTEGER:
        raise ValueError("cost rate exceeds 32 significant digits")
    if value == 0:
        return "0"
    mantissa, separator, exponent_text = str(value).lower().partition("e")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    if not separator:
        return mantissa
    exponent = _bounded_exponent(exponent_text)
    if exponent == 0:
        return mantissa
    return f"{mantissa}e{exponent}"


def _rate_decimal(value: str | int | float) -> Decimal:
    text = value if isinstance(value, str) else _numeric_rate_text(value)
    if not 0 < len(text) <= _MAX_RATE_TEXT_LENGTH:
        raise ValueError("cost rate exceeds the canonical length bound")
    match = _DECIMAL_RATE.fullmatch(text)
    exponent = 0
    if match is None:
        match = _SCIENTIFIC_RATE.fullmatch(text)
        if match is None:
            raise ValueError("cost rate is not a canonical non-negative decimal")
        exponent = _bounded_exponent(match.group(3))
    fraction = match.group(2) or ""
    significant = (match.group(1) + fraction).lstrip("0") or "0"
    if len(significant) > _MAX_RATE_SIGNIFICANT_DIGITS:
        raise ValueError("cost rate exceeds 32 significant digits")
    if len(fraction) > _MAX_RATE_FRACTIONAL_DIGITS:
        raise ValueError("cost rate exceeds 32 fractional digits")
    if abs(exponent) > _MAX_RATE_ABSOLUTE_EXPONENT:
        raise ValueError("cost rate exponent exceeds 32")
    return Decimal(text)


def _calculate_cost_from_rates_usd_canonical(
    input_tokens: int,
    output_tokens: int,
    input_per_1m: str | int | float,
    output_per_1m: str | int | float,
) -> str:
    _validate_token_count("input_tokens", input_tokens)
    _validate_token_count("output_tokens", output_tokens)
    with localcontext() as context:
        context.prec = 128
        total = (
            Decimal(input_tokens) * _rate_decimal(input_per_1m)
            + Decimal(output_tokens) * _rate_decimal(output_per_1m)
        ) / _TOKENS_PER_RATE_UNIT
        rounded = total.quantize(_USD_QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def _calculate_cost_usd_canonical(
    model: str, input_tokens: int, output_tokens: int
) -> str:
    _validate_token_count("input_tokens", input_tokens)
    _validate_token_count("output_tokens", output_tokens)
    entry = lookup_cost(model)
    if entry is None:
        return "0"
    return _calculate_cost_from_rates_usd_canonical(
        input_tokens,
        output_tokens,
        entry.input_per_1m,
        entry.output_per_1m,
    )


def calculate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    return float(_calculate_cost_usd_canonical(model, input_tokens, output_tokens))
