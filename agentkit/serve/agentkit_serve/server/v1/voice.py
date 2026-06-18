"""Voice modality routes (STT WebSocket streaming)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

import websockets
from fastapi import APIRouter, WebSocket
from fastapi.websockets import WebSocketState

from agentkit.infra.realtime.redis import get_redis_client
from agentkit_serve.modalities.voice.stt import (
    TranscriptionSessionState,
    authenticate_ws,
    cancel_pending_publish,
    process_client_messages,
    safe_send_json,
    send_error_message,
    stream_agent_updates,
)
from agentkit_serve.modalities.voice.stt.soniox_service import soniox_service
from agentkit_serve.modalities.voice.stt.soniox_gateway import (
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
    agent_updates_task: Optional[asyncio.Task[None]] = None
    soniox_task: Optional[asyncio.Task[None]] = None
    state = TranscriptionSessionState(final_tokens=[])

    try:
        auth = await authenticate_ws(websocket)
        if auth is None:
            return
        user_id, session_id = auth

        logger.info("Connecting to Redis...")
        redis_conn = await get_redis_client()
        logger.info("Redis connected")

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

        agent_updates_task = asyncio.create_task(
            stream_agent_updates(websocket, redis_conn, user_id)
        )

        await safe_send_json(websocket, {"type": "ready"})
        logger.info("Sent ready signal to client")

        await process_client_messages(
            websocket=websocket,
            redis_conn=redis_conn,
            user_id=user_id,
            session_id=session_id,
            soniox_ws=soniox_ws,
            soniox_task=soniox_task,
            state=state,
        )
    except Exception as error:
        logger.error("WebSocket error: %s", error, exc_info=True)
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await send_error_message(websocket, "Internal server error.")
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
        if agent_updates_task:
            agent_updates_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await agent_updates_task
        if state.pending_publish_task:
            pending_publish_task = state.pending_publish_task
            cancel_pending_publish(state)
            with contextlib.suppress(asyncio.CancelledError):
                await pending_publish_task
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
        logger.info("STT stream closed")
