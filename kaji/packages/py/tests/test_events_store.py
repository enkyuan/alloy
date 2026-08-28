import asyncio
from typing import Any, cast

import pytest

from kaji.infra.events import errors as event_errors
from kaji.infra.events.errors import (
    EventIdConflictError,
    EventStoreCapacityError,
    SessionPurgeBusyError,
)
from kaji.infra.events.lanes import NestedEventTransactionError
from kaji.infra.events.session_lifecycle import (
    SessionPurgeAuthorization,
    finish_session_cleanup,
    store_session_purge,
)
from kaji.infra.events.schemas import (
    NewKajiEvent,
    SessionClosed,
    ToolCallCompleted,
    UserMessage,
)
from kaji.infra.events.store import (
    AppendResult,
    InMemoryEventStore,
    supports_session_purge,
)


class _BarrierStore(InMemoryEventStore):
    def __init__(self, blocked_session: str) -> None:
        super().__init__()
        self.blocked_session = blocked_session
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
        if draft.session_id == self.blocked_session:
            self.entered.set()
            await self.release.wait()
        return await super()._insert_reserved(draft)


@pytest.mark.asyncio
async def test_rejected_direct_appends_admit_no_row_and_preserve_sequence_one() -> None:
    store = InMemoryEventStore()
    poisoned = ToolCallCompleted(
        id="poisoned",
        session_id="durable-boundary",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        result={},
        timestamp=1.0,
    )
    cast(Any, poisoned).result = object()

    invalid_type = getattr(event_errors, "InvalidDurableValueError")
    with pytest.raises(invalid_type) as invalid:
        await store.append(poisoned)
    assert invalid.value.subject == "tool_result"
    assert await store.get_events("durable-boundary") == []
    assert await store.last_sequence("durable-boundary") == 0

    oversized = UserMessage(
        id="oversized",
        session_id="durable-boundary",
        content="😀" * (1_048_576 // 4 + 1),
        timestamp=2.0,
    )
    limit_type = getattr(event_errors, "DurableJsonLimitError")
    with pytest.raises(limit_type) as limited:
        await store.append(oversized)
    assert limited.value.subject == "event"
    assert await store.get_events("durable-boundary") == []
    assert await store.last_sequence("durable-boundary") == 0

    accepted = await store.append(
        UserMessage(
            id="accepted",
            session_id="durable-boundary",
            content="ok",
            timestamp=3.0,
        )
    )
    assert accepted.event.sequence == 1
    assert [event.id for event in await store.get_events("durable-boundary")] == [
        "accepted"
    ]


@pytest.mark.asyncio
async def test_append_order_wins_over_equal_and_backdated_timestamps() -> None:
    store = InMemoryEventStore()
    first = await store.append(
        UserMessage(session_id="s1", content="first", timestamp=2.0)
    )
    second = await store.append(
        UserMessage(session_id="s1", content="second", timestamp=2.0)
    )
    third = await store.append(
        UserMessage(session_id="s1", content="third", timestamp=1.0)
    )

    assert [first.event.sequence, second.event.sequence, third.event.sequence] == [
        1,
        2,
        3,
    ]
    events = await store.get_events("s1")
    assert [event.content for event in events if isinstance(event, UserMessage)] == [
        "first",
        "second",
        "third",
    ]


@pytest.mark.asyncio
async def test_concurrent_appends_assign_contiguous_session_sequences() -> None:
    store = InMemoryEventStore()
    results = await asyncio.gather(
        *(
            store.append(UserMessage(session_id="s1", content=str(index)))
            for index in range(50)
        )
    )

    assert sorted(result.event.sequence for result in results) == list(range(1, 51))
    assert await store.last_sequence("s1") == 50


@pytest.mark.asyncio
async def test_session_lane_does_not_block_an_unrelated_session() -> None:
    store = _BarrierStore("blocked")
    blocked = asyncio.create_task(
        store.append(UserMessage(id="blocked", session_id="blocked", content="one"))
    )
    await store.entered.wait()

    unrelated = await asyncio.wait_for(
        store.append(UserMessage(id="free", session_id="free", content="one")),
        timeout=0.1,
    )
    assert unrelated.event.sequence == 1
    assert not blocked.done()

    store.release.set()
    assert (await blocked).event.sequence == 1
    assert store._lanes.active_count == 0


@pytest.mark.asyncio
async def test_same_session_lane_is_fifo_and_cleans_up_after_cancellation() -> None:
    store = _BarrierStore("same")
    first = asyncio.create_task(
        store.append(UserMessage(id="first", session_id="same", content="one"))
    )
    await store.entered.wait()
    second = asyncio.create_task(
        store.append(UserMessage(id="second", session_id="same", content="two"))
    )
    await asyncio.sleep(0)
    assert not second.done()

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    store.release.set()
    assert (await second).event.sequence == 1
    assert store.active_session_lane_count == 0
    assert store.active_id_reservation_count == 0


@pytest.mark.asyncio
async def test_double_cancel_before_insert_cannot_strand_id_reservation() -> None:
    class PreInsertStore(InMemoryEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.proceed = asyncio.Event()

        async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
            self.entered.set()
            await self.proceed.wait()
            return await super()._insert_reserved(draft)

    store = PreInsertStore()
    event = UserMessage(id="cancel-before", session_id="cancel-before", content="one")
    owner = asyncio.create_task(store.append(event))
    await store.entered.wait()
    await store._metadata_lock.acquire()
    store.proceed.set()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    store._metadata_lock.release()

    with pytest.raises(asyncio.CancelledError):
        await owner
    assert store.active_id_reservation_count == 0
    assert store.active_session_lane_count == 0
    inserted = await asyncio.wait_for(store.append(event), timeout=0.1)
    assert inserted.inserted is True


@pytest.mark.asyncio
async def test_double_cancel_after_insert_settles_id_reservation() -> None:
    class PostInsertStore(InMemoryEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.inserted = asyncio.Event()
            self.proceed = asyncio.Event()

        async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
            result = await super()._insert_reserved(draft)
            self.inserted.set()
            await self.proceed.wait()
            return result

    store = PostInsertStore()
    event = UserMessage(id="cancel-after", session_id="cancel-after", content="one")
    owner = asyncio.create_task(store.append(event))
    await store.inserted.wait()
    await store._metadata_lock.acquire()
    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    store._metadata_lock.release()

    with pytest.raises(asyncio.CancelledError):
        await owner
    assert store.active_id_reservation_count == 0
    assert store.active_session_lane_count == 0
    duplicate = await asyncio.wait_for(store.append(event), timeout=0.1)
    assert duplicate.inserted is False
    assert duplicate.event.sequence == 1


@pytest.mark.asyncio
async def test_nested_session_transaction_fails_instead_of_deadlocking() -> None:
    store = InMemoryEventStore()

    async with store.session_transaction("s1"):
        with pytest.raises(NestedEventTransactionError):
            async with store.session_transaction("s1"):
                raise AssertionError("nested transaction unexpectedly entered")

    assert store.active_session_lane_count == 0


@pytest.mark.asyncio
async def test_child_transaction_during_parent_hold_fails_immediately() -> None:
    store = InMemoryEventStore()

    async with store.session_transaction("parent"):
        child = asyncio.create_task(
            store.append(UserMessage(id="child", session_id="child", content="one"))
        )
        with pytest.raises(NestedEventTransactionError):
            await asyncio.wait_for(child, timeout=0.1)

    assert store.active_session_lane_count == 0


@pytest.mark.asyncio
async def test_child_created_during_hold_can_commit_after_parent_releases() -> None:
    store = InMemoryEventStore()
    release = asyncio.Event()

    async def delayed_append() -> AppendResult:
        await release.wait()
        return await store.append(
            UserMessage(id="delayed", session_id="delayed", content="one")
        )

    async with store.session_transaction("parent"):
        child = asyncio.create_task(delayed_append())
    release.set()

    assert (await asyncio.wait_for(child, timeout=0.1)).inserted is True
    assert store.active_session_lane_count == 0


@pytest.mark.asyncio
async def test_retained_closed_session_requires_purge_after_its_lane_releases() -> None:
    store = InMemoryEventStore(max_sessions=1)
    await store.append(SessionClosed(id="closed", session_id="closed"))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_closed() -> None:
        async with store.session_transaction("closed"):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold_closed())
    await entered.wait()
    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(id="new", session_id="new", content="one"))
    release.set()
    await holder

    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(id="new", session_id="new", content="one"))
    assert await store.purge_session("closed") is True
    inserted = await store.append(
        UserMessage(id="new", session_id="new", content="one")
    )
    assert inserted.event.sequence == 1


@pytest.mark.asyncio
async def test_cross_session_id_conflict_does_not_wait_for_blocked_owner() -> None:
    store = _BarrierStore("owner")
    owner = asyncio.create_task(
        store.append(UserMessage(id="shared", session_id="owner", content="one"))
    )
    await store.entered.wait()

    with pytest.raises(EventIdConflictError):
        await asyncio.wait_for(
            store.append(
                UserMessage(id="shared", session_id="other", content="different")
            ),
            timeout=0.1,
        )

    store.release.set()
    assert (await owner).inserted is True
    assert store.active_id_reservation_count == 0


@pytest.mark.asyncio
async def test_duplicate_id_is_idempotent_but_conflicting_payload_fails() -> None:
    store = InMemoryEventStore()
    event = UserMessage(id="event-1", session_id="s1", content="same")

    inserted = await store.append(event)
    duplicate = await store.append(event.model_copy(deep=True))

    assert inserted.inserted is True
    assert duplicate.inserted is False
    assert duplicate.event is not inserted.event
    assert duplicate.event == inserted.event
    assert await store.last_sequence("s1") == 1

    with pytest.raises(EventIdConflictError) as caught:
        await store.append(
            UserMessage(id="event-1", session_id="s1", content="different")
        )
    assert caught.value.code == "EVENT_ID_CONFLICT"


@pytest.mark.asyncio
async def test_store_deeply_isolates_drafts_append_results_and_reads() -> None:
    store = InMemoryEventStore()
    draft = UserMessage(
        id="isolated",
        session_id="s1",
        turn_id="turn-original",
        content="original",
        metadata={"nested": {"value": "original"}},
    )

    inserted = await store.append(draft)
    draft.turn_id = "turn-mutated-draft"
    cast(dict[str, Any], draft.metadata["nested"])["value"] = "mutated-draft"
    inserted.event.turn_id = "turn-mutated-result"
    inserted.event.metadata["nested"]["value"] = "mutated-result"

    first_read = await store.get_events("s1")
    assert first_read[0].turn_id == "turn-original"
    assert first_read[0].metadata == {"nested": {"value": "original"}}

    first_read[0].turn_id = "turn-mutated-read"
    first_read[0].metadata["nested"]["value"] = "mutated-read"
    second_read = await store.get_events("s1")

    assert second_read[0].turn_id == "turn-original"
    assert second_read[0].metadata == {"nested": {"value": "original"}}

    duplicate = await store.append(
        UserMessage(
            id="isolated",
            session_id="s1",
            turn_id="turn-original",
            timestamp=second_read[0].timestamp,
            content="original",
            metadata={"nested": {"value": "original"}},
        )
    )
    assert duplicate.inserted is False
    duplicate.event.turn_id = "turn-mutated-duplicate"
    duplicate.event.metadata["nested"]["value"] = "mutated-duplicate"

    final_read = await store.get_events("s1")
    assert final_read[0].turn_id == "turn-original"
    assert final_read[0].metadata == {"nested": {"value": "original"}}


@pytest.mark.asyncio
async def test_cursor_is_exclusive_and_limit_is_exact() -> None:
    store = InMemoryEventStore()
    for index in range(5):
        await store.append(UserMessage(session_id="s1", content=str(index)))

    page = await store.get_events("s1", after_sequence=2, limit=2)
    assert [event.sequence for event in page] == [3, 4]
    assert await store.get_events("s1", after_sequence=5) == []
    assert await store.get_events("s1", limit=0) == []


@pytest.mark.asyncio
async def test_store_bounds_never_silently_truncate_active_history() -> None:
    store = InMemoryEventStore(max_sessions=1, max_events_per_session=1)
    await store.append(UserMessage(session_id="active", content="one"))

    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="active", content="two"))
    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="other", content="one"))

    assert [event.sequence for event in await store.get_events("active")] == [1]


@pytest.mark.asyncio
async def test_closed_session_requires_explicit_purge_before_capacity_reuse() -> None:
    store = InMemoryEventStore(max_sessions=1)
    await store.append(UserMessage(session_id="old", content="one"))
    await store.append(SessionClosed(session_id="old"))
    await store.get_events("old")

    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="new", content="two"))

    assert [event.sequence for event in await store.get_events("old")] == [1, 2]
    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="new", content="two"))


@pytest.mark.asyncio
async def test_purge_removes_owned_indexes_and_restarts_sequence_one() -> None:
    store = InMemoryEventStore()
    await store.append(
        UserMessage(id="reusable-id", session_id="purged", content="old")
    )
    await store.append(
        UserMessage(id="retained-id", session_id="retained", content="keep")
    )

    assert supports_session_purge(store)
    assert await store.purge_session("purged") is True
    assert await store.get_events("purged") == []
    assert [event.id for event in await store.get_events("retained")] == ["retained-id"]

    replacement = await store.append(
        UserMessage(id="reusable-id", session_id="purged", content="new")
    )
    assert replacement.event.sequence == 1
    assert await store.purge_session("missing") is False


@pytest.mark.asyncio
async def test_internal_purge_authorization_is_exact_and_single_use() -> None:
    store = InMemoryEventStore()
    other = InMemoryEventStore()
    await store.append(UserMessage(session_id="authorized", content="old"))

    with store_session_purge(store, "authorized") as lease:
        with pytest.raises(SessionPurgeBusyError):
            await store._purge_session_authorized(
                "other-session",
                lease.authorization,
            )
        with pytest.raises(SessionPurgeBusyError):
            await other._purge_session_authorized(
                "authorized",
                lease.authorization,
            )
        with pytest.raises(SessionPurgeBusyError):
            await store._purge_session_authorized(
                "authorized",
                SessionPurgeAuthorization(),
            )

        assert (
            await store._purge_session_authorized(
                "authorized",
                lease.authorization,
            )
            is True
        )
        with pytest.raises(SessionPurgeBusyError):
            await store._purge_session_authorized(
                "authorized",
                lease.authorization,
            )
        finish_session_cleanup(lease)

    assert await store.get_events("authorized") == []


@pytest.mark.asyncio
async def test_unknown_session_returns_empty_and_zero_cursor() -> None:
    store = InMemoryEventStore()
    assert await store.get_events("missing") == []
    assert await store.last_sequence("missing") == 0
