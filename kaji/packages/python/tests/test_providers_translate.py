"""Tests for the shared role translator."""

from kaji.runtime.providers._translate import normalize_role, to_gemini_role


def test_normalize_user():
    assert normalize_role("user") == "user"


def test_normalize_assistant():
    assert normalize_role("assistant") == "assistant"


def test_normalize_tool():
    assert normalize_role("tool") == "tool"


def test_normalize_system():
    assert normalize_role("system") == "system"


def test_normalize_gemini_model_alias():
    # Gemini uses "model" to mean "assistant"; normalize_role must map it.
    assert normalize_role("model") == "assistant"


def test_normalize_unknown_passthrough():
    # Unknown roles are returned unchanged so callers decide how to handle them.
    assert normalize_role("something_weird") == "something_weird"


def test_to_gemini_role_user():
    assert to_gemini_role("user") == "user"


def test_to_gemini_role_assistant():
    assert to_gemini_role("assistant") == "model"


def test_to_gemini_role_model_round_trips():
    # "model" -> normalize -> "assistant" -> to_gemini -> "model"
    assert to_gemini_role("model") == "model"


def test_to_gemini_role_tool():
    assert to_gemini_role("tool") == "tool"
