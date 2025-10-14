"""ElevenLabs service for speech-to-text."""
import logging
from io import BytesIO
from elevenlabs import ElevenLabs
from app.config import settings

logger = logging.getLogger(__name__)

class ElevenLabsService:
    """Service for interacting with the ElevenLabs API."""

    def __init__(self):
        if not settings.ELEVENLABS_API_KEY:
            logger.warning("ELEVENLABS_API_KEY is not set. Speech-to-text will not be available.")
            self.client = None
        else:
            self.client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

    def convert(self, audio_data: BytesIO):
        """Converts audio data to text.

        Args:
            audio_data: In-memory binary data of the audio file.

        Returns:
            The transcription result.

        Raises:
            Exception: If the API call fails.
        """
        if not self.client:
            raise Exception("ElevenLabs client is not initialized.")

        try:
            transcription = self.client.speech_to_text.convert(
                file=audio_data,
                model_id="scribe_v1",
                tag_audio_events=True,
                language_code="eng",
                diarize=True,
            )
            return transcription
        except Exception as e:
            logger.error(f"ElevenLabs API error: {e}", exc_info=True)
            raise

elevenlabs_service = ElevenLabsService()
