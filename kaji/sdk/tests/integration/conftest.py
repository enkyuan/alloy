"""Conftest for integration tests.

Integration tests call real LLM APIs and are skipped when the required
environment variables are absent.  Run them explicitly with:

    pytest -m integration
    pytest -m integration tests/integration/test_openai_provider.py

CI runs ``pytest -m "not integration"`` by default so these are never
executed without credentials.
"""

import os

import pytest


def pytest_collection_modifyitems(items: list) -> None:
    """Skip integration tests when the required API key is not set."""
    for item in items:
        if item.get_closest_marker("integration") is None:
            continue

        # Determine which key(s) this test needs from its own markers or module.
        module_name = item.module.__name__ if item.module else ""

        if "openai" in module_name:
            key = "OPENAI_API_KEY"
        elif "anthropic" in module_name:
            key = "ANTHROPIC_API_KEY"
        elif "gemini" in module_name:
            key = "GEMINI_API_KEY"
        elif "kimi" in module_name:
            key = "OPENROUTER_API_KEY"
        else:
            # Generic integration test — skip unless at least one known key exists.
            key = None

        if key and not os.environ.get(key):
            item.add_marker(
                pytest.mark.skip(reason=f"{key} not set — skipping integration test")
            )
