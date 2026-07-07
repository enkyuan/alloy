import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from kaji_serve.modalities.voice.stt.soniox_service import (
    SonioxConfigError,
    SonioxService,
)


@pytest.fixture
def mock_soniox_service():
    with patch("kaji_serve.server.v1.voice.soniox_service") as mock:
        mock.WEBSOCKET_URL = "ws://mock-soniox/ws"
        mock.get_config.return_value = {"mock": "config"}
        yield mock


@pytest.fixture
def mock_websockets_connect():
    with patch("kaji_serve.server.v1.voice.websockets.connect") as mock_connect:
        yield mock_connect


# Mock Soniox WebSocket connection
class MockSonioxWebSocket:
    def __init__(self):
        self.sent_messages = []
        self.closed = False
        self.responses = []

    async def send(self, message):
        self.sent_messages.append(message)

    async def recv(self):
        # Not used because we iterate over the object
        pass

    async def close(self):
        self.closed = True

    def add_response(self, response_dict):
        self.responses.append(json.dumps(response_dict))

    async def __aiter__(self):
        for resp in self.responses:
            yield resp


@pytest.fixture
def mock_soniox_ws(mock_websockets_connect):
    mock_ws = MockSonioxWebSocket()

    # websockets.connect is awaited, so we need to mock it as an async function
    async def async_connect(*args, **kwargs):
        return mock_ws

    mock_websockets_connect.side_effect = async_connect
    return mock_ws


def test_modalities_voice_websocket_flow(
    test_client: TestClient, mock_supabase_auth, mock_soniox_service, mock_soniox_ws
):
    _ = mock_supabase_auth

    # Setup Soniox responses
    mock_soniox_ws.add_response(
        {
            "tokens": [
                {"text": "Hello ", "is_final": False},
            ]
        }
    )
    mock_soniox_ws.add_response(
        {
            "tokens": [
                {"text": "Hello ", "is_final": True},
                {"text": "world", "is_final": False},
            ]
        }
    )
    mock_soniox_ws.add_response(
        {
            "tokens": [
                {"text": "world", "is_final": True},
            ],
            "finished": True,
        }
    )

    with patch(
        "kaji_serve.modalities.voice.stt.handler.decode_bearer_token",
        return_value={"id": "test_user_stt", "sub": "test_user_stt"},
    ):
        with test_client.websocket_connect(
            "/api/v1/stt/stream", headers={"Authorization": "Bearer valid_token"}
        ) as websocket:
            # Send bytes immediately to ensure we trigger ACK logic eventually
            websocket.send_bytes(b"\x00\x01\x02")

            received_types = set()
            received_messages = []
            import time

            start_time = time.time()

            # We loop until we get everything we expect or timeout (2s)
            # Expected: ready, ack, partial/final, complete
            # Note: "complete" comes from Soniox task "finished=True" in our mock
            while time.time() - start_time < 2.0:
                try:
                    # receive_json is blocking, but TestClient usually doesn't block forever if app finishes
                    # However, we rely on the fact that we sent bytes so ACK should come
                    msg = websocket.receive_json()
                    received_types.add(msg["type"])
                    received_messages.append(msg)

                    if {"ready", "ack", "complete"}.issubset(received_types):
                        break
                except Exception:
                    break

            assert "ready" in received_types
            assert "ack" in received_types
            assert "complete" in received_types
            # We should also see at least one partial or final
            assert "partial" in received_types or "final" in received_types

            # Verify text content
            complete_msg = next(m for m in received_messages if m["type"] == "complete")
            assert "Hello world" in complete_msg["text"]


def test_modalities_voice_auth_failure(test_client: TestClient, mock_supabase_auth):
    _ = mock_supabase_auth

    with pytest.raises(Exception):
        with patch(
            "kaji_serve.modalities.voice.stt.handler.decode_bearer_token",
            side_effect=Exception("bad token"),
        ):
            with test_client.websocket_connect(
                "/api/v1/stt/stream", headers={"Authorization": "Bearer invalid_token"}
            ) as websocket:
                err = websocket.receive_json()
                assert err["type"] == "error"


def test_soniox_service_missing_api_key_raises_typed_error():
    service = SonioxService.__new__(SonioxService)
    service.api_key = None

    with pytest.raises(SonioxConfigError):
        service.get_config()
