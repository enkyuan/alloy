"""Integration smoke test for OpenAIProvider.

Requires OPENAI_API_KEY to be set. Skipped automatically by conftest when
the key is absent.

Run manually:
    OPENAI_API_KEY=sk-... pytest -m integration tests/integration/test_openai_provider.py
"""

import os

import pytest


@pytest.mark.integration
async def test_openai_generate_returns_nonempty_content() -> None:
    """OpenAIProvider.generate() returns a non-empty text response for a simple prompt."""
    # Provider reads OPENAI_API_KEY via get_settings() at __init__ time.
    # The env var is guaranteed present here because conftest skips otherwise.
    assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY must be set"

    from agentkit.runtime.providers.openai import OpenAIProvider

    provider = OpenAIProvider()
    response = await provider.generate(
        messages=[{"role": "user", "content": "Say hello in one word."}],
        tools=[],
    )

    assert isinstance(response.text, str), "response.text should be a string"
    assert len(response.text.strip()) > 0, "response.text should not be empty"
