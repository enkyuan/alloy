from kaji.runtime.providers.costs import calculate_cost_usd, lookup_cost


def test_calculate_cost_usd_for_gpt_54_mini_is_nonzero() -> None:
    assert calculate_cost_usd("gpt-5.4-mini", 1_000_000, 1_000_000) == 5.25


def test_unknown_model_cost_is_zero() -> None:
    assert lookup_cost("unknown-model") is None
    assert calculate_cost_usd("unknown-model", 1_000_000, 1_000_000) == 0
