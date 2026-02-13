import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, cast

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.core.events import (
    UserTranscriptionReceived,
    build_event_envelope,
    to_redis_stream_fields,
)
from app.core.redis import RedisKeys, get_redis_client
from app.services.pipeline.services.soniox_service import soniox_service
from app.services.user.auth import supabase_auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


def _normalize_command_text(value: str) -> str:
    return " ".join(value.lower().split())


def _extract_websocket_bearer_token(websocket: WebSocket) -> Optional[str]:
    """Extract auth token from websocket headers or legacy query param."""
    authorization = websocket.headers.get("authorization")
    if not authorization or not authorization.startswith("Bearer "):
        # Backward-compatible fallback for older clients using query token.
        query_token = websocket.query_params.get("token")
        if query_token:
            return str(query_token)
        return None
    return authorization.replace("Bearer ", "")


async def publish_transcription(
    redis_conn,
    user_id: str,
    text: str,
    session_id: Optional[str] = None,
    alternatives: Optional[list[str]] = None,
    parse_hint: Optional[dict[str, Any]] = None,
) -> None:
    """Publish a typed Agent transcription event to the Redis stream."""
    normalized_alternatives = [str(item) for item in (alternatives or [])]
    normalized_parse_hint: Optional[dict[str, Any]] = None
    if isinstance(parse_hint, dict):
        normalized_parse_hint = {
            str(key): value
            for key, value in parse_hint.items()
            if isinstance(value, (str, int, float, bool))
        }
    event = UserTranscriptionReceived(
        content=text,
        alternatives=cast(Any, normalized_alternatives),
        parse_hint=normalized_parse_hint,
    )
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
    stream_fields = to_redis_stream_fields(entry)
    await redis_conn.xadd(
        RedisKeys.STREAM_VOICE_INPUT, cast(dict[Any, Any], stream_fields)
    )


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


@dataclass
class _TranscriptionSessionState:
    final_tokens: list[dict[str, Any]]
    transcription_active: bool = True
    chunk_count: int = 0
    pending_complete_transcription: Optional[str] = None
    pending_publish_task: Optional[asyncio.Task[None]] = None


async def _safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_json(payload)


async def _send_error_message(websocket: WebSocket, message: str) -> None:
    await _safe_send_json(websocket, {"type": "error", "message": message})


async def _authenticate_ws(websocket: WebSocket) -> tuple[str, str] | None:
    """Authenticate websocket and return (user_id, session_id)."""
    access_token = _extract_websocket_bearer_token(websocket)
    if not access_token:
        logger.warning("Missing or invalid auth token for STT websocket")
        await _send_error_message(websocket, "Missing or invalid auth token.")
        await websocket.close(code=1008)
        return None

    logger.info("Authenticating STT websocket user")
    user = await supabase_auth_service.get_user(access_token)
    if not user:
        logger.warning("Authentication failed: invalid or expired STT token")
        await _send_error_message(websocket, "Invalid or expired token.")
        await websocket.close(code=1008)
        return None

    raw_user_id = user.get("id")
    if not raw_user_id:
        logger.error("User object missing ID")
        await _send_error_message(websocket, "User ID missing from token.")
        await websocket.close(code=1008)
        return None

    user_id = str(raw_user_id)
    session_id = str(uuid.uuid4())
    logger.info("User %s authenticated. Starting STT session %s", user_id, session_id)
    return user_id, session_id


async def _connect_soniox(websocket: WebSocket, user_id: str):
    """Connect and configure Soniox websocket."""
    try:
        logger.info("Connecting to Soniox WebSocket for user %s...", user_id)
        soniox_ws = await websockets.connect(soniox_service.WEBSOCKET_URL)
        logger.info("Connected to Soniox WebSocket for user %s", user_id)
    except Exception as e:
        logger.error("Failed to connect to Soniox for user %s: %s", user_id, e, exc_info=True)
        await _send_error_message(websocket, "Failed to connect to transcription service.")
        await websocket.close(code=1011, reason="Soniox connection failed")
        return None

    config = soniox_service.get_config(
        audio_format="pcm_s16le",
        sample_rate=48000,
        num_channels=1,
        language_hints=["en"],
        enable_endpoint_detection=False,
    )
    logger.info("Sending Soniox config for user %s", user_id)
    await soniox_ws.send(json.dumps(config))
    logger.info("Soniox config sent successfully for user %s", user_id)
    return soniox_ws


def _compose_final_text(final_tokens: list[dict[str, Any]]) -> str:
    return "".join(str(token.get("text", "")) for token in final_tokens)


async def _listen_to_soniox(
    soniox_ws,
    websocket: WebSocket,
    state: _TranscriptionSessionState,
) -> None:
    """Listen for Soniox responses and forward to the client."""
    try:
        async for message in soniox_ws:
            response = json.loads(message)

            if response.get("error_code"):
                logger.error(
                    "Soniox error code=%s message=%s",
                    response.get("error_code"),
                    response.get("error_message"),
                )
                await _send_error_message(websocket, "Transcription service error.")
                continue

            tokens = response.get("tokens", [])
            if tokens:
                new_final_tokens: list[dict[str, Any]] = []
                non_final_tokens: list[dict[str, Any]] = []
                for token in tokens:
                    if token.get("text"):
                        if token.get("is_final"):
                            new_final_tokens.append(token)
                            state.final_tokens.append(token)
                        else:
                            non_final_tokens.append(token)

                final_text = _compose_final_text(state.final_tokens)
                non_final_text = "".join(
                    str(token.get("text", "")) for token in non_final_tokens
                )
                full_text = final_text + non_final_text

                if non_final_tokens:
                    await _safe_send_json(
                        websocket,
                        {"type": "partial", "text": full_text, "is_final": False},
                    )
                    logger.info("Partial: %s", full_text)

                if new_final_tokens:
                    await _safe_send_json(
                        websocket,
                        {"type": "final", "text": final_text, "is_final": True},
                    )
                    logger.info("Final tokens: %s", final_text)

            if response.get("finished"):
                complete_text = _compose_final_text(state.final_tokens)
                await _safe_send_json(
                    websocket, {"type": "complete", "text": complete_text}
                )
                logger.info("Session finished. Complete text: %s", complete_text)
                break
    except websockets.exceptions.ConnectionClosed:
        logger.info("Soniox WebSocket closed")
    except Exception as e:
        logger.error("Error in Soniox listener: %s", e, exc_info=True)
        await _send_error_message(websocket, "Transcription error.")


def _cancel_pending_publish(state: _TranscriptionSessionState) -> None:
    if state.pending_publish_task:
        state.pending_publish_task.cancel()
        state.pending_publish_task = None


def _schedule_pending_transcription_publish(
    *,
    state: _TranscriptionSessionState,
    redis_conn: Any,
    user_id: str,
    session_id: str,
) -> None:
    expected_text = state.pending_complete_transcription
    if not expected_text:
        return

    _cancel_pending_publish(state)

    async def _publish_pending_transcription() -> None:
        try:
            await asyncio.sleep(0.7)
            if state.pending_complete_transcription != expected_text:
                return
            await publish_transcription(
                redis_conn,
                user_id,
                expected_text,
                session_id=session_id,
            )
            logger.info(
                "Published fallback transcription after END because no explicit command message arrived"
            )
        except asyncio.CancelledError:
            return
        finally:
            if state.pending_complete_transcription == expected_text:
                state.pending_complete_transcription = None
            state.pending_publish_task = None

    state.pending_publish_task = asyncio.create_task(_publish_pending_transcription())
    logger.info(
        "Final transcription ready for user %s; waiting briefly for explicit command message from client",
        user_id,
    )


async def _handle_command_message(
    text_data: str,
    *,
    state: _TranscriptionSessionState,
    websocket: WebSocket,
    redis_conn: Any,
    user_id: str,
    session_id: str,
) -> bool:
    try:
        json_data = json.loads(text_data)
    except json.JSONDecodeError:
        return False

    if json_data.get("type") != "command":
        return False

    command_text = str(json_data.get("text", ""))
    mode = str(json_data.get("mode", "auto"))
    stream = bool(json_data.get("stream", False))
    parse_hint = (
        json_data.get("parse_hint") if isinstance(json_data.get("parse_hint"), dict) else None
    )
    logger.info(
        "Received command from user %s (mode=%s, stream=%s, has_parse_hint=%s): %s",
        user_id,
        mode,
        stream,
        bool(parse_hint),
        command_text,
    )

    if state.pending_publish_task and state.pending_complete_transcription:
        if _normalize_command_text(command_text) == _normalize_command_text(
            state.pending_complete_transcription
        ):
            _cancel_pending_publish(state)
            state.pending_complete_transcription = None
            logger.info(
                "Cancelled fallback transcription publish because explicit command message arrived"
            )

    await _safe_send_json(websocket, {"type": "command_queued", "text": command_text})
    await publish_transcription(
        redis_conn,
        user_id,
        command_text,
        session_id=session_id,
        parse_hint=cast(Optional[dict[str, Any]], parse_hint),
    )
    logger.info("Command queued for Agent")
    return True


async def _handle_end_signal(
    *,
    state: _TranscriptionSessionState,
    soniox_ws: Any,
    soniox_task: asyncio.Task[None],
    redis_conn: Any,
    user_id: str,
    session_id: str,
) -> None:
    logger.info("Received END signal from client")
    if not state.transcription_active:
        return

    state.transcription_active = False
    await soniox_ws.send("")
    await soniox_task

    complete_text = _compose_final_text(state.final_tokens).strip()
    if complete_text:
        state.pending_complete_transcription = complete_text
        _schedule_pending_transcription_publish(
            state=state,
            redis_conn=redis_conn,
            user_id=user_id,
            session_id=session_id,
        )


async def _forward_audio_chunk(
    *,
    state: _TranscriptionSessionState,
    soniox_ws: Any,
    websocket: WebSocket,
    audio_chunk: bytes,
) -> bool:
    state.chunk_count += 1
    if len(audio_chunk) > 0:
        if state.transcription_active:
            try:
                await soniox_ws.send(audio_chunk)
                logger.debug(
                    "Chunk #%s: forwarded %s bytes to Soniox",
                    state.chunk_count,
                    len(audio_chunk),
                )
            except Exception as e:
                logger.error(
                    "Failed to send chunk #%s to Soniox: %s",
                    state.chunk_count,
                    e,
                    exc_info=True,
                )
                await _send_error_message(
                    websocket, "Failed to send audio to transcription service."
                )
                return False
    else:
        logger.warning("Chunk #%s: empty chunk, skipping", state.chunk_count)

    await _safe_send_json(
        websocket,
        {
            "type": "ack",
            "chunk_number": state.chunk_count,
            "bytes_received": len(audio_chunk),
        },
    )
    return True


async def _process_client_messages(
    *,
    websocket: WebSocket,
    redis_conn: Any,
    user_id: str,
    session_id: str,
    soniox_ws: Any,
    soniox_task: asyncio.Task[None],
    state: _TranscriptionSessionState,
) -> None:
    try:
        while True:
            try:
                message = await websocket.receive()
            except RuntimeError as e:
                if 'Cannot call "receive" once a disconnect' in str(e):
                    logger.info("Client already disconnected")
                    break
                raise

            if message.get("type") == "websocket.disconnect":
                logger.info("Client disconnected")
                break

            if "text" in message:
                text_data = str(message["text"])
                was_command = await _handle_command_message(
                    text_data,
                    state=state,
                    websocket=websocket,
                    redis_conn=redis_conn,
                    user_id=user_id,
                    session_id=session_id,
                )
                if was_command:
                    continue

                if text_data == "END":
                    await _handle_end_signal(
                        state=state,
                        soniox_ws=soniox_ws,
                        soniox_task=soniox_task,
                        redis_conn=redis_conn,
                        user_id=user_id,
                        session_id=session_id,
                    )
                continue

            if "bytes" in message:
                audio_chunk = message["bytes"]
                if not isinstance(audio_chunk, bytes):
                    continue
                should_continue = await _forward_audio_chunk(
                    state=state,
                    soniox_ws=soniox_ws,
                    websocket=websocket,
                    audio_chunk=audio_chunk,
                )
                if not should_continue:
                    break
    except WebSocketDisconnect:
        logger.info("Client disconnected")


@router.websocket("/stream")
async def stream_transcribe(
    websocket: WebSocket,
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
    hermes_task: Optional[asyncio.Task[None]] = None
    soniox_task: Optional[asyncio.Task[None]] = None
    state = _TranscriptionSessionState(final_tokens=[])

    try:
        auth = await _authenticate_ws(websocket)
        if auth is None:
            return
        user_id, session_id = auth

        logger.info("Connecting to Redis...")
        redis_conn = await get_redis_client()
        logger.info("Redis connected")

        soniox_ws = await _connect_soniox(websocket, user_id)
        if soniox_ws is None:
            return

        soniox_task = asyncio.create_task(_listen_to_soniox(soniox_ws, websocket, state))

        # Give Soniox a moment to process config and avoid first-chunk timeout.
        await asyncio.sleep(0.1)

        hermes_task = asyncio.create_task(
            stream_hermes_updates(websocket, redis_conn, user_id)
        )

        await _safe_send_json(websocket, {"type": "ready"})
        logger.info("Sent ready signal to client")

        await _process_client_messages(
            websocket=websocket,
            redis_conn=redis_conn,
            user_id=user_id,
            session_id=session_id,
            soniox_ws=soniox_ws,
            soniox_task=cast(asyncio.Task[None], soniox_task),
            state=state,
        )
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await _send_error_message(websocket, "Internal server error.")
                await websocket.close(code=1011, reason="Internal server error")
            except Exception as close_error:
                logger.debug(
                    "Failed to send/close websocket after error: %s",
                    close_error,
                    exc_info=True,
                )
    finally:
        if soniox_task:
            soniox_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await soniox_task
        if soniox_ws:
            try:
                await soniox_ws.close()
            except Exception as close_error:
                logger.debug(
                    "Failed to close Soniox websocket: %s",
                    close_error,
                    exc_info=True,
                )
        if hermes_task:
            hermes_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hermes_task
        if state.pending_publish_task:
            state.pending_publish_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.pending_publish_task
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")
