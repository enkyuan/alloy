"""Gemini implementation of the :class:`TTSProvider` protocol.

Synthesizes ``text`` to audio bytes via the google-genai SDK. The genai
generation calls are synchronous, so they run in a worker thread to avoid
blocking the event loop; ``stream`` drains the SDK's chunk iterator onto an
async queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from agentkit.voice.tts.gemini_service import GeminiTTSService

logger = logging.getLogger(__name__)


def _extract_audio(chunk: Any) -> Optional[bytes]:
    """Pull inline audio bytes out of a genai response/chunk, if present."""
    candidates = getattr(chunk, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


class GeminiTTSProvider:
    """TTS provider backed by Gemini. Satisfies the ``TTSProvider`` protocol."""

    def __init__(self, service: Optional[GeminiTTSService] = None) -> None:
        self._service = service or GeminiTTSService()

    async def synthesize(self, text: str) -> bytes:
        """Return the full synthesized audio for ``text``."""
        if not text.strip():
            raise ValueError("text must not be empty")

        service = self._service

        def _run() -> bytes:
            response = service.client.models.generate_content(
                model=service.model,
                contents=text,
                config=service.build_config(),
            )
            audio = _extract_audio(response)
            if audio is None:
                raise RuntimeError("Gemini TTS returned no audio data.")
            return audio

        return await asyncio.to_thread(_run)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for ``text`` as they are synthesized."""
        if not text.strip():
            raise ValueError("text must not be empty")

        service = self._service
        queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                stream = service.client.models.generate_content_stream(
                    model=service.model,
                    contents=text,
                    config=service.build_config(),
                )
                for chunk in stream:
                    audio = _extract_audio(chunk)
                    if audio:
                        loop.call_soon_threadsafe(queue.put_nowait, audio)
            except Exception as error:  # surface, then unblock the consumer
                logger.error("Gemini TTS stream failed: %s", error, exc_info=True)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        producer = asyncio.create_task(asyncio.to_thread(_produce))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            await producer
