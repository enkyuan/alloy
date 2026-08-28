"""Integration smoke test for GeminiProvider.

Requires GEMINI_API_KEY to be set. Skipped automatically by conftest when
the key is absent.

Run manually:
    GEMINI_API_KEY=... pytest -m integration tests/integration/test_gemini_provider.py
"""

import os

import pytest


@pytest.mark.integration
async def test_gemini_generate_returns_nonempty_content() -> None:
    """GeminiProvider.generate() returns a non-empty text response for a simple prompt."""
    assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY must be set"

    from kaji.runtime.providers.gemini import GeminiProvider

    provider = GeminiProvider()
    response = await provider.generate(
        messages=[{"role": "user", "content": "Say hello in one word."}],
        tools=[],
    )

    assert isinstance(response.text, str), "response.text should be a string"
    assert len(response.text.strip()) > 0, "response.text should not be empty"
