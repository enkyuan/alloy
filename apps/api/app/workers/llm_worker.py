"""
LLM Worker - The "Reasoning Node" of the agent pipeline.

This worker acts as the central process that consumes user transcriptions:
1. Consumes 'user.transcription' events from Redis Stream `stream:voice_input`.
2. Reconstructs conversation context (fetching recent messages from DB).
3. Calls LLM (Gemini) with tool definitions.
4. If Tool Call: Dispatches to Taskiq `execute_tool_call` task.
5. If Text: Pushes 'agent.response' events to Redis.
"""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from typing import Any

import app.services.integrations.tools  # ensure tool registration
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.events import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.core.redis import RedisKeys, get_redis_client
from app.services.integrations import list_tool_specs
from app.services.integrations.dispatcher import execute_tool
from app.services.pipeline.cmd_parser import CommandIntent, command_parser
from app.services.pipeline.gemini import get_gemini_service
from app.services.pipeline.tasks import execute_tool_call

logger = logging.getLogger(__name__)

HISTORY_LIMIT = settings.AGENT_HISTORY_LIMIT
CACHE_TTL_SECONDS = settings.AGENT_CACHE_TTL_SECONDS
SPOTIFY_CACHE_TTL_SECONDS = 60 * 60

SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. "
    "Use tools to control integrations when needed. "
    "If a tool result is provided, respond succinctly to the user."
)


def _is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    quota_markers = [
        "resource_exhausted",
        "quota",
        "rate limit",
        "rate_limit",
        "429",
    ]
    return any(marker in message for marker in quota_markers)


def _history_key(user_id: str) -> str:
    return f"agent:history:{user_id}"


def _response_cache_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"agent:cache:{digest}"


def _cache_hit_key() -> str:
    return "agent:cache:hit"


def _cache_miss_key() -> str:
    return "agent:cache:miss"


def _tools_fingerprint() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in list_tool_specs()
    ]


def _normalize_spotify_query(query: str, artist: str | None = None) -> str:
    text = f"{query} {artist or ''}".lower()
    text = re.sub(r"\b(on|in|with)\s+spotify\b", "", text)
    text = re.sub(r"\bspotify\b", "", text)
    text = re.sub(
        r"\b(play|please|could you|can you|would you|hey|hi|haven)\b", "", text
    )
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _spotify_cache_key(query: str, artist: str | None = None) -> str:
    normalized = _normalize_spotify_query(query, artist)
    return f"spotify:cache:track:{normalized}"


def _intent_to_tool_call(intent: CommandIntent) -> tuple[str, dict] | None:
    params = intent.parameters or {}

    if intent.intent == "play_track":
        track = params.get("track")
        if not track:
            return None
        artist = params.get("artist")
        query = track
        tool_args = {"query": query}
        if artist:
            tool_args["artist"] = artist
            tool_args["query"] = f"{track} by {artist}"
        return "spotify.play", tool_args

    if intent.intent == "play_album":
        album = params.get("album")
        if not album:
            return None
        tool_args = {"album": album}
        if params.get("artist"):
            tool_args["artist"] = params["artist"]
        return "spotify.play_album", tool_args

    if intent.intent == "play_playlist":
        playlist = params.get("playlist")
        if not playlist:
            return None
        return "spotify.play_playlist", {"playlist": playlist}

    if intent.intent == "pause":
        return "spotify.pause", {}

    if intent.intent == "resume":
        return "spotify.resume", {}

    if intent.intent == "next":
        return "spotify.next", {}

    if intent.intent == "previous":
        return "spotify.previous", {}

    if intent.intent == "set_volume":
        level = params.get("level")
        if level is None:
            return None
        return "spotify.set_volume", {"level": level}

    if intent.intent == "list_devices":
        return "spotify.list_devices", {}

    if intent.intent == "switch_device":
        device = params.get("device")
        if not device:
            return None
        return "spotify.switch_device", {"device_name": device}

    return None


async def _append_history(redis: Any, user_id: str, role: str, content: str) -> None:
    entry = {"role": role, "content": content}
    await redis.rpush(_history_key(user_id), json.dumps(entry))
    if HISTORY_LIMIT and HISTORY_LIMIT > 0:
        await redis.ltrim(_history_key(user_id), -HISTORY_LIMIT, -1)


async def _get_history(redis: Any, user_id: str) -> list[dict[str, str]]:
    raw_items = await redis.lrange(_history_key(user_id), 0, -1)
    messages: list[dict[str, str]] = []
    for item in raw_items:
        try:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            data = json.loads(item)
            if isinstance(data, dict) and "role" in data and "content" in data:
                messages.append(
                    {"role": str(data["role"]), "content": str(data["content"])}
                )
        except Exception:
            continue
    return messages


async def _dispatch_tool_call(
    redis: Any, user_id: str, tool_name: str, tool_args: dict
) -> None:
    tool_call_id = str(uuid.uuid4())
    logger.info(
        "Dispatching tool call",
        extra={
            "user_id": user_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        },
    )
    await execute_tool_call.kiq(
        user_id=user_id,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_id=tool_call_id,
    )

    tc_event = ToolCall(
        tool_name=tool_name, tool_args=tool_args, tool_call_id=tool_call_id
    )
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "tool.call",
                "user_id": user_id,
                "payload": tc_event.model_dump_json(),
            }
        ),
    )


async def _cache_spotify_result(redis: Any, tool_result: ToolResult) -> None:
    if tool_result.tool_name != "spotify.play":
        return
    if not isinstance(tool_result.result, dict):
        return
    data = tool_result.result.get("data")
    if not isinstance(data, dict):
        return
    uri = data.get("uri")
    track_name = data.get("track_name")
    artist = data.get("artist")
    if not uri or not track_name:
        return

    query = tool_result.tool_args.get("query") if tool_result.tool_args else None
    if not query:
        query = track_name

    cache_key = _spotify_cache_key(str(query), str(artist) if artist else None)
    payload = {
        "uri": uri,
        "track_name": track_name,
        "artist": artist,
    }
    await redis.setex(cache_key, SPOTIFY_CACHE_TTL_SECONDS, json.dumps(payload))


async def _try_cached_spotify_play(redis: Any, user_id: str, tool_args: dict) -> bool:
    query = str(tool_args.get("query", "")).strip()
    if not query:
        return False
    artist = tool_args.get("artist")
    cache_key = _spotify_cache_key(query, str(artist) if artist else None)
    cached = await redis.get(cache_key)
    if not cached:
        return False
    try:
        payload = json.loads(cached)
    except Exception:
        return False
    uri = payload.get("uri")
    if not uri:
        return False

    tool_call_id = str(uuid.uuid4())
    tc_event = ToolCall(
        tool_name="spotify.play",
        tool_args={"uri": uri},
        tool_call_id=tool_call_id,
    )
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "tool.call",
                "user_id": user_id,
                "payload": tc_event.model_dump_json(),
            }
        ),
    )

    track_name = payload.get("track_name")
    artist_name = payload.get("artist")
    if track_name and artist_name:
        response_text = f"Playing {track_name} by {artist_name}."
    elif track_name:
        response_text = f"Playing {track_name}."
    else:
        response_text = "Playing on Spotify."

    await _append_history(redis, user_id, "assistant", response_text)
    response_event = AgentResponse(content=response_text)
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "agent.response",
                "user_id": user_id,
                "payload": response_event.model_dump_json(),
            }
        ),
    )
    return True


async def _execute_tool_fast(
    redis: Any, user_id: str, tool_name: str, tool_args: dict
) -> None:
    tool_call_id = str(uuid.uuid4())
    logger.info(
        "Fast-path tool execution",
        extra={
            "user_id": user_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        },
    )

    tc_event = ToolCall(
        tool_name=tool_name, tool_args=tool_args, tool_call_id=tool_call_id
    )
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "tool.call",
                "user_id": user_id,
                "payload": tc_event.model_dump_json(),
            }
        ),
    )

    result_data = None
    error_msg = None
    db = None
    try:
        db = SessionLocal()
        result_data = await execute_tool(user_id, tool_name, tool_args, db)
    except Exception as e:
        logger.error(f"Fast-path tool failed: {e}", exc_info=True)
        error_msg = str(e)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    tool_result = ToolResult(
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_data,
        error=error_msg,
        tool_call_id=tool_call_id,
        user_id=user_id,
        metadata={"fast_path": True},
    )

    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "tool.result",
                "user_id": user_id,
                "payload": tool_result.model_dump_json(),
            }
        ),
    )

    await _cache_spotify_result(redis, tool_result)

    response_text = _tool_result_response(tool_result)
    if response_text:
        await _append_history(redis, user_id, "assistant", response_text)
        response_event = AgentResponse(content=response_text)
        await redis.publish(
            RedisKeys.CHANNEL_USER_UPDATES,
            json.dumps(
                {
                    "type": "agent.response",
                    "user_id": user_id,
                    "payload": response_event.model_dump_json(),
                }
            ),
        )


async def _dispatch_tool_calls(redis: Any, user_id: str, function_calls) -> None:
    for fc in function_calls:
        logger.info(f"LLM requested tool: {fc.name}")

        tool_call_id = str(uuid.uuid4())
        tool_args = {}
        if fc.args:
            for key, value in fc.args.items():
                tool_args[key] = value

        await execute_tool_call.kiq(
            user_id=user_id,
            tool_name=fc.name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )

        tc_event = ToolCall(
            tool_name=fc.name, tool_args=tool_args, tool_call_id=tool_call_id
        )
        await redis.publish(
            RedisKeys.CHANNEL_USER_UPDATES,
            json.dumps(
                {
                    "type": "tool.call",
                    "user_id": user_id,
                    "payload": tc_event.model_dump_json(),
                }
            ),
        )


async def _handle_llm_response(redis: Any, user_id: str, response) -> None:
    function_calls = []
    if hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        if (
            hasattr(candidate, "content")
            and candidate.content
            and hasattr(candidate.content, "parts")
            and candidate.content.parts
        ):
            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)

    if function_calls:
        logger.info(
            "LLM returned tool calls",
            extra={"user_id": user_id, "count": len(function_calls)},
        )
        await _dispatch_tool_calls(redis, user_id, function_calls)
        return

    response_text = response.text or ""
    if not response_text:
        logger.warning("Gemini returned an empty response")
        # Don't send "Sorry" here if it was just a transient overload or empty safety block
        # just logging warning is often enough, or we can send a fallback.
        # But if we crashed before, we definitely sent nothing.
        # Let's send a fallback only if we really got nothing.
        if not function_calls:
            response_text = "Sorry, I couldn't generate a response right now."

    await _append_history(redis, user_id, "assistant", response_text)
    logger.debug("Publishing agent response", extra={"user_id": user_id})
    response_event = AgentResponse(content=response_text)
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "agent.response",
                "user_id": user_id,
                "payload": response_event.model_dump_json(),
            }
        ),
    )
    logger.info(f"Published agent response: {response_text[:30]}...")


def _build_tools_payload():
    declarations = []
    for spec in list_tool_specs():
        declarations.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )
    return [{"function_declarations": declarations}] if declarations else []


# Define available tools (schema for Gemini)
TOOLS = _build_tools_payload()


def _tool_result_response(tool_result: ToolResult) -> str:
    if tool_result.error:
        return f"Sorry, I couldn't complete that. {tool_result.error}"

    result = tool_result.result
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return "Done."

    status = result.get("status")
    data = result.get("data") if isinstance(result.get("data"), dict) else {}

    if tool_result.tool_name.startswith("spotify."):
        if tool_result.tool_name in {
            "spotify.play",
            "spotify.play_album",
            "spotify.play_playlist",
        }:
            track_name = (
                data.get("track_name")
                or result.get("query")
                or result.get("album")
                or result.get("playlist")
            )
            artist = data.get("artist")
            if track_name and artist:
                return f"Playing {track_name} by {artist}."
            if track_name:
                return f"Playing {track_name}."
            return "Playing on Spotify."

        if tool_result.tool_name == "spotify.pause":
            return "Paused."
        if tool_result.tool_name == "spotify.resume":
            return "Resuming playback."
        if tool_result.tool_name == "spotify.next":
            return "Skipping to the next track."
        if tool_result.tool_name == "spotify.previous":
            return "Going back to the previous track."
        if tool_result.tool_name == "spotify.set_volume":
            level = result.get("volume") or data.get("volume") or data.get("level")
            if isinstance(level, int):
                return f"Volume set to {level}%."
            return "Volume updated."
        if tool_result.tool_name == "spotify.list_devices":
            devices = data.get("devices")
            if isinstance(devices, list):
                return f"Found {len(devices)} devices."
            return "Here are your available devices."

    if isinstance(status, str) and status:
        return status

    return "Done."


async def process_voice_input_stream():
    """Main loop for consuming voice input events."""
    redis = await get_redis_client()

    # Create consumer group if not exists
    try:
        await redis.xgroup_create(
            RedisKeys.STREAM_VOICE_INPUT,
            RedisKeys.GROUP_LLM_WORKER,
            id="0",
            mkstream=True,
        )
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            logger.error(f"Error creating consumer group: {e}")

    logger.info(f"LLM Worker started listening on {RedisKeys.STREAM_VOICE_INPUT}")

    while True:
        try:
            # Read from stream using consumer group
            streams = await redis.xreadgroup(
                groupname=RedisKeys.GROUP_LLM_WORKER,
                consumername="llm_worker_1",
                streams={RedisKeys.STREAM_VOICE_INPUT: ">"},
                count=1,
                block=2000,
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for message_id, data in messages:
                    try:
                        await handle_message(data)
                        # Acknowledge message
                        await redis.xack(
                            RedisKeys.STREAM_VOICE_INPUT,
                            RedisKeys.GROUP_LLM_WORKER,
                            message_id,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error processing message {message_id}: {e}", exc_info=True
                        )

        except Exception as e:
            logger.error(f"Error in LLM worker loop: {e}")
            await asyncio.sleep(1)


async def handle_message(data: dict):
    """Business logic for handling a single voice event."""
    event_type = data.get("type")

    if event_type != "user.transcription":
        return

    payload_json = data.get("payload")
    user_id = data.get("user_id")

    if not payload_json or not user_id:
        logger.warning("Received invalid message payload or missing user_id")
        return

    # Deserialize event
    transcription = UserTranscriptionReceived.model_validate_json(payload_json)

    logger.info(f"Processing transcription for user {user_id}: {transcription.content}")

    # Call LLM (Gemini) with Tools
    try:
        redis = await get_redis_client()
        await _append_history(redis, user_id, "user", transcription.content)

        intent = command_parser.parse_command(transcription.content)
        if intent and not intent.requires_clarification:
            tool_call = _intent_to_tool_call(intent)
            if tool_call:
                tool_name, tool_args = tool_call
                if tool_name == "spotify.play":
                    used_cache = await _try_cached_spotify_play(
                        redis, str(user_id), tool_args
                    )
                    if used_cache:
                        return
                await _execute_tool_fast(redis, str(user_id), tool_name, tool_args)
                return

        gemini = get_gemini_service()
        history = await _get_history(redis, user_id)
        cache_payload = {
            "messages": history,
            "system": SYSTEM_INSTRUCTION,
            "tools": _tools_fingerprint(),
        }
        cached_response = await redis.get(_response_cache_key(cache_payload))
        if cached_response:
            await redis.incr(_cache_hit_key())
            logger.debug("Cache hit", extra={"user_id": user_id})
            if isinstance(cached_response, bytes):
                cached_response = cached_response.decode("utf-8")
            response_event = AgentResponse(content=str(cached_response))
            await redis.publish(
                RedisKeys.CHANNEL_USER_UPDATES,
                json.dumps(
                    {
                        "type": "agent.response",
                        "user_id": user_id,
                        "payload": response_event.model_dump_json(),
                    }
                ),
            )
            await _append_history(redis, user_id, "assistant", str(cached_response))
            return
        await redis.incr(_cache_miss_key())
        logger.debug("Cache miss", extra={"user_id": user_id})
        response = await gemini.generate_chat_response(
            messages=history, system_instruction=SYSTEM_INSTRUCTION, tools=TOOLS
        )
        await _handle_llm_response(redis, user_id, response)
        try:
            if response.text:
                await redis.setex(
                    _response_cache_key(cache_payload),
                    CACHE_TTL_SECONDS,
                    response.text,
                )
        except ValueError:
            # response.text raises ValueError if content is purely function calls
            pass

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}", exc_info=True)
        if user_id:
            redis = await get_redis_client()
            if _is_quota_error(e):
                error_event = AgentError(
                    error="Gemini quota exhausted.",
                    code="gemini_quota",
                )
                await redis.publish(
                    RedisKeys.CHANNEL_USER_UPDATES,
                    json.dumps(
                        {
                            "type": "agent.error",
                            "user_id": user_id,
                            "payload": error_event.model_dump_json(),
                        }
                    ),
                )
            else:
                response_event = AgentResponse(
                    content="Sorry, I ran into an error while generating a response."
                )
                await redis.publish(
                    RedisKeys.CHANNEL_USER_UPDATES,
                    json.dumps(
                        {
                            "type": "agent.response",
                            "user_id": user_id,
                            "payload": response_event.model_dump_json(),
                        }
                    ),
                )


async def process_tool_results():
    """Listen for tool results and continue the agent loop."""
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(RedisKeys.CHANNEL_USER_UPDATES)
    logger.info("LLM Worker listening for tool results")
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0)
                continue

            raw = message.get("data")
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "tool.result":
                continue

            payload = event.get("payload")
            user_id = event.get("user_id")
            if not payload or not user_id:
                continue

            try:
                tool_result = ToolResult.model_validate_json(payload)
            except Exception:
                continue

            user_id = str(user_id)
            if tool_result.metadata and tool_result.metadata.get("fast_path"):
                continue

            await _cache_spotify_result(redis, tool_result)

            response_text = _tool_result_response(tool_result)
            if not response_text:
                continue

            await _append_history(redis, user_id, "assistant", response_text)
            response_event = AgentResponse(content=response_text)
            await redis.publish(
                RedisKeys.CHANNEL_USER_UPDATES,
                json.dumps(
                    {
                        "type": "agent.response",
                        "user_id": user_id,
                        "payload": response_event.model_dump_json(),
                    }
                ),
            )
    finally:
        await pubsub.unsubscribe(RedisKeys.CHANNEL_USER_UPDATES)
        await pubsub.close()


if __name__ == "__main__":
    from app.core.config import settings

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    async def _run():
        await asyncio.gather(
            process_voice_input_stream(),
            process_tool_results(),
        )

    asyncio.run(_run())
