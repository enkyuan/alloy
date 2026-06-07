"""OpenAI implementation of the :class:`TTSProvider` protocol.

Synthesizes ``text`` to audio bytes via the OpenAI ``audio.speech`` API. The
OpenAI SDK is natively async, so these methods call it directly (no worker
thread). ``stream`` uses the streaming response and yields audio chunks as they
arrive.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from agentkit.modalities.voice.tts.openai_service import OpenAITTSService

logger = logging.getLogger(__name__)


class OpenAITTSProvider:
    """TTS provider backed by OpenAI. Satisfies the ``TTSProvider`` protocol."""

    def __init__(self, service: Optional[OpenAITTSService] = None) -> None:
        self._service = service or OpenAITTSService()

    async def synthesize(self, text: str) -> bytes:
        """Return the full synthesized audio for ``text``."""
        if not text.strip():
            raise ValueError("text must not be empty")

        service = self._service
        response = await service.client.audio.speech.create(
            model=service.model,
            voice=service.voice,
            input=text,
            response_format=service.RESPONSE_FORMAT,
        )
        return await response.read()

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for ``text`` as they are synthesized."""
        if not text.strip():
            raise ValueError("text must not be empty")

        service = self._service
        async with service.client.audio.speech.with_streaming_response.create(
            model=service.model,
            voice=service.voice,
            input=text,
            response_format=service.RESPONSE_FORMAT,
        ) as response:
            async for chunk in response.iter_bytes():
                if chunk:
                    yield chunk
