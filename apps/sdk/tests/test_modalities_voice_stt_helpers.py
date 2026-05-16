import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from fastapi.websockets import WebSocketState

from src.events.envelope import parse_event_envelope
from src.modalities.voice.stt import (
    TranscriptionSessionState,
    authenticate_ws,
    compose_final_text,
    extract_websocket_bearer_token,
    handle_command_message,
    normalize_command_text,
    publish_transcription,
    safe_send_json,
    send_error_message,
)


def test_normalize_command_text_collapses_whitespace():
    assert normalize_command_text("  Play   Jazz  ") == "play jazz"


def test_extract_websocket_bearer_token_from_header():
    websocket = MagicMock()
    websocket.headers = {"authorization": "Bearer secret"}
    websocket.query_params = {}
    assert extract_websocket_bearer_token(websocket) == "secret"


def test_extract_websocket_bearer_token_from_query_fallback():
    websocket = MagicMock()
    websocket.headers = {}
    websocket.query_params = {"token": "legacy"}
    assert extract_websocket_bearer_token(websocket) == "legacy"


def test_compose_final_text_joins_tokens():
    tokens = [{"text": "hel"}, {"text": "lo"}]
    assert compose_final_text(tokens) == "hello"


@pytest.mark.asyncio
async def test_publish_transcription_writes_stream_entry():
    redis = AsyncMock()
    await publish_transcription(redis, "user-1", "hello", session_id="sess-1")
    redis.xadd.assert_awaited_once()
    fields = redis.xadd.await_args.args[1]
    parsed = parse_event_envelope(fields)
    assert parsed.type == "user.transcription"
    assert parsed.user_id == "user-1"


@pytest.mark.asyncio
async def test_authenticate_ws_missing_token_closes_socket():
    websocket = AsyncMock()
    websocket.headers = {}
    websocket.query_params = {}
    result = await authenticate_ws(websocket)
    assert result is None
    websocket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_authenticate_ws_invalid_user_closes_socket():
    websocket = AsyncMock()
    websocket.headers = {"authorization": "Bearer bad"}
    with patch("src.modalities.voice.stt.supabase_auth_service") as auth:
        auth.get_user = AsyncMock(return_value=None)
        result = await authenticate_ws(websocket)
    assert result is None
    websocket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_handle_command_message_publishes_and_acks():
    redis = AsyncMock()
    websocket = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    state = TranscriptionSessionState(final_tokens=[])
    payload = json.dumps({"type": "command", "text": "play jazz", "mode": "auto"})
    handled = await handle_command_message(
        payload,
        state=state,
        websocket=websocket,
        redis_conn=redis,
        user_id="user-1",
        session_id="sess-1",
    )
    assert handled is True
    websocket.send_json.assert_awaited_once()
    redis.xadd.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_command_message_ignores_non_command_json():
    redis = AsyncMock()
    websocket = AsyncMock()
    state = TranscriptionSessionState(final_tokens=[])
    handled = await handle_command_message(
        '{"type":"ping"}',
        state=state,
        websocket=websocket,
        redis_conn=redis,
        user_id="user-1",
        session_id="sess-1",
    )
    assert handled is False
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_send_json_skips_when_disconnected():
    websocket = MagicMock()
    websocket.client_state = WebSocketState.DISCONNECTED
    await safe_send_json(websocket, {"type": "noop"})
    websocket.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_send_error_message_shape():
    websocket = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    await send_error_message(websocket, "nope")
    websocket.send_json.assert_awaited_with({"type": "error", "message": "nope"})
