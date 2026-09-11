"""In-memory journal-backed task handles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kaji.core.determinism import IdFactory, SYSTEM_ID_FACTORY
from kaji.events import InMemoryEventJournal, InMemoryEventStore
from kaji.events.protocols import EventJournal
from kaji.events.schemas import (
    NewKajiEvent,
    TaskCancelled,
    TaskCreated,
    TaskResumed,
    StoredKajiEvent,
    ToolApprovalApproved,
    ToolApprovalRejected,
)
from kaji.events.store import EventStore
from kaji.runtime.agents.coordinator import (
    TurnCoordinator,
    default_coordinator_for_store,
)
from kaji.runtime.tools.idempotency import (
    InMemoryToolIdempotencyLedger,
    ToolIdempotencyLedger,
)

from .errors import TaskNotFoundError
from .projector import approval_id, project_task
from .types import PendingApproval, TaskSnapshot


@dataclass(slots=True)
class InMemoryBackend:
    """Minimal composition root for the task prototype."""

    store: EventStore
    journal: EventJournal
    coordinator: TurnCoordinator
    idempotency_ledger: ToolIdempotencyLedger = field(
        default_factory=InMemoryToolIdempotencyLedger
    )
    task_sessions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls) -> InMemoryBackend:
        store = InMemoryEventStore()
        return cls(
            store, InMemoryEventJournal(store), default_coordinator_for_store(store)
        )


class TaskRuntime:
    """Creates and finds task handles; snapshots always replay the journal."""

    def __init__(
        self, backend: InMemoryBackend, *, ids: IdFactory = SYSTEM_ID_FACTORY
    ) -> None:
        self._backend = backend
        self._ids = ids

    @classmethod
    def for_in_memory(cls, *, ids: IdFactory = SYSTEM_ID_FACTORY) -> TaskRuntime:
        return cls(InMemoryBackend.create(), ids=ids)

    async def start(
        self,
        *,
        session_id: str,
        principal_id: str,
        input: str,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> TaskHandle:
        identifier = task_id or self._ids.next("task")
        if identifier in self._backend.task_sessions:
            raise ValueError(f"task already exists: {identifier}")
        handle = TaskHandle.for_in_memory(
            identifier, session_id, self._backend, self._ids
        )
        async with self._backend.coordinator.acquire(session_id):
            await self._backend.journal.commit(
                TaskCreated(
                    id=self._ids.next("event"),
                    task_id=identifier,
                    session_id=session_id,
                    principal_id=principal_id,
                    input=input,
                    metadata=metadata or {},
                )
            )
            await self._backend.journal.commit(
                TaskResumed(
                    id=self._ids.next("event"),
                    task_id=identifier,
                    session_id=session_id,
                )
            )
            self._backend.task_sessions[identifier] = session_id
        return handle

    def get(self, task_id: str) -> TaskHandle:
        try:
            session_id = self._backend.task_sessions[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        return TaskHandle.for_in_memory(task_id, session_id, self._backend, self._ids)


class TaskHandle:
    """A narrow task control surface over one session journal."""

    def __init__(
        self, task_id: str, session_id: str, backend: InMemoryBackend, ids: IdFactory
    ) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self._backend = backend
        self._ids = ids

    @classmethod
    def for_in_memory(
        cls,
        task_id: str,
        session_id: str,
        backend: InMemoryBackend,
        ids: IdFactory = SYSTEM_ID_FACTORY,
    ) -> TaskHandle:
        return cls(task_id, session_id, backend, ids)

    async def events(self, *, after_sequence: int = 0) -> tuple[StoredKajiEvent, ...]:
        return tuple(
            await self._backend.store.get_events(
                self.session_id, after_sequence=after_sequence
            )
        )

    async def snapshot(self) -> TaskSnapshot:
        return project_task(self.task_id, await self.events())

    async def pending_approvals(self) -> tuple[PendingApproval, ...]:
        events = await self.events()
        snapshot = project_task(self.task_id, events)
        by_id: dict[str, PendingApproval] = {}
        from .types import PendingApproval as FullApproval

        for event in events:
            if event.type.value == "tool.approval.requested":
                by_id[approval_id(event)] = FullApproval(
                    id=approval_id(event),
                    capability=event.tool_name,
                    risk=event.risk,
                    arguments=dict(event.tool_args),
                )
        return tuple(by_id[item.id] for item in snapshot.pending_approvals)

    async def cancel(self) -> TaskSnapshot:
        return await self._append(
            TaskCancelled(
                id=self._ids.next("event"),
                task_id=self.task_id,
                session_id=self.session_id,
            )
        )

    async def resume(self) -> TaskSnapshot:
        return await self._append(
            TaskResumed(
                id=self._ids.next("event"),
                task_id=self.task_id,
                session_id=self.session_id,
            )
        )

    async def decide_approval(
        self,
        approval: PendingApproval,
        *,
        approved: bool,
        reason: str = "host decision",
    ) -> TaskSnapshot:
        event: NewKajiEvent
        event_id = self._ids.next("event")
        turn_id, tool_call_id = approval.id.split(":", 1)
        if approved:
            event = ToolApprovalApproved(
                id=event_id,
                session_id=self.session_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                tool_name=approval.capability,
            )
        else:
            event = ToolApprovalRejected(
                id=event_id,
                session_id=self.session_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                tool_name=approval.capability,
                error_code="APPROVAL_REJECTED",
                reason=reason,
            )
        # The active EventApprovalHandler holds the session turn lease while it
        # waits, so this canonical decision must not queue behind that lease.
        await self._backend.journal.commit(event)
        return project_task(self.task_id, await self.events())

    async def _append(self, event: NewKajiEvent) -> TaskSnapshot:
        async with self._backend.coordinator.acquire(self.session_id):
            await self._backend.journal.commit(event)
            return project_task(self.task_id, await self.events())
