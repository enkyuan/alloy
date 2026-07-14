from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.websockets import WebSocketState

from kaji_serve.modalities.voice.stt import (
    TranscriptionSessionState,
    authenticate_ws,
    compose_final_text,
    extract_websocket_access_token,
    process_client_messages,
    safe_send_json,
    send_error_message,
)


def test_extract_websocket_access_token_from_header():
    websocket = MagicMock()
    websocket.headers = {"authorization": "Bearer secret"}
    websocket.cookies = {}
    assert extract_websocket_access_token(websocket) == "secret"


def test_extract_websocket_access_token_from_cookie():
    websocket = MagicMock()
    websocket.headers = {"origin": "http://localhost:3000"}
    websocket.cookies = {"kaji_access_token": "cookie-secret"}
    assert extract_websocket_access_token(websocket) == "cookie-secret"


@pytest.mark.parametrize("origin", [None, "https://malicious.example"])
def test_extract_websocket_access_token_rejects_untrusted_cookie_origin(origin):
    websocket = MagicMock()
    websocket.headers = {"origin": origin} if origin else {}
    websocket.cookies = {"kaji_access_token": "cookie-secret"}
    assert extract_websocket_access_token(websocket) is None


def test_extract_websocket_access_token_rejects_query_token():
    websocket = MagicMock()
    websocket.headers = {}
    websocket.cookies = {}
    websocket.query_params = {"token": "must-not-be-read"}
    assert extract_websocket_access_token(websocket) is None


def test_compose_final_text_joins_tokens():
    tokens = [{"text": "hel"}, {"text": "lo"}]
    assert compose_final_text(tokens) == "hello"


@pytest.mark.asyncio
async def test_authenticate_ws_missing_token_closes_socket():
    websocket = AsyncMock()
    websocket.headers = {}
    websocket.cookies = {}
    result = await authenticate_ws(websocket)
    assert result is None
    websocket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_authenticate_ws_invalid_user_closes_socket():
    websocket = AsyncMock()
    websocket.headers = {"authorization": "Bearer bad"}
    with patch(
        "kaji_serve.modalities.voice.stt.handler.decode_bearer_token",
        side_effect=Exception("bad token"),
    ):
        result = await authenticate_ws(websocket)
    assert result is None
    websocket.close.assert_awaited_once_with(code=1008)


@pytest.mark.asyncio
async def test_authenticate_ws_returns_user_id():
    websocket = AsyncMock()
    websocket.headers = {"authorization": "Bearer good"}
    with patch(
        "kaji_serve.modalities.voice.stt.handler.decode_bearer_token",
        return_value={"sub": "user-1"},
    ):
        result = await authenticate_ws(websocket)
    assert result == "user-1"


@pytest.mark.asyncio
async def test_process_client_messages_rejects_non_stt_control_message():
    websocket = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.receive.side_effect = [
        {"text": '{"type":"command","text":"play jazz"}'},
        {"type": "websocket.disconnect"},
    ]
    state = TranscriptionSessionState(final_tokens=[])
    soniox_task = AsyncMock()

    await process_client_messages(
        websocket=websocket,
        soniox_ws=AsyncMock(),
        soniox_task=soniox_task,
        state=state,
    )

    websocket.send_json.assert_awaited_once_with(
        {
            "type": "error",
            "message": "Only audio and the END control message are supported.",
        }
    )


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
