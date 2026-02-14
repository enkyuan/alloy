"""Soniox transport helpers for STT websocket routing."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import websockets
from fastapi import WebSocket

from .shared import (
    TranscriptionSessionState,
    compose_final_text,
    safe_send_json,
    send_error_message,
)

logger = logging.getLogger(__name__)

WebSocketConnector = Callable[[str], Awaitable[Any]]


async def connect_soniox(
    websocket: WebSocket,
    user_id: str,
    *,
    connect_fn: WebSocketConnector,
    soniox_service: Any,
) -> Any | None:
    """Connect and configure Soniox websocket."""
    try:
        logger.info("Connecting to Soniox WebSocket for user %s...", user_id)
        soniox_ws = await connect_fn(soniox_service.WEBSOCKET_URL)
        logger.info("Connected to Soniox WebSocket for user %s", user_id)
    except Exception as error:
        logger.error(
            "Failed to connect to Soniox for user %s: %s",
            user_id,
            error,
            exc_info=True,
        )
        await send_error_message(websocket, "Failed to connect to transcription service.")
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


async def listen_to_soniox(
    soniox_ws: Any,
    websocket: WebSocket,
    state: TranscriptionSessionState,
) -> None:
    """Listen for Soniox responses and forward to the websocket client."""
    try:
        async for message in soniox_ws:
            response = json.loads(message)

            if response.get("error_code"):
                logger.error(
                    "Soniox error code=%s message=%s",
                    response.get("error_code"),
                    response.get("error_message"),
                )
                await send_error_message(websocket, "Transcription service error.")
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

                final_text = compose_final_text(state.final_tokens)
                non_final_text = "".join(
                    str(token.get("text", "")) for token in non_final_tokens
                )
                full_text = final_text + non_final_text

                if non_final_tokens:
                    await safe_send_json(
                        websocket,
                        {"type": "partial", "text": full_text, "is_final": False},
                    )
                    logger.info("Partial: %s", full_text)

                if new_final_tokens:
                    await safe_send_json(
                        websocket,
                        {"type": "final", "text": final_text, "is_final": True},
                    )
                    logger.info("Final tokens: %s", final_text)

            if response.get("finished"):
                complete_text = compose_final_text(state.final_tokens)
                await safe_send_json(websocket, {"type": "complete", "text": complete_text})
                logger.info("Session finished. Complete text: %s", complete_text)
                break
    except websockets.exceptions.ConnectionClosed:
        logger.info("Soniox WebSocket closed")
    except Exception as error:
        logger.error("Error in Soniox listener: %s", error, exc_info=True)
        await send_error_message(websocket, "Transcription error.")
