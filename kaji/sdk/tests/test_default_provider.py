"""Pin the SDK's out-of-the-box default LLM provider."""

from __future__ import annotations

import os
from unittest.mock import patch


def test_default_provider_is_mock() -> None:
    """A fresh import with no env var must default to the in-memory mock.

    Routing to a real vendor (kimi/openrouter, openai, anthropic) by default
    would silently send the user's tokens to a third party they did not pick.
    """
    fake_env = {k: v for k, v in os.environ.items() if not k.startswith("KAJI_")}
    with patch.dict(os.environ, fake_env, clear=True):
        from kaji.core.config import Settings

        settings = Settings()
        assert settings.KAJI_MODEL_PROVIDER == "mock"


def test_explicit_provider_env_still_wins() -> None:
    """Setting KAJI_MODEL_PROVIDER=kimi must still route to kimi."""
    with patch.dict(os.environ, {"KAJI_MODEL_PROVIDER": "kimi"}):
        from kaji.core.config import Settings

        settings = Settings()
        assert settings.KAJI_MODEL_PROVIDER == "kimi"
