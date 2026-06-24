"""Integration smoke test for AnthropicProvider.

Requires ANTHROPIC_API_KEY to be set. Skipped automatically by conftest when
the key is absent.

Run manually:
    ANTHROPIC_API_KEY=sk-ant-... pytest -m integration tests/integration/test_anthropic_provider.py
"""

import os

import pytest


@pytest.mark.integration
async def test_anthropic_generate_returns_nonempty_content() -> None:
    """AnthropicProvider.generate() returns a non-empty text response for a simple prompt."""
    assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY must be set"

    from kaji.runtime.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider()
    response = await provider.generate(
        messages=[{"role": "user", "content": "Say hello in one word."}],
        tools=[],
    )

    assert isinstance(response.text, str), "response.text should be a string"
    assert len(response.text.strip()) > 0, "response.text should not be empty"
