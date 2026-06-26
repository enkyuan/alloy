"""Integration smoke test for KimiProvider.

Requires OPENROUTER_API_KEY (or KIMI_API_KEY) to be set. Skipped
automatically by conftest when OPENROUTER_API_KEY is absent.

Run manually:
    OPENROUTER_API_KEY=... pytest -m integration tests/integration/test_kimi_provider.py
"""

import os

import pytest


@pytest.mark.integration
async def test_kimi_generate_returns_nonempty_content() -> None:
    """KimiProvider.generate() returns a non-empty text response for a simple prompt."""
    assert os.environ.get("OPENROUTER_API_KEY"), "OPENROUTER_API_KEY must be set"

    from kaji.runtime.providers.kimi import KimiProvider

    provider = KimiProvider()
    response = await provider.generate(
        messages=[{"role": "user", "content": "Say hello in one word."}],
        tools=[],
    )

    assert isinstance(response.text, str), "response.text should be a string"
    assert len(response.text.strip()) > 0, "response.text should not be empty"
