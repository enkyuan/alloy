import asyncio
import json
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.services.auth import supabase_auth_service
from app.services.soniox import soniox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


@router.websocket("/stream")
async def stream_transcribe(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """WebSocket router for real-time speech-to-text streaming with Soniox.

    Client sends:
    - Binary audio chunks continuously while recording (PCM audio)
    - Text message "END" when recording stops

    Server sends:
    - JSON with partial transcriptions: {"type": "partial", "text": "...", "is_final": false}
    - JSON with final transcriptions: {"type": "final", "text": "...", "is_final": true}
    - JSON with complete result: {"type": "complete", "text": "..."}
    - JSON with errors: {"type": "error", "message": "..."}
    """
    await websocket.accept()

    soniox_ws = None
    final_tokens = []

    try:
        # Authenticate via token in query param
        if not token:
            await websocket.send_json(
                {"type": "error", "message": "Missing authentication token"}
            )
            await websocket.close(code=1008)
            return

        user = await supabase_auth_service.get_user(token)
        if not user:
            await websocket.send_json(
                {"type": "error", "message": "Invalid or expired token"}
            )
            await websocket.close(code=1008)
            return

        logger.info(f"User {user.get('id')} connected to STT stream")

        # Connect to Soniox WebSocket
        try:
            soniox_ws = await websockets.connect(soniox_service.WEBSOCKET_URL)
            logger.info("Connected to Soniox WebSocket")
        except Exception as e:
            logger.error(f"Failed to connect to Soniox: {e}")
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Failed to connect to transcription service: {str(e)}",
                }
            )
            await websocket.close()
            return

        # Send Soniox configuration
        # Using PCM format: 48kHz, mono, 16-bit signed little-endian
        config = soniox_service.get_config(
            audio_format="pcm_s16le",
            sample_rate=48000,
            num_channels=1,
            language_hints=["en"],
            enable_endpoint_detection=False,  # We'll handle endpoint manually
        )
        await soniox_ws.send(json.dumps(config))
        logger.info(f"Sent Soniox config: {config}")

        # Start listening to Soniox responses
        async def listen_to_soniox():
            """Listen for responses from Soniox and forward to client."""
            nonlocal final_tokens
            try:
                async for message in soniox_ws:
                    response = json.loads(message)

                    # Check for errors from Soniox
                    if response.get("error_code"):
                        error_msg = f"Soniox error {response['error_code']}: {response.get('error_message', 'Unknown error')}"
                        logger.error(error_msg)
                        await websocket.send_json(
                            {"type": "error", "message": error_msg}
                        )
                        continue
                        await websocket.send_json(
                            {"type": "error", "message": error_msg}
                        )
                        continue

                    # Process tokens
                    tokens = response.get("tokens", [])
                    if tokens:
                        # Separate final and non-final tokens
                        new_final_tokens = []
                        non_final_tokens = []
                        for token in tokens:
                            if token.get("text"):
                                if token.get("is_final"):
                                    new_final_tokens.append(token)
                                    final_tokens.append(token)
                                else:
                                    non_final_tokens.append(token)

                        # Build full transcription text
                        final_text = "".join([t["text"] for t in final_tokens])
                        non_final_text = "".join([t["text"] for t in non_final_tokens])
                        full_text = final_text + non_final_text

                        # Send partial update if we have non-final tokens
                        if non_final_tokens:
                            await websocket.send_json(
                                {
                                    "type": "partial",
                                    "text": full_text,
                                    "is_final": False,
                                }
                            )
                            logger.info(f"📝 Partial: {full_text}")

                        # Send final update if we have new final tokens
                        if new_final_tokens:
                            await websocket.send_json(
                                {"type": "final", "text": final_text, "is_final": True}
                            )
                            logger.info(f"✅ Final tokens: {final_text}")

                    # Check if session finished
                    if response.get("finished"):
                        # Send complete transcription
                        complete_text = "".join([t["text"] for t in final_tokens])
                        await websocket.send_json(
                            {"type": "complete", "text": complete_text}
                        )
                        logger.info(
                            f"🏁 Session finished. Complete text: {complete_text}"
                        )
                        break

            except websockets.exceptions.ConnectionClosed:
                logger.info("Soniox WebSocket closed")
            except Exception as e:
                logger.error(f"Error in Soniox listener: {e}", exc_info=True)
                await websocket.send_json(
                    {"type": "error", "message": f"Transcription error: {str(e)}"}
                )

        # Start Soniox listener task
        soniox_task = asyncio.create_task(listen_to_soniox())
        
        # Give Soniox a moment to process the config and be ready
        # This prevents 408 timeout on first chunks
        await asyncio.sleep(0.1)
        
        # Now send ready message to client
        await websocket.send_json({"type": "ready"})
        logger.info("Sent ready signal to client")

        # Receive audio chunks from client
        chunk_count = 0
        try:
            while True:
                message = await websocket.receive()

                # Handle text messages (control signals)
                if "text" in message:
                    text_data = message["text"]
                    if text_data == "END":
                        logger.info("Received END signal from client")
                        # Send empty frame to Soniox to signal end of audio
                        await soniox_ws.send("")
                        # Wait for final response from Soniox
                        await soniox_task
                        break

                # Handle binary messages (audio chunks)
                elif "bytes" in message:
                    audio_chunk = message["bytes"]
                    chunk_count += 1

                    # Client now sends raw PCM data (no WAV header)
                    # Forward directly to Soniox
                    if len(audio_chunk) > 0:
                        await soniox_ws.send(audio_chunk)
                        logger.debug(
                            f"Chunk #{chunk_count}: forwarded {len(audio_chunk)} bytes to Soniox"
                        )
                    else:
                        logger.warning(f"Chunk #{chunk_count}: empty chunk, skipping")

                    # Send acknowledgment to client
                    await websocket.send_json(
                        {
                            "type": "ack",
                            "chunk_number": chunk_count,
                            "bytes_received": len(audio_chunk),
                        }
                    )
        except WebSocketDisconnect:
            logger.info("Client disconnected")

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except:
                pass

    finally:
        # Clean up
        if soniox_ws:
            try:
                await soniox_ws.close()
            except:
                pass
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")