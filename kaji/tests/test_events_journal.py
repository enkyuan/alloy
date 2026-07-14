import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.errors import (
    EventBufferOverflowError,
    EventDeliveryError,
    EventSchemaIncompatibleError,
    EventStoreCapacityError,
)
from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.infra.events.schemas import NewKajiEvent, StoredKajiEvent, UserMessage
from kaji.infra.events.store import AppendResult, InMemoryEventStore


async def _close(stream: object) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


class _FailingAppendStore(InMemoryEventStore):
    async def append(self, event):  # type: ignore[no-untyped-def]
        raise RuntimeError("append unavailable")


class _FailOnceBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[StoredKajiEvent] = []
        self.fail = True

    async def publish(self, event: StoredKajiEvent) -> str:
        self.calls.append(event)
        if self.fail:
            self.fail = False
            raise RuntimeError("publish unavailable")
        return await super().publish(event)


class _BlockingReadStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.backlog_captured = asyncio.Event()
        self.release_backlog = asyncio.Event()

    async def get_events(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        events = await super().get_events(*args, **kwargs)
        self.backlog_captured.set()
        await self.release_backlog.wait()
        return events


class _FailingReadStore(InMemoryEventStore):
    async def get_events(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("read unavailable")


class _RawBacklogStore(InMemoryEventStore):
    def __init__(self, row: dict[str, Any]) -> None:
        super().__init__()
        self.row = row

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        _ = session_id, after_sequence, limit
        return [cast(StoredKajiEvent, self.row)]

    async def last_sequence(self, session_id: str) -> int:
        _ = session_id
        return cast(int, self.row["sequence"])


class _RawAppendStore(InMemoryEventStore):
    def __init__(self, row: dict[str, Any]) -> None:
        super().__init__()
        self.row = row

    async def append(self, event: object) -> AppendResult:
        _ = event
        return AppendResult(event=cast(StoredKajiEvent, self.row), inserted=True)


class _AlwaysFailBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[StoredKajiEvent] = []

    async def publish(self, event: StoredKajiEvent) -> str:
        self.calls.append(event)
        raise RuntimeError("publish unavailable")


class _LazyCursorBackedBus:
    def __init__(self) -> None:
        self.events: list[StoredKajiEvent] = []
        self.started = False
        self.closed = False

    async def publish(self, event: StoredKajiEvent) -> str:
        self.events.append(event)
        return str(event.sequence)

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        async def _iterate() -> AsyncIterator[StoredKajiEvent]:
            self.started = True
            try:
                for event in self.events:
                    if (
                        event.session_id == session_id
                        and event.sequence > after_sequence
                    ):
                        yield event
                await asyncio.Future()
            finally:
                self.closed = True

        return _iterate()


class _TrackingLiveStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> "_TrackingLiveStream":
        return self

    async def __anext__(self) -> StoredKajiEvent:
        await asyncio.Future()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _TrackingBus:
    def __init__(self) -> None:
        self.subscription: _TrackingLiveStream | None = None
        self.published: list[StoredKajiEvent] = []

    async def publish(self, event: StoredKajiEvent) -> str:
        self.published.append(event)
        return str(event.sequence)

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        _ = session_id, after_sequence
        self.subscription = _TrackingLiveStream()
        return self.subscription


class _RawLiveStream(_TrackingLiveStream):
    def __init__(self, row: dict[str, Any]) -> None:
        super().__init__()
        self._row = row
        self._delivered = False

    async def __anext__(self) -> StoredKajiEvent:
        if self._delivered:
            raise StopAsyncIteration
        self._delivered = True
        return cast(StoredKajiEvent, self._row)


class _RawLiveBus(_TrackingBus):
    def __init__(self, row: dict[str, Any]) -> None:
        super().__init__()
        self._row = row

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        _ = session_id, after_sequence
        self.subscription = _RawLiveStream(self._row)
        return self.subscription


class _FailingLiveStream(_TrackingLiveStream):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    async def __anext__(self) -> StoredKajiEvent:
        raise self._error

    async def aclose(self) -> None:
        self.closed = True
        raise RuntimeError("close unavailable")


class _FailingLiveBus(_TrackingBus):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        _ = session_id, after_sequence
        self.subscription = _FailingLiveStream(self._error)
        return self.subscription


class _CloseFailingRawLiveStream(_RawLiveStream):
    async def aclose(self) -> None:
        self.closed = True
        raise RuntimeError("close unavailable")


class _CloseFailingRawLiveBus(_RawLiveBus):
    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        _ = session_id, after_sequence
        self.subscription = _CloseFailingRawLiveStream(self._row)
        return self.subscription


def _raw_stored_message() -> dict[str, Any]:
    return UserMessage(
        id="raw-backlog",
        session_id="s1",
        content="raw",
        timestamp=1,
        sequence=8,
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_commit_deduplicates_without_second_live_notification() -> None:
    journal = InMemoryEventJournal()
    stream = journal.subscribe("s1")
    first_live = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    draft = UserMessage(id="event-1", session_id="s1", content="one")
    first = await journal.commit(draft)
    assert await first_live is first

    duplicate = await journal.commit(draft.model_copy(deep=True))
    assert duplicate == first
    assert duplicate is not first
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.01)
    await _close(stream)


@pytest.mark.asyncio
async def test_subscribe_handshake_has_no_backlog_live_gap_or_duplicates() -> None:
    store = _BlockingReadStore()
    journal = InMemoryEventJournal(store)
    first = await journal.commit(UserMessage(session_id="s1", content="backlog"))

    stream = journal.subscribe("s1")
    backlog_task = asyncio.ensure_future(anext(stream))
    await store.backlog_captured.wait()
    live_task = asyncio.create_task(
        journal.commit(UserMessage(session_id="s1", content="live"))
    )
    await asyncio.sleep(0)
    assert not live_task.done()

    store.release_backlog.set()
    backlog = await backlog_task
    assert backlog == first
    assert backlog is not first
    live = await live_task
    assert await anext(stream) is live
    await _close(stream)


@pytest.mark.asyncio
async def test_shared_store_fanout_reaches_other_journals_and_direct_appends() -> None:
    store = InMemoryEventStore()
    reader = InMemoryEventJournal(store)
    writer = InMemoryEventJournal(store)
    subscription = await reader.open_subscription("shared")

    through_writer = await writer.commit(
        UserMessage(id="writer", session_id="shared", content="writer")
    )
    through_store = await store.append(
        UserMessage(id="direct", session_id="shared", content="direct")
    )

    assert [await anext(subscription), await anext(subscription)] == [
        through_writer,
        through_store.event,
    ]
    await subscription.aclose()
    assert store.active_session_lane_count == 0
    assert store.active_listener_count == 0


@pytest.mark.asyncio
async def test_stable_journal_does_not_serialize_unrelated_sessions() -> None:
    class BlockingStore(InMemoryEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
            if draft.session_id == "blocked":
                self.entered.set()
                await self.release.wait()
            return await super()._insert_reserved(draft)

    store = BlockingStore()
    journal = InMemoryEventJournal(store)
    blocked = asyncio.create_task(
        journal.commit(UserMessage(id="blocked", session_id="blocked", content="one"))
    )
    await store.entered.wait()

    unrelated = await asyncio.wait_for(
        journal.commit(UserMessage(id="free", session_id="free", content="one")),
        timeout=0.1,
    )
    assert unrelated.sequence == 1
    assert not blocked.done()

    store.release.set()
    assert (await blocked).sequence == 1
    assert store.active_session_lane_count == 0


@pytest.mark.asyncio
async def test_queued_same_session_commit_cannot_overtake_fanout() -> None:
    class BlockingStore(InMemoryEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
            if draft.id == "first":
                self.entered.set()
                await self.release.wait()
            return await super()._insert_reserved(draft)

    store = BlockingStore()
    journal = InMemoryEventJournal(store)
    subscription = await journal.open_subscription("same")
    first = asyncio.create_task(
        journal.commit(UserMessage(id="first", session_id="same", content="one"))
    )
    await store.entered.wait()
    second = asyncio.create_task(
        journal.commit(UserMessage(id="second", session_id="same", content="two"))
    )
    await asyncio.sleep(0)

    store.release.set()
    await asyncio.gather(first, second)
    assert [await anext(subscription), await anext(subscription)] == [
        first.result(),
        second.result(),
    ]
    await subscription.aclose()


@pytest.mark.asyncio
async def test_split_capacity_is_reserved_before_cross_session_persistence() -> None:
    class BlockingBus(InMemoryEventBus):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def publish(self, event: StoredKajiEvent) -> str:
            self.entered.set()
            await self.release.wait()
            raise RuntimeError("publish unavailable")

    store = InMemoryEventStore()
    bus = BlockingBus()
    journal = SplitEventJournal(store, bus, max_pending_events=1)
    first = asyncio.create_task(
        journal.commit(UserMessage(id="first", session_id="first", content="one"))
    )
    await bus.entered.wait()

    with pytest.raises(EventStoreCapacityError):
        await asyncio.wait_for(
            journal.commit(
                UserMessage(id="second", session_id="second", content="two")
            ),
            timeout=0.1,
        )
    assert await store.last_sequence("second") == 0

    bus.release.set()
    with pytest.raises(EventDeliveryError):
        await first
    assert journal.pending_event_ids == {"first"}


@pytest.mark.asyncio
async def test_append_failure_is_reported_as_not_persisted_and_not_published() -> None:
    journal = InMemoryEventJournal(_FailingAppendStore())
    draft = UserMessage(session_id="s1", content="one")

    with pytest.raises(EventDeliveryError) as caught:
        await journal.commit(draft)

    assert caught.value.code == "EVENT_APPEND_FAILED"
    assert caught.value.phase == "append"
    assert caught.value.event_id == draft.id
    assert caught.value.persisted is False


@pytest.mark.asyncio
async def test_split_publish_retry_uses_persisted_event_without_second_append() -> None:
    store = InMemoryEventStore()
    bus = _FailOnceBus()
    journal = SplitEventJournal(store, bus)
    draft = UserMessage(session_id="s1", content="one")

    with pytest.raises(EventDeliveryError) as caught:
        await journal.commit(draft)
    assert caught.value.code == "EVENT_PUBLISH_FAILED"
    assert caught.value.persisted is True
    assert journal.pending_event_ids == {draft.id}

    retried = await journal.retry_pending(draft.id)
    assert retried.sequence == 1
    assert journal.pending_event_ids == set()
    assert [event.id for event in bus.calls] == [draft.id, draft.id]
    assert len(await store.get_events("s1")) == 1


@pytest.mark.asyncio
async def test_split_pending_delivery_stays_in_sequence_until_target_retry() -> None:
    store = InMemoryEventStore()
    bus = _FailOnceBus()
    journal = SplitEventJournal(store, bus)
    first = UserMessage(session_id="s1", content="first")

    with pytest.raises(EventDeliveryError):
        await journal.commit(first)
    second = UserMessage(session_id="s1", content="second")
    with pytest.raises(EventDeliveryError) as caught:
        await journal.commit(second)

    assert caught.value.event_id == second.id
    assert caught.value.persisted is True
    assert [event.id for event in bus.calls] == [first.id]
    assert journal.pending_event_ids == {first.id, second.id}

    await journal.retry_pending(second.id)

    assert [event.id for event in bus.calls] == [first.id, first.id, second.id]
    assert journal.pending_event_ids == set()


@pytest.mark.asyncio
async def test_split_pending_outbox_applies_backpressure_before_append() -> None:
    store = InMemoryEventStore()
    bus = _AlwaysFailBus()
    journal = SplitEventJournal(store, bus, max_pending_events=2)
    first = UserMessage(session_id="s1", content="first")

    with pytest.raises(EventDeliveryError):
        await journal.commit(first)
    second = UserMessage(session_id="s1", content="second")
    with pytest.raises(EventDeliveryError):
        await journal.commit(second)

    with pytest.raises(EventStoreCapacityError) as caught:
        await journal.commit(UserMessage(session_id="s1", content="third"))

    assert journal.max_pending_events == 2
    assert caught.value.reason == (
        "split delivery outbox is full (2 pending events); "
        "retry pending delivery before appending a new event"
    )
    assert journal.pending_event_ids == {first.id, second.id}
    assert await store.last_sequence("s1") == 2
    assert [event.id for event in bus.calls] == [first.id]


@pytest.mark.asyncio
async def test_lagging_subscriber_overflow_isolated_and_resume_cursor_is_lossless() -> (
    None
):
    journal = InMemoryEventJournal(subscriber_queue_capacity=1)
    stream = journal.subscribe("s1")
    first_task = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    first = await journal.commit(UserMessage(session_id="s1", content="one"))
    assert await first_task is first
    await journal.commit(UserMessage(session_id="s1", content="two"))
    third = await journal.commit(UserMessage(session_id="s1", content="three"))

    with pytest.raises(EventBufferOverflowError) as caught:
        await anext(stream)
    assert caught.value.last_sequence == 1
    assert caught.value.latest_sequence == third.sequence == 3

    missed_page = await journal.store.get_events(
        "s1",
        after_sequence=caught.value.last_sequence,
        limit=1,
    )
    assert [event.sequence for event in missed_page] == [2]
    resumed = journal.subscribe("s1", after_sequence=2)
    assert (await anext(resumed)).sequence == 3
    await _close(resumed)


@pytest.mark.asyncio
async def test_subscription_rejects_backlog_larger_than_its_hard_capacity() -> None:
    journal = InMemoryEventJournal(subscriber_queue_capacity=2)
    for content in ("one", "two", "three"):
        await journal.commit(UserMessage(session_id="s1", content=content))

    stream = journal.subscribe("s1")
    with pytest.raises(EventBufferOverflowError) as caught:
        await anext(stream)
    assert caught.value.last_sequence == 0
    assert caught.value.latest_sequence == 3


@pytest.mark.parametrize("field", ["id", "version", "timestamp"])
@pytest.mark.parametrize("split", [False, True], ids=["stable", "split"])
@pytest.mark.asyncio
async def test_custom_store_subscription_validates_backlog_before_attachment(
    field: str,
    split: bool,
) -> None:
    row = _raw_stored_message()
    row.pop(field)
    store = _RawBacklogStore(row)
    bus = _TrackingBus()
    journal = SplitEventJournal(store, bus) if split else InMemoryEventJournal(store)

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        await journal.open_subscription("s1", after_sequence=7)

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == f"/{field}"
    if split:
        assert bus.subscription is not None
        assert bus.subscription.closed is True
    else:
        assert cast(Any, journal)._subscribers == {}


@pytest.mark.parametrize("field", ["id", "version", "timestamp"])
@pytest.mark.asyncio
async def test_split_subscription_validates_live_rows_before_cursor_advance(
    field: str,
) -> None:
    row = _raw_stored_message()
    row.pop(field)
    bus = _RawLiveBus(row)
    subscription = await SplitEventJournal(
        InMemoryEventStore(),
        bus,
    ).open_subscription("s1", after_sequence=7)

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        await anext(subscription)

    assert raised.value.path == f"/{field}"
    assert cast(Any, subscription)._last_sequence == 7
    assert bus.subscription is not None
    assert bus.subscription.closed is True


@pytest.mark.asyncio
async def test_split_subscription_preserves_schema_error_when_cleanup_fails() -> None:
    row = _raw_stored_message()
    row.pop("id")
    bus = _CloseFailingRawLiveBus(row)
    subscription = await SplitEventJournal(
        InMemoryEventStore(),
        bus,
    ).open_subscription("s1", after_sequence=7)

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        await anext(subscription)

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == "/id"
    assert cast(Any, subscription)._last_sequence == 7
    assert bus.subscription is not None
    assert bus.subscription.closed is True


@pytest.mark.parametrize(
    "error",
    [
        EventSchemaIncompatibleError("/id"),
        asyncio.CancelledError(),
    ],
    ids=["typed", "cancelled"],
)
@pytest.mark.asyncio
async def test_split_subscription_closes_when_live_read_fails(
    error: BaseException,
) -> None:
    bus = _FailingLiveBus(error)
    subscription = await SplitEventJournal(
        InMemoryEventStore(),
        bus,
    ).open_subscription("s1", after_sequence=7)

    with pytest.raises(type(error)) as raised:
        await anext(subscription)

    assert raised.value is error
    assert cast(Any, subscription)._last_sequence == 7
    assert bus.subscription is not None
    assert bus.subscription.closed is True


@pytest.mark.parametrize("field", ["id", "version", "timestamp"])
@pytest.mark.parametrize("split", [False, True], ids=["stable", "split"])
@pytest.mark.asyncio
async def test_custom_store_live_result_is_validated_before_fanout(
    field: str,
    split: bool,
) -> None:
    row = _raw_stored_message()
    row.pop(field)
    store = _RawAppendStore(row)
    bus = _TrackingBus()
    journal = SplitEventJournal(store, bus) if split else InMemoryEventJournal(store)
    subscription = await journal.open_subscription("s1", after_sequence=7)

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        await journal.commit(UserMessage(session_id="s1", content="live"))

    assert raised.value.path == f"/{field}"
    if split:
        assert cast(Any, subscription)._last_sequence == 7
        assert bus.published == []
    else:
        assert cast(Any, subscription)._subscriber.last_sequence == 7
        assert cast(Any, subscription)._subscriber.queue.empty()
    await subscription.aclose()
    if split:
        assert bus.subscription is not None
        assert bus.subscription.closed is True
    else:
        assert cast(Any, journal)._subscribers == {}


@pytest.mark.asyncio
async def test_split_subscription_joins_store_backlog_and_live_without_loss() -> None:
    store = InMemoryEventStore()
    bus = _FailOnceBus()
    bus.fail = False
    journal = SplitEventJournal(store, bus)
    first = await journal.commit(UserMessage(session_id="s1", content="backlog"))

    stream = journal.subscribe("s1")
    backlog = await anext(stream)
    assert backlog == first
    assert backlog is not first
    second = await journal.commit(UserMessage(session_id="s1", content="live"))
    live = await anext(stream)
    assert live == second
    assert live is not second
    await _close(stream)


@pytest.mark.asyncio
async def test_split_subscription_supports_lazy_cursor_backed_bus_without_gap() -> None:
    store = InMemoryEventStore()
    bus = _LazyCursorBackedBus()
    journal = SplitEventJournal(store, bus)
    first = await journal.commit(UserMessage(session_id="s1", content="backlog"))

    stream = journal.subscribe("s1")
    backlog = await anext(stream)
    assert backlog == first
    assert backlog is not first
    assert bus.started is False

    second = await journal.commit(UserMessage(session_id="s1", content="live"))
    assert bus.started is False
    delivered = await anext(stream)
    assert delivered == second
    assert delivered is not second
    assert bus.started is True

    await _close(stream)
    assert bus.closed is True


@pytest.mark.asyncio
async def test_split_subscription_closes_live_iterator_when_backlog_read_fails() -> (
    None
):
    bus = _TrackingBus()
    journal = SplitEventJournal(_FailingReadStore(), bus)

    with pytest.raises(RuntimeError, match="read unavailable"):
        await anext(journal.subscribe("s1"))

    assert bus.subscription is not None
    assert bus.subscription.closed is True


@pytest.mark.asyncio
async def test_split_subscription_closes_live_iterator_when_read_is_cancelled() -> None:
    store = _BlockingReadStore()
    bus = _TrackingBus()
    stream = SplitEventJournal(store, bus).subscribe("s1")
    read = asyncio.ensure_future(anext(stream))
    await store.backlog_captured.wait()

    read.cancel()
    with pytest.raises(asyncio.CancelledError):
        await read

    assert bus.subscription is not None
    assert bus.subscription.closed is True


@pytest.mark.asyncio
async def test_split_subscription_deduplicates_pending_retry_by_sequence() -> None:
    store = InMemoryEventStore()
    bus = _FailOnceBus()
    journal = SplitEventJournal(store, bus)
    draft = UserMessage(session_id="s1", content="pending")
    with pytest.raises(EventDeliveryError):
        await journal.commit(draft)

    stream = journal.subscribe("s1")
    persisted = await anext(stream)
    assert persisted.sequence == 1
    await journal.retry_pending(draft.id)
    second = await journal.commit(UserMessage(session_id="s1", content="next"))
    live = await anext(stream)
    assert live == second
    assert live is not second
    await _close(stream)
