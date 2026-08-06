"""Voice modality routes (STT WebSocket streaming)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketState

from kaji.core.safe_logging import log_redacted_failure
from kaji_serve.modalities.voice.stt import (
    TranscriptionSessionState,
    authenticate_ws,
    process_client_messages,
    safe_send_json,
    send_error_message,
)
from kaji_serve.modalities.voice.stt.soniox_service import soniox_service
from kaji_serve.modalities.voice.stt.soniox_gateway import (
    connect_soniox,
    listen_to_soniox,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["speech-to-text-streaming"])


@router.websocket("/stream")
async def stream_transcribe(websocket: WebSocket):
    """Stream PCM audio to Soniox and relay partial/final transcriptions."""
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    soniox_ws = None
    soniox_task: Optional[asyncio.Task[None]] = None
    state = TranscriptionSessionState(final_tokens=[])

    try:
        user_id = await authenticate_ws(websocket)
        if user_id is None:
            return

        soniox_ws = await connect_soniox(
            websocket,
            user_id,
            connect_fn=websockets.connect,
            soniox_service=soniox_service,
        )
        if soniox_ws is None:
            return

        soniox_task = asyncio.create_task(listen_to_soniox(soniox_ws, websocket, state))
        await asyncio.sleep(0.1)

        await safe_send_json(websocket, {"type": "ready"})
        logger.info("Sent ready signal to client")

        await process_client_messages(
            websocket=websocket,
            soniox_ws=soniox_ws,
            soniox_task=soniox_task,
            state=state,
        )
    except Exception as error:
        log_redacted_failure(
            logger,
            logging.ERROR,
            "STT WebSocket failed",
            error,
        )
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await send_error_message(websocket, "Internal server error.")
                await websocket.close(code=1011, reason="Internal server error")
            except Exception as close_error:
                log_redacted_failure(
                    logger,
                    logging.DEBUG,
                    "Failed to send or close STT WebSocket after error",
                    close_error,
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
                log_redacted_failure(
                    logger,
                    logging.DEBUG,
                    "Failed to close Soniox WebSocket",
                    close_error,
                )
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")
