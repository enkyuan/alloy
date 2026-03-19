"""Soniox WebSocket service for real-time speech-to-text."""

import logging
import json
from typing import Optional, Callable, Dict, Any
import asyncio

from app.core.config import settings

logger = logging.getLogger(__name__)


class SonioxService:
    """Service for real-time speech-to-text via Soniox WebSocket API."""

    WEBSOCKET_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

    def __init__(self):
        if not settings.SONIOX_API_KEY:
            logger.warning(
                "SONIOX_API_KEY is not set. Real-time transcription will not be available."
            )
            self.api_key = None
        else:
            self.api_key = settings.SONIOX_API_KEY

    def get_config(
        self,
        audio_format: str = "pcm_s16le",
        sample_rate: int = 48000,
        num_channels: int = 1,
        language_hints: Optional[list[str]] = None,
        enable_endpoint_detection: bool = False,
    ) -> Dict[str, Any]:
        """Get Soniox STT configuration.

        Args:
            audio_format: Audio format (e.g., "pcm_s16le", "auto")
            sample_rate: Sample rate in Hz (e.g., 48000, 16000)
            num_channels: Number of audio channels (1 for mono, 2 for stereo)
            language_hints: List of language codes to improve accuracy (e.g., ["en", "es"])
            enable_endpoint_detection: Enable automatic endpoint detection

        Returns:
            Configuration dictionary for Soniox WebSocket API
        """
        if not self.api_key:
            raise Exception("Soniox API key is not configured.")

        config = {
            "api_key": self.api_key,
            "model": "stt-rt-preview",
            "audio_format": audio_format,
        }

        # Add sample rate and channels for raw audio formats
        if audio_format != "auto":
            config["sample_rate"] = sample_rate
            config["num_channels"] = num_channels

        # Add language hints if provided
        if language_hints:
            config["language_hints"] = language_hints

        # Add endpoint detection if enabled
        if enable_endpoint_detection:
            config["enable_endpoint_detection"] = enable_endpoint_detection

        return config


soniox_service = SonioxService()
