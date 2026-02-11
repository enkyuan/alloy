import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, cast

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.core.events import UserTranscriptionReceived, build_event_envelope
from app.core.redis import RedisKeys, get_redis_client
from app.services.pipeline.soniox import soniox_service
from app.services.user.auth import supabase_auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


async def publish_transcription(
    redis_conn,
    user_id: str,
    text: str,
    session_id: Optional[str] = None,
) -> None:
    """Publish a typed Agent transcription event to the Redis stream."""
    event = UserTranscriptionReceived(content=text)
    metadata: dict[str, Any] = {
        "timestamp": str(datetime.now(timezone.utc).timestamp()),
        "source": "stt.router",
    }
    if session_id:
        metadata["session_id"] = session_id

    entry = build_event_envelope(
        event_type="user.transcription",
        user_id=user_id,
        payload=event,
        metadata=metadata,
    )
    await redis_conn.xadd(RedisKeys.STREAM_VOICE_INPUT, cast(dict[Any, Any], entry))


async def forward_hermes_updates(
    websocket: WebSocket,
    redis_conn,
    user_id: str,
    timeout: float = 15.0,
) -> bool:
    """Forward Agent updates for a user from Redis pubsub to the websocket."""
    pubsub = redis_conn.pubsub()
    await pubsub.subscribe(RedisKeys.CHANNEL_USER_UPDATES)
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=timeout
            )
            if message is None:
                return False

            data = message.get("data")
            if not data:
                continue

            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            if event.get("user_id") != user_id:
                continue

            await websocket.send_json(event)
            if event.get("type") == "agent.response":
                return True
    finally:
        await pubsub.unsubscribe(RedisKeys.CHANNEL_USER_UPDATES)
        await pubsub.close()


async def stream_hermes_updates(
    websocket: WebSocket,
    redis_conn,
    user_id: str,
):
    """Continuously forward Agent updates for a user from Redis pubsub to the websocket."""
    pubsub = redis_conn.pubsub()
    await pubsub.subscribe(RedisKeys.CHANNEL_USER_UPDATES)
    try:
        while True:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    await asyncio.sleep(0.1)
                    continue

                data = message.get("data")
                if not data:
                    continue

                try:
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if event.get("user_id") != user_id:
                    continue

                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(event)
                else:
                    break
            except Exception as e:
                logger.error(f"Error relaying Agent update: {e}")
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Agent stream task cancelled")
    finally:
        await pubsub.unsubscribe(RedisKeys.CHANNEL_USER_UPDATES)
        await pubsub.close()


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
    logger.info("WebSocket connection accepted")

    soniox_ws = None
    hermes_task = None
    final_tokens = []

    try:
        # Authenticate via token in query param
        if not token:
            logger.warning("No authentication token provided")
            await websocket.send_json(
                {"type": "error", "message": "Missing authentication token"}
            )
            await websocket.close(code=1008)
            return

        logger.info(f"Authenticating user with token: {token[:10]}...")
        user = await supabase_auth_service.get_user(token)
        if not user:
            logger.warning(
                f"Authentication failed: Invalid token provided. Token: {token[:10]}..."
            )
            await websocket.send_json(
                {"type": "error", "message": "Invalid or expired token"}
            )
            await websocket.close(code=1008)
            return

        user_id = user.get("id")
        if not user_id:
            logger.error("User object missing ID")
            await websocket.send_json(
                {"type": "error", "message": "User ID missing from token"}
            )
            await websocket.close(code=1008)
            return
        user_id = str(user_id)
        session_id = str(uuid.uuid4())
        logger.info(f"User {user_id} authenticated. Starting STT session {session_id}")

        logger.info("Connecting to Redis...")
        redis_conn = await get_redis_client()
        logger.info("Redis connected")

        # Connect to Soniox WebSocket
        try:
            logger.info(f"Connecting to Soniox WebSocket for user {user_id}...")
            soniox_ws = await websockets.connect(soniox_service.WEBSOCKET_URL)
            logger.info(f"Connected to Soniox WebSocket for user {user_id}")
        except Exception as e:
            logger.error(
                f"Failed to connect to Soniox for user {user_id}: {e}", exc_info=True
            )
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Failed to connect to transcription service: {str(e)}",
                }
            )
            await websocket.close(code=1011, reason="Soniox connection failed")
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
        logger.info(f"Sending Soniox config for user {user_id}: {config}")
        await soniox_ws.send(json.dumps(config))
        logger.info(f"Soniox config sent successfully for user {user_id}")

        # Start listening to Soniox responses
        async def listen_to_soniox():
            """Listen for responses from Soniox and forward to client."""
            nonlocal final_tokens
            try:
                assert soniox_ws is not None
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
                            logger.info(f"Partial: {full_text}")

                        # Send final update if we have new final tokens
                        if new_final_tokens:
                            await websocket.send_json(
                                {"type": "final", "text": final_text, "is_final": True}
                            )
                            logger.info(f"Final tokens: {final_text}")

                    # Check if session finished
                    if response.get("finished"):
                        # Send complete transcription
                        complete_text = "".join([t["text"] for t in final_tokens])
                        await websocket.send_json(
                            {"type": "complete", "text": complete_text}
                        )
                        logger.info(f"Session finished. Complete text: {complete_text}")
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

        # Start Agent listener task
        hermes_task = asyncio.create_task(
            stream_hermes_updates(websocket, redis_conn, user_id)
        )

        # Now send ready message to client
        await websocket.send_json({"type": "ready"})
        logger.info("Sent ready signal to client")

        # Receive audio chunks and command messages from client
        chunk_count = 0
        transcription_active = True
        try:
            while True:
                try:
                    message = await websocket.receive()
                except RuntimeError as e:
                    if 'Cannot call "receive" once a disconnect' in str(
                        e
                    ):
                        logger.info("Client already disconnected")
                        break
                    raise

                if message.get("type") == "websocket.disconnect":
                    logger.info("Client disconnected")
                    break

                # Handle text messages (control signals and commands)
                if "text" in message:
                    text_data = message["text"]

                    # Check if it's a JSON command message
                    try:
                        json_data = json.loads(text_data)

                        # Handle command messages
                        if json_data.get("type") == "command":
                            command_text = json_data.get("text", "")
                            mode = json_data.get("mode", "auto")
                            stream = json_data.get("stream", False)
                            logger.info(
                                f"Received command from user {user_id} (mode={mode}, stream={stream}): {command_text}"
                            )

                            await websocket.send_json(
                                {"type": "command_queued", "text": command_text}
                            )
                            await publish_transcription(
                                redis_conn, user_id, command_text, session_id=session_id
                            )
                            logger.info("Command queued for Agent")
                            continue

                    except json.JSONDecodeError:
                        # Not JSON, treat as control signal
                        pass

                    # Handle END signal
                    if text_data == "END":
                        logger.info("Received END signal from client")
                        if transcription_active:
                            transcription_active = False
                            # Send empty frame to Soniox to signal end of audio
                            await soniox_ws.send("")
                            # Wait for final response from Soniox
                            await soniox_task

                            # Publish the complete transcription to Agent/Redis now
                            complete_text = "".join([t["text"] for t in final_tokens])
                            if complete_text.strip():
                                try:
                                    logger.info(
                                        f"Publishing complete transcription to Redis for user {user_id}"
                                    )
                                    await publish_transcription(
                                        redis_conn,
                                        user_id,
                                        complete_text,
                                        session_id=session_id,
                                    )
                                    logger.info(
                                        f"Successfully published complete utterance: {complete_text[:50]}..."
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Failed to publish to Redis: {e}",
                                        exc_info=True,
                                    )

                        # Do NOT break here; keep connection open for Agent updates
                        continue

                # Handle binary messages (audio chunks)
                elif "bytes" in message:
                    audio_chunk = message["bytes"]
                    chunk_count += 1

                    # Client now sends raw PCM data (no WAV header)
                    # Forward directly to Soniox
                    if len(audio_chunk) > 0:
                        if transcription_active:
                            try:
                                await soniox_ws.send(audio_chunk)
                                logger.debug(
                                    f"Chunk #{chunk_count}: forwarded {len(audio_chunk)} bytes to Soniox"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to send chunk #{chunk_count} to Soniox: {e}",
                                    exc_info=True,
                                )
                                await websocket.send_json(
                                    {
                                        "type": "error",
                                        "message": f"Failed to send audio to transcription service: {str(e)}",
                                    }
                                )
                                break
                        else:
                            # Silently ignore chunks after END
                            pass
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
                await websocket.close(code=1011, reason="Internal server error")
            except:
                pass

    finally:
        # Clean up
        if soniox_ws:
            try:
                await soniox_ws.close()
            except:
                pass
        if hermes_task:
            hermes_task.cancel()
            try:
                await hermes_task
            except asyncio.CancelledError:
                pass
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")
