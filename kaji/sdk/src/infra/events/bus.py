import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass

from kaji.infra.events.errors import EventBufferOverflowError
from kaji.infra.events.schemas import (
    KajiEvent,
    StoredKajiEvent,
    require_stored_event,
)

logger = logging.getLogger(__name__)


@dataclass(eq=False, slots=True)
class _LiveSubscriber:
    queue: asyncio.Queue[StoredKajiEvent | EventBufferOverflowError]
    last_sequence: int


class _InMemorySubscription:
    def __init__(
        self,
        bus: "InMemoryEventBus",
        session_id: str,
        subscriber: _LiveSubscriber,
    ) -> None:
        self._bus = bus
        self._session_id = session_id
        self._subscriber = subscriber
        self._closed = False

    def __aiter__(self) -> "_InMemorySubscription":
        return self

    async def __anext__(self) -> StoredKajiEvent:
        if self._closed:
            raise StopAsyncIteration
        item = await self._subscriber.queue.get()
        if isinstance(item, EventBufferOverflowError):
            self._closed = True
            raise item
        assert item.sequence is not None
        self._subscriber.last_sequence = item.sequence
        return item

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._bus._remove(self._session_id, self._subscriber)


class InMemoryEventBus:
    """Bounded live-only event bus for experimental split delivery.

    Durable backlog belongs to the event store. The stable in-process path uses
    :class:`InMemoryEventJournal`, which owns the backlog/live handshake.
    """

    def __init__(self, *, subscriber_queue_capacity: int = 1_024) -> None:
        if subscriber_queue_capacity < 1:
            raise ValueError("subscriber_queue_capacity must be positive")
        self.subscriber_queue_capacity = subscriber_queue_capacity
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[_LiveSubscriber]] = defaultdict(list)

    def _overflow(
        self,
        session_id: str,
        subscriber: _LiveSubscriber,
        latest_sequence: int,
    ) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is not None and subscriber in subscribers:
            subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(session_id, None)
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(
            EventBufferOverflowError(
                last_sequence=subscriber.last_sequence,
                latest_sequence=latest_sequence,
            )
        )

    async def publish(self, event: StoredKajiEvent) -> str:
        """Fan out a persisted event without retaining duplicate history."""
        stored = require_stored_event(event)
        assert stored.sequence is not None
        async with self._lock:
            for subscriber in list(self._subscribers.get(stored.session_id, ())):
                if subscriber.queue.full():
                    self._overflow(stored.session_id, subscriber, stored.sequence)
                elif stored.sequence > subscriber.last_sequence:
                    subscriber.queue.put_nowait(stored)
        logger.debug("Published event %s for %s", stored.type, stored.session_id)
        return str(stored.sequence)

    async def _remove(self, session_id: str, subscriber: _LiveSubscriber) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None and subscriber in subscribers:
                subscribers.remove(subscriber)
                if not subscribers:
                    self._subscribers.pop(session_id, None)

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        """Yield live events after a cursor; history is owned by the journal."""
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        subscriber = _LiveSubscriber(
            queue=asyncio.Queue(maxsize=self.subscriber_queue_capacity),
            last_sequence=after_sequence,
        )
        # Registration is synchronous, so a split journal can attach live
        # delivery and capture store backlog without an await-sized gap.
        self._subscribers[session_id].append(subscriber)
        return _InMemorySubscription(self, session_id, subscriber)


class EventBus:
    """Redis Stream-backed event bus for Kaji events."""

    def __init__(self, stream_key_prefix: str = "kaji:events"):
        self.stream_key_prefix = stream_key_prefix

    def _get_stream_key(self, session_id: str) -> str:
        return f"{self.stream_key_prefix}:{session_id}"

    async def publish(self, event: StoredKajiEvent) -> str:
        """Publish an event to the Redis stream."""
        from kaji.infra.realtime.redis import get_redis_client

        redis = await get_redis_client()
        stream_key = self._get_stream_key(event.session_id)

        # Serialize the event to JSON
        stored = require_stored_event(event)
        event_json = stored.model_dump_json()

        # We store it under a single field 'payload' in the stream
        message_id = await redis.xadd(stream_key, {"payload": event_json})

        logger.debug("Published event %s to %s", stored.type, stream_key)
        return message_id

    async def subscribe(
        self,
        session_id: str,
        last_id: str = "0",
        block_ms: int = 2000,
        *,
        after_sequence: int = 0,
    ) -> AsyncGenerator[StoredKajiEvent, None]:
        """Subscribe to events for a specific session."""
        from kaji.infra.realtime.redis import get_redis_client

        redis = await get_redis_client()
        stream_key = self._get_stream_key(session_id)
        current_id = last_id

        from pydantic import TypeAdapter

        adapter = TypeAdapter(KajiEvent)

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
                        event = require_stored_event(
                            adapter.validate_json(payload_json)
                        )
                        assert event.sequence is not None
                        if event.sequence > after_sequence:
                            yield event
                    except Exception as e:
                        logger.error("Failed to deserialize event from stream: %s", e)
