import json
from pathlib import Path

import pytest

from kaji.runtime.providers.costs import (
    _calculate_cost_from_rates_usd_canonical,
    _calculate_cost_usd_canonical,
    calculate_cost_usd,
    lookup_cost,
)


FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "providers"
        / "cost-conformance.json"
    ).read_text()
)


def test_calculate_cost_usd_for_gpt_54_mini_is_nonzero() -> None:
    assert calculate_cost_usd("gpt-5.4-mini", 1_000_000, 1_000_000) == 5.25


def test_unknown_model_cost_is_zero() -> None:
    assert lookup_cost("unknown-model") is None
    assert calculate_cost_usd("unknown-model", 1_000_000, 1_000_000) == 0


def test_cost_lookup_accepts_snapshots_but_never_guesses_model_families() -> None:
    assert lookup_cost("gpt-5.4-mini-2026-04-15") == lookup_cost("gpt-5.4-mini")
    assert lookup_cost("gemini-3.5-flash-001") == lookup_cost("gemini-3.5-flash")
    assert lookup_cost("claude-sonnet-4-60") is None
    assert lookup_cost("moonshotai/kimi-k2.6") is None


def test_gemini_25_flash_uses_current_standard_rate() -> None:
    entry = lookup_cost("gemini-2.5-flash")
    assert entry is not None
    assert (entry.input_per_1m, entry.output_per_1m) == (0.3, 2.5)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_provider_cost_contract(case: dict[str, object]) -> None:
    input_tokens = case["inputTokens"]
    output_tokens = case["outputTokens"]
    expected = case["expectedCanonicalUsd"]
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    assert isinstance(expected, str)

    rates = case.get("rates")
    if isinstance(rates, dict):
        input_rate = rates.get("inputPer1M")
        output_rate = rates.get("outputPer1M")
        assert isinstance(input_rate, str)
        assert isinstance(output_rate, str)
        canonical = _calculate_cost_from_rates_usd_canonical(
            input_tokens,
            output_tokens,
            input_rate,
            output_rate,
        )
        assert (
            _calculate_cost_from_rates_usd_canonical(
                input_tokens,
                output_tokens,
                float(input_rate),
                float(output_rate),
            )
            == expected
        )
    else:
        model = case["model"]
        assert isinstance(model, str)
        canonical = _calculate_cost_usd_canonical(model, input_tokens, output_tokens)
        result = calculate_cost_usd(model, input_tokens, output_tokens)
        assert isinstance(result, float)
        assert result == float(expected)
    assert canonical == expected


@pytest.mark.parametrize(
    "invalid", FIXTURE["invalidTokenCounts"], ids=lambda case: case["name"]
)
@pytest.mark.parametrize("field", ["input", "output"])
def test_provider_cost_rejects_invalid_token_counts(
    invalid: dict[str, object], field: str
) -> None:
    value = invalid["value"]
    input_tokens = value if field == "input" else 0
    output_tokens = value if field == "output" else 0
    with pytest.raises((TypeError, ValueError)):
        calculate_cost_usd(
            "gemini-3.5-flash",
            input_tokens,  # ty: ignore[invalid-argument-type]
            output_tokens,  # ty: ignore[invalid-argument-type]
        )


def _invalid_rate(case: dict[str, object]) -> str | float:
    value = case["value"]
    kind = case["kind"]
    assert isinstance(value, str)
    assert kind in {"number", "string"}
    return float(value) if kind == "number" else value


@pytest.mark.parametrize(
    "invalid", FIXTURE["invalidRates"], ids=lambda case: case["name"]
)
@pytest.mark.parametrize("field", ["input", "output"])
def test_provider_cost_rejects_invalid_rates(
    invalid: dict[str, object], field: str
) -> None:
    value = _invalid_rate(invalid)
    input_rate = value if field == "input" else "0"
    output_rate = value if field == "output" else "0"
    with pytest.raises((TypeError, ValueError)):
        _calculate_cost_from_rates_usd_canonical(1, 1, input_rate, output_rate)


def test_provider_cost_rejects_a_huge_integer_rate_before_string_conversion() -> None:
    with pytest.raises(ValueError, match="32 significant digits"):
        _calculate_cost_from_rates_usd_canonical(1, 1, 10**10_000, 0)
