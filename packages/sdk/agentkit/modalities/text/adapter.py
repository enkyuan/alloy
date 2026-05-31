"""Text modality adapter for non-voice chat sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TextSessionConfig:
    session_id: str
    user_id: str
    modality: str = "text"


class TextModalityAdapter:
    """Facade for text-based session setup (placeholder for future chat wiring)."""

    modality = "text"

    def create_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        config = TextSessionConfig(session_id=session_id, user_id=user_id)
        return {
            "session_id": config.session_id,
            "user_id": config.user_id,
            "modality": config.modality,
        }
