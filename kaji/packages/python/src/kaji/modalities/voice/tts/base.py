"""TTS provider protocol.

Concrete providers implement this Protocol. The streaming variant yields
audio chunks as they are synthesized; the batch variant returns the full
payload.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class TTSProvider(Protocol):
    """Synthesize text into audio bytes."""

    async def synthesize(self, text: str) -> bytes:
        """Return the full synthesized audio for `text`."""
        ...

    def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks for `text` as they become available."""
        ...
