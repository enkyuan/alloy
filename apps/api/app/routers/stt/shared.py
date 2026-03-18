"""Shared STT websocket helpers for auth, event publishing, and client message handling."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, cast

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.core.events import (
    UserTranscriptionReceived,
    build_event_envelope,
    to_redis_stream_fields,
)
from app.core.redis import RedisKeys
from app.services.user.auth import supabase_auth_service

logger = logging.getLogger(__name__)


def normalize_command_text(value: str) -> str:
    return " ".join(value.lower().split())


def extract_websocket_bearer_token(websocket: WebSocket) -> Optional[str]:
    """Extract auth token from websocket headers or legacy query param."""
    authorization = websocket.headers.get("authorization")
    if not authorization or not authorization.startswith("Bearer "):
        query_token = websocket.query_params.get("token")
        if query_token:
            return str(query_token)
        return None
    return authorization.replace("Bearer ", "")


async def publish_transcription(
    redis_conn: Any,
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
    redis_conn: Any,
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
    redis_conn: Any,
    user_id: str,
) -> None:
    """Continuously forward Agent updates for a user from Redis pubsub to websocket."""
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
            except Exception as error:
                logger.error("Error relaying Agent update: %s", error)
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Agent stream task cancelled")
    finally:
        await pubsub.unsubscribe(RedisKeys.CHANNEL_USER_UPDATES)
        await pubsub.close()


@dataclass
class TranscriptionSessionState:
    final_tokens: list[dict[str, Any]]
    transcription_active: bool = True
    chunk_count: int = 0
    pending_complete_transcription: Optional[str] = None
    pending_publish_task: Optional[asyncio.Task[None]] = None


async def safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_json(payload)


async def send_error_message(websocket: WebSocket, message: str) -> None:
    await safe_send_json(websocket, {"type": "error", "message": message})


async def authenticate_ws(websocket: WebSocket) -> tuple[str, str] | None:
    """Authenticate websocket and return (user_id, session_id)."""
    access_token = extract_websocket_bearer_token(websocket)
    if not access_token:
        logger.warning("Missing or invalid auth token for STT websocket")
        await send_error_message(websocket, "Missing or invalid auth token.")
        await websocket.close(code=1008)
        return None

    logger.info("Authenticating STT websocket user")
    user = await supabase_auth_service.get_user(access_token)
    if not user:
        logger.warning("Authentication failed: invalid or expired STT token")
        await send_error_message(websocket, "Invalid or expired token.")
        await websocket.close(code=1008)
        return None

    raw_user_id = user.get("id")
    if not raw_user_id:
        logger.error("User object missing ID")
        await send_error_message(websocket, "User ID missing from token.")
        await websocket.close(code=1008)
        return None

    user_id = str(raw_user_id)
    session_id = str(uuid.uuid4())
    logger.info("User %s authenticated. Starting STT session %s", user_id, session_id)
    return user_id, session_id


def compose_final_text(final_tokens: list[dict[str, Any]]) -> str:
    return "".join(str(token.get("text", "")) for token in final_tokens)


def cancel_pending_publish(state: TranscriptionSessionState) -> None:
    if state.pending_publish_task:
        state.pending_publish_task.cancel()
        state.pending_publish_task = None


def schedule_pending_transcription_publish(
    *,
    state: TranscriptionSessionState,
    redis_conn: Any,
    user_id: str,
    session_id: str,
) -> None:
    expected_text = state.pending_complete_transcription
    if not expected_text:
        return

    cancel_pending_publish(state)

    async def _publish_pending_transcription() -> None:
        try:
            await asyncio.sleep(0.7)
            if state.pending_complete_transcription != expected_text:
                return
            assert expected_text is not None
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


async def handle_command_message(
    text_data: str,
    *,
    state: TranscriptionSessionState,
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
        json_data.get("parse_hint")
        if isinstance(json_data.get("parse_hint"), dict)
        else None
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
        if normalize_command_text(command_text) == normalize_command_text(
            state.pending_complete_transcription
        ):
            cancel_pending_publish(state)
            state.pending_complete_transcription = None
            logger.info(
                "Cancelled fallback transcription publish because explicit command message arrived"
            )

    await safe_send_json(websocket, {"type": "command_queued", "text": command_text})
    await publish_transcription(
        redis_conn,
        user_id,
        command_text,
        session_id=session_id,
        parse_hint=cast(Optional[dict[str, Any]], parse_hint),
    )
    logger.info("Command queued for Agent")
    return True


async def handle_end_signal(
    *,
    state: TranscriptionSessionState,
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

    complete_text = compose_final_text(state.final_tokens).strip()
    if complete_text:
        state.pending_complete_transcription = complete_text
        schedule_pending_transcription_publish(
            state=state,
            redis_conn=redis_conn,
            user_id=user_id,
            session_id=session_id,
        )


async def forward_audio_chunk(
    *,
    state: TranscriptionSessionState,
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
            except Exception as error:
                logger.error(
                    "Failed to send chunk #%s to Soniox: %s",
                    state.chunk_count,
                    error,
                    exc_info=True,
                )
                await send_error_message(
                    websocket, "Failed to send audio to transcription service."
                )
                return False
    else:
        logger.warning("Chunk #%s: empty chunk, skipping", state.chunk_count)

    await safe_send_json(
        websocket,
        {
            "type": "ack",
            "chunk_number": state.chunk_count,
            "bytes_received": len(audio_chunk),
        },
    )
    return True


async def process_client_messages(
    *,
    websocket: WebSocket,
    redis_conn: Any,
    user_id: str,
    session_id: str,
    soniox_ws: Any,
    soniox_task: asyncio.Task[None],
    state: TranscriptionSessionState,
) -> None:
    try:
        while True:
            try:
                message = await websocket.receive()
            except RuntimeError as error:
                if 'Cannot call "receive" once a disconnect' in str(error):
                    logger.info("Client already disconnected")
                    break
                raise

            if message.get("type") == "websocket.disconnect":
                logger.info("Client disconnected")
                break

            if "text" in message:
                text_data = str(message["text"])
                was_command = await handle_command_message(
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
                    await handle_end_signal(
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
                should_continue = await forward_audio_chunk(
                    state=state,
                    soniox_ws=soniox_ws,
                    websocket=websocket,
                    audio_chunk=audio_chunk,
                )
                if not should_continue:
                    break
    except WebSocketDisconnect:
        logger.info("Client disconnected")
