"""Opt-in onMutate callback on provider_safe_tool_name.

The sanitizer must have NO default side-effect: every registered tool
runs through it, so a default warn-on-mutation would produce one stderr
line per sanitized name on every startup. Callers (integration base
classes) thread an explicit callback in to surface the mutation through
their own logger.
"""

from __future__ import annotations

import logging

from agentkit.runtime.tools.registry import provider_safe_tool_name


def test_on_mutate_callback_fires_when_name_is_changed():
    seen: list[tuple[str, str]] = []
    out = provider_safe_tool_name(
        "weather-api.v2",
        on_mutate=lambda original, sanitized: seen.append((original, sanitized)),
    )
    assert out != "weather-api.v2"
    assert seen == [("weather-api.v2", out)]


def test_on_mutate_not_called_when_name_is_already_safe():
    seen: list[tuple[str, str]] = []
    out = provider_safe_tool_name(
        "weather_api",
        on_mutate=lambda original, sanitized: seen.append((original, sanitized)),
    )
    assert out == "weather_api"
    assert seen == []


def test_no_side_effect_when_callback_omitted(caplog):
    caplog.set_level(logging.WARNING, logger="agentkit.runtime.tools.registry")
    out = provider_safe_tool_name("weather.api")
    assert out == "weather_api"
    assert [r for r in caplog.records if "sanitized" in r.message.lower()] == []


def test_preserves_existing_transform():
    assert provider_safe_tool_name("a.b.c") == "a_b_c"
    assert provider_safe_tool_name("a-b-c") == "a-b-c"
    assert provider_safe_tool_name("___foo___") == "foo"
    assert provider_safe_tool_name("$$$") == "tool"
