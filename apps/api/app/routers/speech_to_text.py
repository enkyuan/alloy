"""Router for speech-to-text functionality."""
import logging
from io import BytesIO

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status

from app.services.auth import supabase_auth_service
from app.services.elevenlabs import elevenlabs_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stt", tags=["speech-to-text"])


@router.post("/transcribe")
async def transcribe_audio(
    authorization: str = Header(None),
    file: UploadFile = File(...),
):
    """Transcribes audio using Eleven Labs Speech to Text."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    access_token = authorization.replace("Bearer ", "")
    supabase_user = await supabase_auth_service.get_user(access_token)

    if not supabase_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    try:
        audio_data = BytesIO(await file.read())
        transcription = elevenlabs_service.convert(audio_data)
        return transcription
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to transcribe audio.",
        )
