import pytest
import json
import uuid
from unittest.mock import MagicMock, patch, AsyncMock
from app.core.redis import RedisKeys
from app.core.events import UserTranscriptionReceived

# We need to import the module to patch it, or use string paths
from app.workers import llm_worker


@pytest.fixture
def mock_redis_worker():
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def get_redis():
        return fake

    with patch("app.workers.llm_worker.get_redis_client", side_effect=get_redis):
        yield fake


@pytest.fixture
def mock_gemini():
    service = MagicMock()
    # Mock chat response
    chat_resp = MagicMock()
    chat_resp.text = "I am a helpful AI."
    chat_resp.candidates = []
    service.generate_chat_response = AsyncMock(return_value=chat_resp)

    with patch("app.workers.llm_worker.get_gemini_service", return_value=service):
        yield service


@pytest.fixture
def mock_taskiq():
    with patch("app.workers.llm_worker.execute_tool_call") as mock:
        mock.kiq = AsyncMock()
        yield mock


@pytest.fixture
def mock_execute_tool():
    with patch("app.workers.llm_worker.execute_tool", new_callable=AsyncMock) as mock:
        mock.return_value = {"status": "success"}
        yield mock


@pytest.mark.asyncio
async def test_fast_path_command(mock_redis_worker, mock_taskiq, mock_execute_tool):
    # Simulate a "user.transcription" event that triggers a fast path (e.g. "pause")
    user_id = "test_user_fast"
    transcription = "pause"

    # We construct the message payload manually as it comes from Redis stream
    event = UserTranscriptionReceived(content=transcription)
    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": event.model_dump_json(),
    }

    # Call handle_message
    await llm_worker.handle_message(data)

    # Verify execute_tool was called (Fast path for pause)
    # The command parser should identify "pause" -> spotify.pause
    mock_execute_tool.assert_called_once()
    args = mock_execute_tool.call_args
    assert args[0][0] == user_id
    assert args[0][1] == "spotify.pause"

    # Verify we published a response to the user
    # Check Redis for published messages
    # We assume 'handle_message' publishes 'agent.response' via _cache_spotify_result or _tool_result_response
    # For 'pause' fast path, it stores result and says "Paused."

    # We can check history or published messages
    history_key = f"agent:history:{user_id}"
    history = await mock_redis_worker.lrange(history_key, 0, -1)
    assert len(history) > 0
    # Last message should be assistant saying "Paused."
    last_msg = json.loads(history[-1])
    assert last_msg["role"] == "assistant"
    assert "Paused" in last_msg["content"]


@pytest.mark.asyncio
async def test_llm_chat_response(mock_redis_worker, mock_gemini):
    user_id = "test_user_llm"
    transcription = "Hello, how are you?"

    event = UserTranscriptionReceived(content=transcription)
    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": event.model_dump_json(),
    }

    await llm_worker.handle_message(data)

    # Verify Gemini was called
    mock_gemini.generate_chat_response.assert_called_once()

    # Verify history updated
    history_key = f"agent:history:{user_id}"
    history = await mock_redis_worker.lrange(history_key, 0, -1)
    assert len(history) == 2  # User msg + Assistant msg

    user_msg = json.loads(history[0])
    assert user_msg["content"] == transcription

    ai_msg = json.loads(history[1])
    assert ai_msg["content"] == "I am a helpful AI."


@pytest.mark.asyncio
async def test_conversation_router_blocks_implicit_music_phrase_fast_path(
    mock_redis_worker, mock_gemini, mock_execute_tool
):
    user_id = "test_user_conversation_router"
    transcription = "I like to play songs when I code"

    event = UserTranscriptionReceived(content=transcription)
    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": event.model_dump_json(),
    }

    await llm_worker.handle_message(data)

    # Should be treated as conversation and go to LLM, not tool fast-path.
    mock_execute_tool.assert_not_called()
    mock_gemini.generate_chat_response.assert_called_once()


@pytest.mark.asyncio
async def test_llm_tool_call(mock_redis_worker, mock_gemini, mock_taskiq):
    user_id = "test_user_tool"
    transcription = "Check my calendar"

    # Configure Gemini to return a Function Call
    chat_resp = MagicMock()
    chat_resp.candidates = [MagicMock()]

    # Structure heavily depends on how `google.generativeai` models response
    # The worker code checks: candidate.content.parts[0].function_call
    part = MagicMock()
    function_call = MagicMock()
    function_call.name = "google.calendar.list"
    function_call.args = {"limit": 5}
    part.function_call = function_call

    chat_resp.candidates[0].content.parts = [part]
    mock_gemini.generate_chat_response.return_value = chat_resp

    event = UserTranscriptionReceived(content=transcription)
    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": event.model_dump_json(),
    }

    await llm_worker.handle_message(data)

    # Verify Taskiq was called to execute tool separate from worker
    mock_taskiq.kiq.assert_called_once()
    call_kwargs = mock_taskiq.kiq.call_args[1]
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["tool_name"] == "google.calendar.list"
    assert call_kwargs["tool_args"] == {"limit": 5}


@pytest.mark.asyncio
async def test_fast_path_add_to_queue(
    mock_redis_worker, mock_taskiq, mock_execute_tool
):
    user_id = "test_user_queue"
    transcription = "add bohemian rhapsody by queen to queue"

    event = UserTranscriptionReceived(content=transcription)
    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": event.model_dump_json(),
    }

    await llm_worker.handle_message(data)

    mock_execute_tool.assert_called_once()
    args = mock_execute_tool.call_args
    assert args[0][0] == user_id
    assert args[0][1] == "spotify.add_to_queue"
    assert args[0][2]["query"] == "bohemian rhapsody"
    assert args[0][2]["artist"] == "queen"


@pytest.mark.asyncio
async def test_fast_path_uses_n_best_alternative_when_primary_is_not_command(
    mock_redis_worker, mock_taskiq, mock_execute_tool
):
    user_id = "test_user_nbest_override"
    transcription = UserTranscriptionReceived(
        content="that's a great song",
        alternatives=["add bohemian rhapsody by queen to queue"],
    )

    data = {
        "type": "user.transcription",
        "user_id": user_id,
        "payload": transcription.model_dump_json(),
    }

    await llm_worker.handle_message(data)

    mock_execute_tool.assert_called_once()
    args = mock_execute_tool.call_args
    assert args[0][0] == user_id
    assert args[0][1] == "spotify.add_to_queue"
    assert args[0][2]["query"] == "bohemian rhapsody"
    assert args[0][2]["artist"] == "queen"
