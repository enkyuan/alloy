"""Tests for AgentRuntime.turn — the one-call hello-world wrapper."""

from __future__ import annotations

import asyncio
import gc
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from kaji.infra.events import session_lifecycle
from kaji.infra.events.errors import (
    SessionPurgeBusyError,
    SessionPurgeUnsupportedError,
)
from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.journal import SplitEventJournal
from kaji.infra.events.schemas import NewKajiEvent, StoredKajiEvent, UserMessage
from kaji.infra.events.store import (
    AppendResult,
    EventStore,
    InMemoryEventStore,
    supports_session_purge,
)
from kaji.infra.events.session_lifecycle import SessionPurgeAuthorization
from kaji.infra.events.types import EventType
from kaji.runtime.agents import AgentBuilder, InMemoryTurnCoordinator, TurnContext
from kaji.runtime.tools.errors import UnclassifiedToolRiskError
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.mock import MockProvider


class _PublicPurgeOnlyStore:
    """Custom store with the supported public one-argument purge shape only."""

    def __init__(self) -> None:
        self.inner = InMemoryEventStore()
        self.max_sessions = self.inner.max_sessions

    async def append(self, event: NewKajiEvent) -> AppendResult:
        return await self.inner.append(event)

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        return await self.inner.get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def last_sequence(self, session_id: str) -> int:
        return await self.inner.last_sequence(session_id)

    async def purge_session(self, session_id: str) -> bool:
        return await self.inner.purge_session(session_id)


class _ControlledPurgeStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.purge_entered = asyncio.Event()
        self.purge_release = asyncio.Event()

    async def _purge_session_authorized(
        self,
        session_id: str,
        authorization: SessionPurgeAuthorization,
    ) -> bool:
        self.purge_entered.set()
        await self.purge_release.wait()
        return await super()._purge_session_authorized(session_id, authorization)


@dataclass
class _UnhashableEventStore:
    inner: InMemoryEventStore = field(default_factory=InMemoryEventStore)

    @property
    def max_sessions(self) -> int:
        return self.inner.max_sessions

    async def append(self, event: NewKajiEvent) -> AppendResult:
        return await self.inner.append(event)

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        return await self.inner.get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def last_sequence(self, session_id: str) -> int:
        return await self.inner.last_sequence(session_id)


class _SlotsOnlyEventStore:
    __slots__ = ("inner", "max_sessions")

    def __init__(self) -> None:
        self.inner = InMemoryEventStore()
        self.max_sessions = self.inner.max_sessions

    async def append(self, event: NewKajiEvent) -> AppendResult:
        return await self.inner.append(event)

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        return await self.inner.get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def last_sequence(self, session_id: str) -> int:
        return await self.inner.last_sequence(session_id)


def _build(provider: ModelProvider, store: InMemoryEventStore | None = None):
    store = store or InMemoryEventStore()
    return (
        AgentBuilder().provider(provider).build(store=store),
        store,
    )


@pytest.mark.asyncio
async def test_turn_returns_text_for_simple_reply():
    runtime, _ = _build(MockProvider(reply="hello world"))
    result = await runtime.turn("ping")
    assert result.text == "hello world"
    assert result.session_id
    assert result.tool_call_events == []


@pytest.mark.asyncio
async def test_turn_generates_session_id_when_none_given():
    runtime, store = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first")
    r2 = await runtime.turn("second")
    assert r1.session_id != r2.session_id
    s1 = await store.get_events(r1.session_id)
    s2 = await store.get_events(r2.session_id)
    assert s1 and s2
    assert s1[0].type == EventType.SESSION_CREATED
    assert s2[0].type == EventType.SESSION_CREATED


@pytest.mark.asyncio
async def test_turn_reuses_existing_session_id():
    runtime, store = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first", session_id="s-1")
    r2 = await runtime.turn("second", session_id="s-1")
    assert r1.session_id == r2.session_id == "s-1"
    events = await store.get_events("s-1")
    created = [e for e in events if e.type == EventType.SESSION_CREATED]
    assert len(created) == 1


@pytest.mark.asyncio
async def test_turn_rejects_unadvertised_tool_before_request_event():
    runtime, store = _build(MockProvider(tool_call={"name": "ping", "args": {}}))
    with pytest.raises(UnclassifiedToolRiskError):
        await runtime.turn(
            "call ping",
            session_id="unadvertised",
            context=TurnContext(principal_id="test-principal"),
        )
    events = await store.get_events("unadvertised")
    assert all(event.type != EventType.TOOL_CALL_REQUESTED for event in events)


@pytest.mark.asyncio
async def test_turn_text_uses_message_completed_not_delta():
    """Text is sourced from AgentMessageCompleted, not delta accumulation."""
    runtime, _ = _build(MockProvider(reply="exact text"))
    result = await runtime.turn("hi")
    assert result.text == "exact text"


@pytest.mark.asyncio
async def test_turn_returns_events_scoped_to_this_turn():
    runtime, _ = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first", session_id="s-1")
    r2 = await runtime.turn("second", session_id="s-1")
    # r2.events should not contain the SessionCreated event (only first turn)
    assert not any(e.type == EventType.SESSION_CREATED for e in r2.events)
    # but r1.events should
    assert any(e.type == EventType.SESSION_CREATED for e in r1.events)


@pytest.mark.asyncio
async def test_turn_propagates_provider_errors():
    """turn() is a wrapper, not an error sink. send() exceptions bubble."""

    class FailingProvider:
        async def generate(self, *_a, **_kw):
            raise RuntimeError("provider boom")

        async def generate_stream(self, *_a, **_kw):
            raise RuntimeError("provider boom")
            yield  # pragma: no cover

    runtime, _ = _build(FailingProvider())
    with pytest.raises(RuntimeError, match="provider boom"):
        await runtime.turn("hi")


@pytest.mark.parametrize(
    ("store_factory", "unsupported_operation"),
    [
        pytest.param(_UnhashableEventStore, hash, id="unhashable"),
        pytest.param(_SlotsOnlyEventStore, weakref.ref, id="non-weakref"),
    ],
)
@pytest.mark.asyncio
async def test_runtime_lifecycle_accepts_identity_only_event_stores(
    store_factory: Callable[[], EventStore],
    unsupported_operation: Callable[[object], object],
) -> None:
    store = store_factory()
    with pytest.raises(TypeError):
        unsupported_operation(store)

    runtime = (
        AgentBuilder()
        .provider(MockProvider(reply="ok"))
        .coordinator(InMemoryTurnCoordinator())
        .build(store=store)
    )
    result = await runtime.turn("hello", session_id="identity-store")
    assert result.text == "ok"
    assert await store.last_sequence("identity-store") > 0

    store_identity = id(store)
    assert store_identity in session_lifecycle._STORES
    runtime_reference = weakref.ref(runtime)
    del runtime
    gc.collect()
    assert runtime_reference() is None
    assert store_identity not in session_lifecycle._STORES


def test_lifecycle_registry_replaces_a_stale_identity_entry() -> None:
    stale_store = _SlotsOnlyEventStore()
    store = _SlotsOnlyEventStore()
    stale_entry = session_lifecycle._StoreEntry(
        identity=id(stale_store),
        strong_store=stale_store,
    )
    session_lifecycle._STORES[id(store)] = stale_entry

    try:
        with session_lifecycle.store_session_operation(store, "reused-identity"):
            current = session_lifecycle._STORES[id(store)]
            assert current is not stale_entry
            assert current.resolve() is store
        assert id(store) not in session_lifecycle._STORES
    finally:
        session_lifecycle._STORES.pop(id(store), None)


def test_non_weakref_store_retains_post_delete_cleanup_targets() -> None:
    store = _SlotsOnlyEventStore()
    runtime = (
        AgentBuilder()
        .provider(MockProvider(reply="ok"))
        .coordinator(InMemoryTurnCoordinator())
        .build(store=store)
    )
    with session_lifecycle.store_session_purge(
        store,
        "cleanup-pending",
        coordinated=True,
    ) as initial_lease:
        assert initial_lease.cleanup_targets == (runtime,)
        session_lifecycle.assert_physical_purge_authorized(
            store,
            "cleanup-pending",
            initial_lease.authorization,
        )
        session_lifecycle.mark_physical_purge_committed(initial_lease)

    del initial_lease
    runtime_reference = weakref.ref(runtime)
    del runtime
    gc.collect()
    retained_runtime = runtime_reference()
    assert retained_runtime is not None
    assert id(store) in session_lifecycle._STORES

    with session_lifecycle.store_session_purge(
        store,
        "cleanup-pending",
        coordinated=True,
        retry_cleanup=True,
    ) as recovery_lease:
        assert recovery_lease.cleanup_targets == (retained_runtime,)
        session_lifecycle.finish_session_cleanup(recovery_lease)

    del recovery_lease
    del retained_runtime
    gc.collect()
    assert runtime_reference() is None
    assert id(store) not in session_lifecycle._STORES


@pytest.mark.asyncio
async def test_runtime_purge_closes_subscribers_and_restarts_shared_generation() -> (
    None
):
    store = InMemoryEventStore()
    runtime, _ = _build(MockProvider(reply="first"), store)
    sibling, _ = _build(MockProvider(reply="second"), store)
    await runtime.turn("old-one", session_id="shared-generation")
    await sibling.turn("old-two", session_id="shared-generation")

    old_events = await store.get_events("shared-generation")
    subscription = await runtime.journal.open_subscription("shared-generation")
    for expected in old_events:
        assert (await anext(subscription)).id == expected.id
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)
    assert not waiting.done()

    assert await runtime.purge_session("shared-generation") is True
    with pytest.raises(StopAsyncIteration):
        await waiting
    assert store.active_listener_count == 0
    assert await store.get_events("shared-generation") == []

    fresh_subscription = await sibling.journal.open_subscription("shared-generation")
    fresh_event = asyncio.create_task(anext(fresh_subscription))
    result = await sibling.turn("fresh", session_id="shared-generation")
    created = await fresh_event
    assert created.type == EventType.SESSION_CREATED
    assert created.sequence == 1
    assert result.events[0].sequence == 1
    await fresh_subscription.aclose()


@pytest.mark.asyncio
async def test_runtime_rejects_public_only_custom_purge_without_partial_deletion() -> (
    None
):
    store = _PublicPurgeOnlyStore()
    assert isinstance(store, EventStore)
    assert supports_session_purge(store)
    await store.append(UserMessage(session_id="direct", content="old"))
    assert await store.purge_session("direct") is True

    runtime = AgentBuilder().provider(MockProvider(reply="kept")).build(store=store)
    await runtime.turn("keep", session_id="runtime-owned")
    retained = await store.get_events("runtime-owned")
    with pytest.raises(SessionPurgeUnsupportedError) as unsupported:
        await runtime.purge_session("runtime-owned")
    assert unsupported.value.component == "event_store"
    assert await store.get_events("runtime-owned") == retained


@pytest.mark.asyncio
async def test_direct_purge_and_owner_registration_cannot_borrow_runtime_lease() -> (
    None
):
    store = _ControlledPurgeStore()
    runtime, _ = _build(MockProvider(reply="old"), store)
    await runtime.turn("old", session_id="purge-race")

    purge = asyncio.create_task(runtime.purge_session("purge-race"))
    await store.purge_entered.wait()
    with pytest.raises(SessionPurgeBusyError):
        await store.purge_session("purge-race")
    with pytest.raises(SessionPurgeBusyError):
        _build(MockProvider(reply="new"), store)

    store.purge_release.set()
    assert await purge is True


@pytest.mark.asyncio
async def test_split_delivery_blocks_runtime_and_underlying_store_purge() -> None:
    store = InMemoryEventStore()
    journal = SplitEventJournal(store, InMemoryEventBus())
    runtime = (
        AgentBuilder()
        .provider(MockProvider(reply="old"))
        .build(store=store, journal=journal)
    )
    await runtime.turn("old", session_id="split-generation")

    with pytest.raises(SessionPurgeUnsupportedError) as runtime_blocked:
        await runtime.purge_session("split-generation")
    assert runtime_blocked.value.component == "event_delivery"
    with pytest.raises(SessionPurgeUnsupportedError) as store_blocked:
        await store.purge_session("split-generation")
    assert store_blocked.value.component == "event_delivery"
    assert await store.get_events("split-generation")
