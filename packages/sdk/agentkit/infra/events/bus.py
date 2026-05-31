import asyncio
import logging
from typing import AsyncGenerator

from agentkit.core.redis import get_redis_client
from agentkit.infra.events.schemas import AgentKitEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Redis Stream-backed event bus for AgentKit events."""

    def __init__(self, stream_key_prefix: str = "agentkit:events"):
        self.stream_key_prefix = stream_key_prefix

    def _get_stream_key(self, session_id: str) -> str:
        return f"{self.stream_key_prefix}:{session_id}"

    async def publish(self, event: AgentKitEvent) -> str:
        """Publish an event to the Redis stream."""
        redis = await get_redis_client()
        stream_key = self._get_stream_key(event.session_id)

        # Serialize the event to JSON
        event_json = event.model_dump_json()

        # We store it under a single field 'payload' in the stream
        message_id = await redis.xadd(stream_key, {"payload": event_json})

        logger.debug("Published event %s to %s", event.type, stream_key)
        return message_id

    async def subscribe(
        self, session_id: str, last_id: str = "0", block_ms: int = 2000
    ) -> AsyncGenerator[AgentKitEvent, None]:
        """Subscribe to events for a specific session."""
        redis = await get_redis_client()
        stream_key = self._get_stream_key(session_id)
        current_id = last_id

        from pydantic import TypeAdapter

        adapter = TypeAdapter(AgentKitEvent)

        while True:
            # xread returns: [[b'stream_name', [(b'message_id', {b'payload': b'json_str'})]]]
            streams = await redis.xread(
                {stream_key: current_id}, count=10, block=block_ms
            )

            if not streams:
                # Timed out, yield control back
                await asyncio.sleep(0)
                continue

            for _, messages in streams:
                for message_id, data in messages:
                    current_id = (
                        message_id.decode()
                        if isinstance(message_id, bytes)
                        else message_id
                    )

                    payload_raw = data.get(b"payload") or data.get("payload")
                    if not payload_raw:
                        continue

                    payload_json = (
                        payload_raw.decode()
                        if isinstance(payload_raw, bytes)
                        else payload_raw
                    )

                    try:
                        event = adapter.validate_json(payload_json)
                        yield event
                    except Exception as e:
                        logger.error("Failed to deserialize event from stream: %s", e)
