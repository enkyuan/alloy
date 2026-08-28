"""Process-local session-generation fences shared by stores and runtimes."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, TypeVar, runtime_checkable
from weakref import ReferenceType, ref

from kaji.infra.events.errors import (
    SessionPurgeBusyError,
    SessionPurgeComponent,
    SessionPurgeUnsupportedError,
)

if TYPE_CHECKING:
    from kaji.infra.events.store.base import EventStore
else:
    EventStore = Any


class StoreRuntimeOwner(Protocol):
    """Runtime state that must converge before a session ID can be reused."""

    def session_purge_unsupported_component(
        self,
    ) -> SessionPurgeComponent | None: ...

    def is_session_busy(self, session_id: str) -> bool: ...

    async def close_session_subscriptions(
        self,
        session_id: str,
        authorization: SessionPurgeAuthorization,
    ) -> None: ...

    def clear_session_caches(self, session_id: str) -> None: ...

    async def release_settled_session(self, session_id: str) -> None: ...


class StorePurgeBlocker(Protocol):
    """Explicit-lifetime blocker for unsupported delivery implementations."""

    @property
    def session_purge_component(self) -> SessionPurgeComponent: ...


class SessionPurgeAuthorization:
    """Opaque identity token issued only for one active purge lease."""

    __slots__ = ()


@dataclass(slots=True)
class _SessionState:
    active_operations: int = 0
    quarantined_providers: int = 0
    purging: bool = False
    active_authorization: SessionPurgeAuthorization | None = None
    active_lease: StoreSessionPurgeLease | None = None
    cleanup_pending: bool = False
    cleanup_targets: tuple[StoreRuntimeOwner, ...] = ()
    physical_existed: bool = False


@dataclass(slots=True)
class _StoreState:
    owners: list[ReferenceType[StoreRuntimeOwner]] = field(default_factory=list)
    blockers: set[_PurgeBlockerToken] = field(default_factory=set)
    sessions: dict[str, _SessionState] = field(default_factory=dict)


@dataclass(eq=False, frozen=True, slots=True)
class _PurgeBlockerToken:
    session_purge_component: SessionPurgeComponent


@dataclass(slots=True)
class _StoreEntry:
    identity: int
    state: _StoreState = field(default_factory=_StoreState)
    weak_store: ReferenceType[Any] | None = None
    strong_store: EventStore | None = None

    def resolve(self) -> EventStore | None:
        if self.weak_store is not None:
            return self.weak_store()
        return self.strong_store


@dataclass(slots=True)
class StoreSessionPurgeLease:
    """One store/session purge attempt and its retained cleanup targets."""

    store: EventStore
    session_id: str
    authorization: SessionPurgeAuthorization
    cleanup_targets: tuple[StoreRuntimeOwner, ...]
    recovering: bool
    _store_state: _StoreState
    _session_state: _SessionState
    _authorization_consumed: bool = False
    _physical_committed: bool = False
    _physical_existed: bool = False

    @property
    def physical_existed(self) -> bool:
        return (
            self._session_state.physical_existed
            if self.recovering
            else self._physical_existed
        )


@runtime_checkable
class CoordinatedPurgeableEventStore(Protocol):
    """Internal capability that validates an opaque coordinated lease."""

    async def _purge_session_authorized(
        self,
        session_id: str,
        authorization: SessionPurgeAuthorization,
    ) -> bool: ...


@runtime_checkable
class AuthorizedListenerTeardownStore(Protocol):
    """Internal narrow capability for detaching listeners during purge."""

    async def _detach_listeners_authorized(
        self,
        session_id: str,
        listeners: tuple[object, ...],
        authorization: SessionPurgeAuthorization,
    ) -> None: ...


_STORES: dict[int, _StoreEntry] = {}
_ReferenceTarget = TypeVar("_ReferenceTarget", bound=object)

# Session-generation ordering:
# operation/quarantine -> purge lease -> authorized delete -> cleanup tombstone -> reuse


def _discard_store_entry(
    identity: int,
    reference: ReferenceType[Any],
) -> None:
    entry = _STORES.get(identity)
    if entry is not None and entry.weak_store is reference:
        _STORES.pop(identity, None)


def _existing_store_entry(store: EventStore) -> _StoreEntry | None:
    identity = id(store)
    entry = _STORES.get(identity)
    if entry is None:
        return None
    if entry.resolve() is store:
        return entry
    _STORES.pop(identity, None)
    return None


def _store_entry(store: EventStore) -> _StoreEntry:
    entry = _existing_store_entry(store)
    if entry is not None:
        return entry

    identity = id(store)
    entry = _StoreEntry(identity=identity)
    try:
        entry.weak_store = ref(
            store,
            lambda dead, identity=identity: _discard_store_entry(identity, dead),
        )
    except TypeError:
        entry.strong_store = store
    _STORES[identity] = entry
    return entry


def _store_state(store: EventStore) -> _StoreState:
    return _store_entry(store).state


def _live_references(
    references: list[ReferenceType[_ReferenceTarget]],
) -> list[_ReferenceTarget]:
    live: list[_ReferenceTarget] = []
    retained: list[ReferenceType[_ReferenceTarget]] = []
    for reference in references:
        value = reference()
        if value is not None:
            live.append(value)
            retained.append(reference)
    references[:] = retained
    return live


def _maybe_prune_entry(entry: _StoreEntry) -> None:
    state = entry.state
    if state.sessions or _live_references(state.owners) or state.blockers:
        return
    if _STORES.get(entry.identity) is entry:
        _STORES.pop(entry.identity, None)


def runtime_owners_for_store(store: EventStore) -> tuple[StoreRuntimeOwner, ...]:
    entry = _existing_store_entry(store)
    if entry is None:
        return ()
    owners = tuple(_live_references(entry.state.owners))
    _maybe_prune_entry(entry)
    return owners


def _blockers_for_store(store: EventStore) -> tuple[StorePurgeBlocker, ...]:
    entry = _existing_store_entry(store)
    if entry is None:
        return ()
    blockers = tuple(entry.state.blockers)
    _maybe_prune_entry(entry)
    return blockers


def _registration_blocked_session(state: _StoreState) -> str | None:
    return next(
        (
            session_id
            for session_id, session in state.sessions.items()
            if session.purging or session.cleanup_pending
        ),
        None,
    )


def _register_weak(
    entry: _StoreEntry,
    references: list[ReferenceType[_ReferenceTarget]],
    value: _ReferenceTarget,
) -> Callable[[], None]:
    _live_references(references)

    def expired(reference: ReferenceType[_ReferenceTarget]) -> None:
        try:
            references.remove(reference)
        except ValueError:
            pass
        _maybe_prune_entry(entry)

    reference = ref(value, expired)
    references.append(reference)
    released = False

    def unregister() -> None:
        nonlocal released
        if released:
            return
        released = True
        try:
            references.remove(reference)
        except ValueError:
            pass
        _maybe_prune_entry(entry)

    return unregister


def register_runtime_owner(
    store: EventStore,
    owner: StoreRuntimeOwner,
) -> Callable[[], None]:
    entry = _store_entry(store)
    state = entry.state
    blocked = _registration_blocked_session(state)
    if blocked is not None:
        raise SessionPurgeBusyError(blocked)
    return _register_weak(entry, state.owners, owner)


def register_purge_blocker(
    store: EventStore,
    blocker: StorePurgeBlocker,
) -> Callable[[], None]:
    entry = _store_entry(store)
    state = entry.state
    blocked = _registration_blocked_session(state)
    if blocked is not None:
        raise SessionPurgeBusyError(blocked)
    token = _PurgeBlockerToken(blocker.session_purge_component)
    state.blockers.add(token)
    released = False

    def unregister() -> None:
        nonlocal released
        if released:
            return
        released = True
        state.blockers.discard(token)
        _maybe_prune_entry(entry)

    return unregister


def _session_state(
    store: EventStore,
    session_id: str,
) -> tuple[_StoreState, _SessionState]:
    stores = _store_state(store)
    session = stores.sessions.get(session_id)
    if session is None:
        session = _SessionState()
        stores.sessions[session_id] = session
    return stores, session


def _release_session_state(
    store: EventStore,
    session_id: str,
    stores: _StoreState,
    session: _SessionState,
) -> None:
    if (
        session.active_operations == 0
        and session.quarantined_providers == 0
        and not session.purging
        and not session.cleanup_pending
        and stores.sessions.get(session_id) is session
    ):
        stores.sessions.pop(session_id, None)
    entry = _existing_store_entry(store)
    if entry is not None and entry.state is stores:
        _maybe_prune_entry(entry)


@contextmanager
def store_session_operation(store: EventStore, session_id: str) -> Iterator[None]:
    stores, session = _session_state(store, session_id)
    if session.purging or session.cleanup_pending:
        _release_session_state(store, session_id, stores, session)
        raise SessionPurgeBusyError(session_id)
    session.active_operations += 1
    try:
        yield
    finally:
        session.active_operations -= 1
        _release_session_state(store, session_id, stores, session)


def retain_store_session_quarantine(
    store: EventStore,
    session_id: str,
) -> Callable[[], None]:
    stores, session = _session_state(store, session_id)
    if session.purging or session.cleanup_pending:
        raise SessionPurgeBusyError(session_id)
    session.quarantined_providers += 1
    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        session.quarantined_providers -= 1
        _release_session_state(store, session_id, stores, session)

    return release


@contextmanager
def store_session_purge(
    store: EventStore,
    session_id: str,
    *,
    coordinated: bool = False,
    retry_cleanup: bool = False,
) -> Iterator[StoreSessionPurgeLease]:
    stores, session = _session_state(store, session_id)
    if session.purging or session.active_operations or session.quarantined_providers:
        _release_session_state(store, session_id, stores, session)
        raise SessionPurgeBusyError(session_id)

    blockers = _blockers_for_store(store)
    if blockers:
        _release_session_state(store, session_id, stores, session)
        raise SessionPurgeUnsupportedError(
            session_id,
            blockers[0].session_purge_component,
        )

    owners = runtime_owners_for_store(store)
    if session.cleanup_pending:
        if not coordinated or not retry_cleanup:
            raise SessionPurgeBusyError(session_id)
        cleanup_targets = session.cleanup_targets
        recovering = True
    else:
        if owners and not coordinated:
            _release_session_state(store, session_id, stores, session)
            raise SessionPurgeBusyError(session_id)
        cleanup_targets = owners
        recovering = False

    authorization = SessionPurgeAuthorization()
    lease = StoreSessionPurgeLease(
        store=store,
        session_id=session_id,
        authorization=authorization,
        cleanup_targets=cleanup_targets,
        recovering=recovering,
        _store_state=stores,
        _session_state=session,
    )
    session.purging = True
    session.active_authorization = authorization
    session.active_lease = lease
    try:
        yield lease
    finally:
        if session.active_lease is lease:
            session.active_lease = None
            session.active_authorization = None
            session.purging = False
        _release_session_state(store, session_id, stores, session)


def _assert_active_lease(lease: StoreSessionPurgeLease) -> None:
    state = lease._session_state
    if (
        not state.purging
        or state.active_lease is not lease
        or state.active_authorization is not lease.authorization
    ):
        raise SessionPurgeBusyError(lease.session_id)


@contextmanager
def authorized_session_teardown(
    store: EventStore,
    session_id: str,
    authorization: SessionPurgeAuthorization,
) -> Iterator[None]:
    entry = _existing_store_entry(store)
    stores = None if entry is None else entry.state
    session = None if stores is None else stores.sessions.get(session_id)
    if (
        session is None
        or not session.purging
        or session.active_authorization is not authorization
        or session.active_lease is None
        or session.active_lease._authorization_consumed
    ):
        raise SessionPurgeBusyError(session_id)
    yield


def assert_physical_purge_authorized(
    store: EventStore,
    session_id: str,
    authorization: SessionPurgeAuthorization,
) -> StoreSessionPurgeLease:
    entry = _existing_store_entry(store)
    stores = None if entry is None else entry.state
    session = None if stores is None else stores.sessions.get(session_id)
    if session is None:
        raise SessionPurgeBusyError(session_id)
    lease = session.active_lease
    if (
        lease is None
        or lease.store is not store
        or lease.session_id != session_id
        or lease.authorization is not authorization
        or session.active_authorization is not authorization
        or lease.recovering
        or lease._authorization_consumed
    ):
        raise SessionPurgeBusyError(session_id)
    lease._authorization_consumed = True
    return lease


def mark_physical_purge_committed(lease: StoreSessionPurgeLease) -> None:
    _assert_active_lease(lease)
    if not lease._authorization_consumed or lease._physical_committed:
        raise SessionPurgeBusyError(lease.session_id)
    session = lease._session_state
    lease._physical_committed = True
    session.cleanup_targets = lease.cleanup_targets
    session.cleanup_pending = True
    session.physical_existed = lease._physical_existed


def finish_session_cleanup(lease: StoreSessionPurgeLease) -> None:
    _assert_active_lease(lease)
    session = lease._session_state
    if not session.cleanup_pending:
        raise SessionPurgeBusyError(lease.session_id)
    session.cleanup_targets = ()
    session.cleanup_pending = False
    session.physical_existed = False


def supports_coordinated_session_purge(
    store: EventStore,
) -> TypeGuard[CoordinatedPurgeableEventStore]:
    return callable(getattr(store, "_purge_session_authorized", None))


def supports_authorized_listener_teardown(
    store: EventStore,
) -> TypeGuard[AuthorizedListenerTeardownStore]:
    return callable(getattr(store, "_detach_listeners_authorized", None))
