"""Canonical cross-SDK JSON encoding for durable event values."""

from __future__ import annotations

import json
import math
from typing import Any


MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _is_unsafe_integral_number(value: int | float) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) > MAX_SAFE_INTEGER
    return math.isfinite(value) and value.is_integer() and abs(value) > MAX_SAFE_INTEGER


def _canonical_float(value: float, subject: str) -> str:
    if not math.isfinite(value):
        raise ValueError(f"{subject} contains a non-finite number")
    if _is_unsafe_integral_number(value):
        raise TypeError(f"{subject} contains an integer outside the I-JSON safe range")
    if value == 0:
        return "0"

    source = repr(abs(value)).lower()
    coefficient, marker, raw_exponent = source.partition("e")
    exponent = int(raw_exponent) if marker else 0
    whole, point, fraction = coefficient.partition(".")
    digits = (whole + fraction).lstrip("0")
    scale = exponent - (len(fraction) if point else 0)
    while digits.endswith("0"):
        digits = digits[:-1]
        scale += 1

    decimal_exponent = len(digits) + scale - 1
    sign = "-" if value < 0 else ""
    if -6 <= decimal_exponent < 21:
        decimal_point = decimal_exponent + 1
        if decimal_point <= 0:
            body = "0." + ("0" * -decimal_point) + digits
        elif decimal_point >= len(digits):
            body = digits + ("0" * (decimal_point - len(digits)))
        else:
            body = digits[:decimal_point] + "." + digits[decimal_point:]
        return sign + body

    mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    exponent_sign = "+" if decimal_exponent >= 0 else ""
    return f"{sign}{mantissa}e{exponent_sign}{decimal_exponent}"


def _canonical_integer(value: int, subject: str) -> str:
    if _is_unsafe_integral_number(value):
        raise TypeError(f"{subject} contains an integer outside the I-JSON safe range")
    return _canonical_float(float(value), subject)


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _validate_unicode_scalar_string(value: str, subject: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise TypeError(f"{subject} contains an unpaired Unicode surrogate")


def canonical_json(value: Any, *, subject: str = "JSON value") -> str:
    """Encode a strict JSON value with the shared ECMAScript number policy."""

    def encode(item: Any, ancestors: set[int]) -> str:
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, str):
            _validate_unicode_scalar_string(item, subject)
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, int):
            return _canonical_integer(item, subject)
        if isinstance(item, float):
            return _canonical_float(item, subject)
        if isinstance(item, (list, dict)):
            identity = id(item)
            if identity in ancestors:
                raise TypeError(f"{subject} must be acyclic")
            ancestors.add(identity)
            try:
                if isinstance(item, list):
                    return (
                        "[" + ",".join(encode(child, ancestors) for child in item) + "]"
                    )
                keys: list[str] = []
                for key in item:
                    if not isinstance(key, str):
                        raise TypeError(f"{subject} JSON object keys must be strings")
                    _validate_unicode_scalar_string(key, subject)
                    keys.append(key)
                return (
                    "{"
                    + ",".join(
                        json.dumps(key, ensure_ascii=False)
                        + ":"
                        + encode(item[key], ancestors)
                        for key in sorted(keys, key=_utf16_sort_key)
                    )
                    + "}"
                )
            finally:
                ancestors.remove(identity)
        raise TypeError(f"{subject} contains non-JSON value {type(item).__name__}")

    return encode(value, set())


__all__ = ["MAX_SAFE_INTEGER", "canonical_json"]
