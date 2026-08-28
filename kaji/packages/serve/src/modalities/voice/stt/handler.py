"""Shared STT WebSocket helpers for auth and client message handling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from kaji.core.safe_logging import log_redacted_failure
from kaji_serve.config import settings
from kaji_serve.server.auth_utils import decode_bearer_token

logger = logging.getLogger(__name__)


def extract_websocket_access_token(websocket: WebSocket) -> Optional[str]:
    """Extract bearer auth or an origin-bound host-managed browser cookie."""
    authorization = websocket.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")

    cookie_token = websocket.cookies.get("kaji_access_token")
    if not cookie_token:
        return None

    origin = websocket.headers.get("origin")
    if not origin or origin not in settings.cors_allow_origins:
        return None
    return str(cookie_token)


@dataclass
class TranscriptionSessionState:
    final_tokens: list[dict[str, Any]]
    transcription_active: bool = True
    chunk_count: int = 0


async def safe_send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    if websocket.client_state == WebSocketState.CONNECTED:
        await websocket.send_json(payload)


async def send_error_message(websocket: WebSocket, message: str) -> None:
    await safe_send_json(websocket, {"type": "error", "message": message})


async def authenticate_ws(websocket: WebSocket) -> str | None:
    """Authenticate the WebSocket and return the caller's user ID."""
    access_token = extract_websocket_access_token(websocket)
    if not access_token:
        logger.warning("Missing or invalid auth token for STT websocket")
        await send_error_message(websocket, "Missing or invalid auth token.")
        await websocket.close(code=1008)
        return None

    logger.info("Authenticating STT websocket user")
    try:
        payload = decode_bearer_token(access_token)
    except Exception:
        logger.warning("Authentication failed: invalid or expired STT token")
        await send_error_message(websocket, "Invalid or expired token.")
        await websocket.close(code=1008)
        return None

    user_id = str(payload.get("id") or payload.get("sub", ""))
    if not user_id:
        logger.error("User object missing ID")
        await send_error_message(websocket, "User ID missing from token.")
        await websocket.close(code=1008)
        return None

    logger.info("Authenticated STT WebSocket user")
    return user_id


def compose_final_text(final_tokens: list[dict[str, Any]]) -> str:
    return "".join(str(token.get("text", "")) for token in final_tokens)


async def handle_end_signal(
    *,
    state: TranscriptionSessionState,
    soniox_ws: Any,
    soniox_task: asyncio.Task[None],
) -> None:
    logger.info("Received END signal from client")
    if not state.transcription_active:
        return

    state.transcription_active = False
    await soniox_ws.send("")
    await soniox_task


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
                log_redacted_failure(
                    logger,
                    logging.ERROR,
                    "Failed to send audio chunk to Soniox",
                    error,
                    identifiers={"chunk_number": state.chunk_count},
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
                if text_data == "END":
                    await handle_end_signal(
                        state=state,
                        soniox_ws=soniox_ws,
                        soniox_task=soniox_task,
                    )
                else:
                    await send_error_message(
                        websocket,
                        "Only audio and the END control message are supported.",
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
