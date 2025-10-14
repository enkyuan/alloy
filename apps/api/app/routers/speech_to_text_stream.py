"""WebSocket router for real-time speech-to-text streaming."""
import logging
import json
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.websockets import WebSocketState

from app.services.auth import supabase_auth_service
from app.services.elevenlabs import elevenlabs_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


@router.websocket("/stream")
async def stream_transcribe(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time speech-to-text streaming.
    
    Client sends:
    - Binary audio chunks continuously while recording
    - Text message "END" when recording stops
    
    Server sends:
    - JSON with partial transcriptions: {"type": "partial", "text": "..."}
    - JSON with final transcription: {"type": "final", "text": "..."}
    - JSON with errors: {"type": "error", "message": "..."}
    """
    await websocket.accept()
    
    audio_buffer = BytesIO()
    authenticated = False
    
    try:
        # Authenticate via token in query param
        if not token:
            await websocket.send_json({
                "type": "error",
                "message": "Missing authentication token"
            })
            await websocket.close(code=1008)
            return
        
        user = await supabase_auth_service.get_user(token)
        if not user:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid or expired token"
            })
            await websocket.close(code=1008)
            return
        
        authenticated = True
        logger.info(f"User {user.get('id')} connected to STT stream")
        
        # Send ready message
        await websocket.send_json({"type": "ready"})
        
        # Receive audio chunks
        while True:
            message = await websocket.receive()
            
            # Handle text messages (control signals)
            if "text" in message:
                text_data = message["text"]
                
                if text_data == "END":
                    # Process accumulated audio
                    logger.info(f"Processing {audio_buffer.tell()} bytes of audio")
                    
                    if audio_buffer.tell() == 0:
                        await websocket.send_json({
                            "type": "error",
                            "message": "No audio data received"
                        })
                        break
                    
                    # Reset buffer position for reading
                    audio_buffer.seek(0)
                    
                    try:
                        # Transcribe with ElevenLabs
                        transcription = elevenlabs_service.convert(audio_buffer)
                        
                        # Send final transcription
                        await websocket.send_json({
                            "type": "final",
                            "text": transcription.text,
                            "language_code": transcription.language_code,
                            "language_probability": transcription.language_probability
                        })
                        logger.info(f"Transcription complete: {transcription.text}")
                        
                    except Exception as e:
                        logger.error(f"Transcription error: {e}", exc_info=True)
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Transcription failed: {str(e)}"
                        })
                    
                    break
            
            # Handle binary messages (audio data)
            elif "bytes" in message:
                audio_chunk = message["bytes"]
                audio_buffer.write(audio_chunk)
                
                # Send acknowledgment for each chunk
                await websocket.send_json({
                    "type": "ack",
                    "bytes_received": len(audio_chunk),
                    "total_bytes": audio_buffer.tell()
                })
        
    except WebSocketDisconnect:
        logger.info("Client disconnected from STT stream")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
            except:
                pass
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        audio_buffer.close()
