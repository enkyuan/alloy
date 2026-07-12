#!/usr/bin/env python3
"""Offline Kaji runtime benchmark cases with process-isolated samples."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncGenerator
import json
import os
from pathlib import Path
import random
import resource
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.replay import replay_session
from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    NewKajiEvent,
    UserMessage,
    require_stored_event,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents import (
    AgentBuilder,
    AgentRuntime,
    AgentStrategy,
    CancellationToken,
    InMemoryTurnCoordinator,
)
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.providers.base import (
    ProviderDiagnosticsSink,
    provider_diagnostics_scope,
)
from kaji.runtime.providers.errors import ProviderOutputLimitError
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderResponseLimits,
)
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.tools.registry import ToolSpec


CASES = (
    "replay10k",
    "crossSession100",
    "sameSession25",
    "toolBatch100",
    "context10kIterations5",
    "crossSessionCommit100",
    "streamDeltas10k",
    "toolArgDeltas10k",
)


class _Ids:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.value = 0

    def next(self, scope: Any) -> str:
        self.value += 1
        return f"{scope}-{self.seed}-{self.value}"


class _RuntimeClock:
    def now_wall_seconds(self) -> float:
        return 0.0

    def now_monotonic(self) -> float:
        return time.perf_counter()


def _peak_mib() -> float:
    return _peak_bytes() / (1024 * 1024)


def _peak_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


class _TrackedTimer:
    def __init__(self, scheduler: _TrackingTimerScheduler, handle: Any) -> None:
        self.scheduler = scheduler
        self.handle = handle
        self.cancelled = False

    def cancel(self) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        self.handle.cancel()
        self.scheduler.active.discard(self)


class _TrackingTimerScheduler:
    def __init__(self) -> None:
        self.active: set[_TrackedTimer] = set()

    def call_later(self, delay_seconds: float, callback: Any) -> _TrackedTimer:
        timer: _TrackedTimer

        def run() -> None:
            self.active.discard(timer)
            callback()

        handle = asyncio.get_running_loop().call_later(max(0.0, delay_seconds), run)
        timer = _TrackedTimer(self, handle)
        self.active.add(timer)
        return timer

    @property
    def leak_count(self) -> int:
        return len(self.active)


def _provider_task_leaks() -> int:
    current = asyncio.current_task()
    return sum(task is not current and not task.done() for task in asyncio.all_tasks())


class _GateProvider:
    def __init__(self, target: int) -> None:
        self.target = target
        self.entered = 0
        self.active = 0
        self.max_active = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="ok")

    async def generate_stream(
        self, *_args: Any, **_kwargs: Any
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.entered += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.entered == self.target:
            self.all_entered.set()
        try:
            await self.release.wait()
            yield ModelResponseChunk(delta="ok")
        finally:
            self.active -= 1


class _ToolLoopProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self, *_args: Any, **_kwargs: Any
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        yield ModelResponseChunk(
            tool_calls=[
                {
                    "id": f"call-{self.calls}",
                    "name": "noop",
                    "arguments": {},
                }
            ]
        )


class _StreamProvider:
    def __init__(self, count: int, *, fail: bool = False) -> None:
        self.count = count
        self.fail = fail
        self.response_limits: ProviderResponseLimits | None = None
        self.active_iterators = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        *_args: Any,
        response_limits: ProviderResponseLimits | None = None,
        **_kwargs: Any,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.response_limits = response_limits
        self.active_iterators += 1
        try:
            for _ in range(self.count):
                yield ModelResponseChunk(delta="x")
            if self.fail:
                raise RuntimeError("benchmark provider failure")
        finally:
            self.active_iterators -= 1


def _context_history(seed: int) -> list[NewKajiEvent]:
    session_id = "benchmark-context"
    events: list[NewKajiEvent] = []
    for index in range(5_000):
        events.extend(
            (
                UserMessage(
                    id=f"context-user-{seed}-{index}",
                    timestamp=0,
                    session_id=session_id,
                    content=f"user-{index}",
                ),
                AgentMessageCompleted(
                    id=f"context-agent-{seed}-{index}",
                    timestamp=0,
                    session_id=session_id,
                    content=f"agent-{index}",
                ),
            )
        )
    return events


def _stored_context_history(seed: int) -> list[Any]:
    return [
        require_stored_event(event.model_copy(update={"sequence": sequence}))
        for sequence, event in enumerate(_context_history(seed), 1)
    ]


async def _context_replay_baseline(seed: int) -> dict[str, Any]:
    events = _stored_context_history(seed)
    started = time.perf_counter_ns()
    state = replay_session(events)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    if len(state.messages) != 10_000:
        raise RuntimeError("context replay baseline lost history")
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "peakBytes": _peak_bytes(),
    }


async def _context10k_iterations5(seed: int) -> dict[str, Any]:
    store = InMemoryEventStore(max_events_per_session=10_100)
    events = _stored_context_history(seed)
    # Fixture setup is outside the measured region. Seed the production store's
    # backing log once so the benchmark measures cold replay/index work instead
    # of 10,000 unrelated journal transactions.
    store._events["benchmark-context"] = events
    store._events_by_id.update((event.id, event) for event in events)

    provider = _ToolLoopProvider()
    scheduler = _TrackingTimerScheduler()
    ids = _Ids(seed)

    async def execute(_invocation: Any) -> dict[str, bool]:
        return {"ok": True}

    spec = ToolSpec(
        name="noop",
        description="deterministic benchmark no-op",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )
    runtime = AgentRuntime(
        bus=None,
        store=store,
        provider=provider,
        planner=ToolPlanner(
            execute,
            specs={spec.name: spec},
            id_factory=ids,
            clock=_RuntimeClock(),
        ),
        strategy=AgentStrategy(max_iterations=5),
        tools=[spec],
        default_context=TurnContext(
            principal_id="benchmark",
            request_id="benchmark-request",
            trace_id="benchmark-trace",
            id_factory=ids,
        ),
        id_factory=ids,
        clock=_RuntimeClock(),
        timer_scheduler=scheduler,
    )
    started = time.perf_counter_ns()
    await runtime.run_turn("benchmark-context")
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    await asyncio.sleep(0)
    stats = runtime.context_index_stats("benchmark-context")
    if stats is None:
        raise RuntimeError("context benchmark did not retain index statistics")
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "peakBytes": _peak_bytes(),
        "historyEvents": 10_000,
        "fullHistoryScans": stats.full_cold_builds,
        "providerIterations": provider.calls,
        "coldEvents": stats.cold_events,
        "incrementalEvents": stats.incremental_events,
        "suffixCalls": stats.suffix_calls,
        "copiedPayloadBytes": stats.persistent_copied_payload_bytes,
        "retainedTurns": stats.retained_turns,
        "turnIndexEntries": stats.turn_entries,
        "sentinelEntries": stats.sentinel_entries,
        "totalIndexEntries": stats.total_entries,
        "maxVisitedTurnEntries": stats.max_visited_turn_entries,
        "timerLeaks": scheduler.leak_count,
        "providerTaskLeaks": _provider_task_leaks(),
    }


async def _cross_session_commit100(seed: int) -> dict[str, Any]:
    class BlockingStore(InMemoryEventStore):
        def __init__(self) -> None:
            super().__init__(max_sessions=100)
            self.block_id: str | None = None
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def _insert_reserved(self, draft: NewKajiEvent) -> Any:
            if draft.id == self.block_id:
                self.entered.set()
                await self.release.wait()
            return await super()._insert_reserved(draft)

    store = BlockingStore()
    journal = InMemoryEventJournal(store)
    session_ids = [f"commit-{index}" for index in range(100)]
    for index, session_id in enumerate(session_ids):
        await journal.commit(
            UserMessage(
                id=f"preseed-{seed}-{index}",
                timestamp=0,
                session_id=session_id,
                content="first",
            )
        )

    started = time.perf_counter_ns()
    store.block_id = f"commit-{seed}-0"
    tasks: dict[str, asyncio.Task[Any]] = {
        session_id: asyncio.create_task(
            journal.commit(
                UserMessage(
                    id=f"commit-{seed}-{index}",
                    timestamp=0,
                    session_id=session_id,
                    content="second",
                )
            )
        )
        for index, session_id in enumerate(session_ids)
    }
    await store.entered.wait()
    completed_before_release: set[str] = set()
    for _ in range(10_000):
        completed_before_release.update(
            session_id
            for session_id, task in tasks.items()
            if session_id != session_ids[0] and task.done()
        )
        if len(completed_before_release) >= 2:
            break
        await asyncio.sleep(0)
    else:
        raise RuntimeError("unrelated session commits did not overlap")
    if tasks[session_ids[0]].done():
        raise RuntimeError("blocked session commit escaped its store lane")
    store.release.set()

    stored = await asyncio.gather(*tasks.values())
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    contiguous = 0
    for session_id in session_ids:
        events = await store.get_events(session_id)
        if [event.sequence for event in events] == [1, 2]:
            contiguous += 1
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "sessions": len(session_ids),
        "commits": len(stored),
        "overlappingSessions": len(completed_before_release),
        "contiguousSessions": contiguous,
        "laneEntriesAfter": store.active_session_lane_count,
        "reservationEntriesAfter": store.active_id_reservation_count,
    }


def _completion_count(events: list[Any]) -> int:
    return sum(event.type == EventType.AGENT_MESSAGE_COMPLETED for event in events)


async def _stream_deltas10k(seed: int) -> dict[str, Any]:
    scheduler = _TrackingTimerScheduler()
    success_provider = _StreamProvider(10_000)
    success_store = InMemoryEventStore()
    success_runtime = AgentRuntime(
        bus=None,
        store=success_store,
        provider=success_provider,
        id_factory=_Ids(seed),
        clock=_RuntimeClock(),
        timer_scheduler=scheduler,
    )
    started = time.perf_counter_ns()
    result = await success_runtime.turn("benchmark", session_id="stream-success")
    diagnostics = success_runtime.stream_diagnostics(result.session_id)
    if diagnostics is None or success_provider.response_limits is None:
        raise RuntimeError("stream benchmark did not expose production diagnostics")
    deltas = [
        event.delta
        for event in result.events
        if event.type == EventType.AGENT_MESSAGE_DELTA
    ]
    if "".join(deltas) != result.text or result.text != "x" * 10_000:
        raise RuntimeError("stream benchmark text was not exact")

    failure_provider = _StreamProvider(1, fail=True)
    failure_store = InMemoryEventStore()
    failure_runtime = AgentRuntime(
        bus=None,
        store=failure_store,
        provider=failure_provider,
        id_factory=_Ids(seed + 1),
        clock=_RuntimeClock(),
        timer_scheduler=scheduler,
    )
    try:
        await failure_runtime.turn("benchmark", session_id="stream-failure")
    except RuntimeError as error:
        if str(error) != "benchmark provider failure":
            raise
    else:
        raise RuntimeError("failing benchmark provider unexpectedly succeeded")
    failure_events = await failure_store.get_events("stream-failure")
    await asyncio.sleep(0)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    limits = success_provider.response_limits
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "characters": len(result.text),
        "deltaEvents": len(deltas),
        "inputFragments": diagnostics.input_fragments,
        "deltaJoinOperations": diagnostics.delta_join_operations,
        "responseJoinOperations": diagnostics.response_join_operations,
        "providerTextMaxBytes": limits.text_max_bytes,
        "providerResponseMaxBytes": limits.response_max_bytes,
        "completionEvents": _completion_count(result.events),
        "completionEventsAfterFailure": _completion_count(failure_events),
        "timerLeaks": scheduler.leak_count,
        "providerTaskLeaks": (
            _provider_task_leaks()
            + success_provider.active_iterators
            + failure_provider.active_iterators
        ),
    }


def _split_nonempty(value: str, count: int) -> list[str]:
    width, extra = divmod(len(value), count)
    result: list[str] = []
    cursor = 0
    for index in range(count):
        length = width + (1 if index < extra else 0)
        result.append(value[cursor : cursor + length])
        cursor += length
    if cursor != len(value) or any(not fragment for fragment in result):
        raise RuntimeError("tool argument benchmark produced empty fragments")
    return result


def _openai_tool_chunk(*, call_id: str | None, name: str | None, arguments: str) -> Any:
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason=None,
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=0,
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                ),
            )
        ],
    )


class _OpenAIArgumentStream:
    def __init__(self, fragments: list[str]) -> None:
        self.fragments = fragments
        self.index = 0
        self.completed = False
        self.closed = False

    def __aiter__(self) -> _OpenAIArgumentStream:
        return self

    async def __anext__(self) -> Any:
        if self.index >= len(self.fragments):
            self.completed = True
            raise StopAsyncIteration
        index = self.index
        self.index += 1
        return _openai_tool_chunk(
            call_id="call" if index == 0 else None,
            name="lookup" if index == 0 else None,
            arguments=self.fragments[index],
        )

    async def aclose(self) -> None:
        self.closed = True

    @property
    def leak_count(self) -> int:
        return int(not self.completed and not self.closed)


class _BenchmarkOpenAIProvider(OpenAIProvider):
    def __init__(self, stream: _OpenAIArgumentStream) -> None:
        super().__init__(api_key="benchmark")
        self._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=self._create_stream)
            )
        )
        self.stream = stream
        self.parse_calls = 0

    async def _create_stream(self, **_kwargs: Any) -> _OpenAIArgumentStream:
        return self.stream

    def _finalize_stream_tool_calls(
        self, pending: dict[int, dict[str, Any]], budget: Any = None
    ) -> list[dict[str, Any]]:
        self.parse_calls += 1
        return OpenAIProvider._finalize_stream_tool_calls(pending, budget)


async def _consume_openai(
    provider: _BenchmarkOpenAIProvider,
    diagnostics: ProviderDiagnosticsSink,
) -> list[ModelResponseChunk]:
    with provider_diagnostics_scope(diagnostics):
        return [
            chunk
            async for chunk in provider.generate_stream(
                [], response_limits=ProviderResponseLimits()
            )
        ]


async def _tool_arg_deltas10k() -> dict[str, Any]:
    empty = '{"value":""}'
    exact = '{"value":"' + ("x" * (65_536 - len(empty))) + '"}'
    fragments = _split_nonempty(exact, 10_000)
    exact_stream = _OpenAIArgumentStream(fragments)
    exact_provider = _BenchmarkOpenAIProvider(exact_stream)
    exact_diagnostics = ProviderDiagnosticsSink()
    started = time.perf_counter_ns()
    chunks = await _consume_openai(exact_provider, exact_diagnostics)
    calls = [call for chunk in chunks for call in chunk.tool_calls]
    if calls != [
        {
            "id": "call",
            "name": "lookup",
            "arguments": {"value": "x" * (len(exact) - len(empty))},
        }
    ]:
        raise RuntimeError("tool argument benchmark did not parse the exact payload")

    oversized = '{"value":"' + ("x" * (65_537 - len(empty))) + '"}'
    over_stream = _OpenAIArgumentStream([oversized])
    over_provider = _BenchmarkOpenAIProvider(over_stream)
    over_diagnostics = ProviderDiagnosticsSink()
    rejected_before_parse = False
    try:
        await _consume_openai(over_provider, over_diagnostics)
    except ProviderOutputLimitError as error:
        rejected_before_parse = (
            error.dimension == "tool_arguments"
            and error.limit == 65_536
            and over_provider.parse_calls == 0
        )
    else:
        raise RuntimeError("one-byte-over tool arguments were accepted")
    await asyncio.sleep(0)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    diagnostics = exact_diagnostics.diagnostics
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "argumentBytes": len(exact.encode("utf-8")),
        "responseMaxBytes": ProviderResponseLimits().response_max_bytes,
        "argumentFragments": len(fragments),
        "rawFragments": diagnostics.raw_fragments,
        "fragmentJoins": diagnostics.tool_argument_join_operations,
        "overLimitBytes": len(oversized.encode("utf-8")),
        "overLimitRejectedBeforeParse": rejected_before_parse,
        "iteratorLeaks": exact_stream.leak_count + over_stream.leak_count,
        "parserLeaks": over_provider.parse_calls,
        "providerTaskLeaks": _provider_task_leaks(),
    }


async def _replay10k() -> dict[str, Any]:
    events = []
    session_id = "benchmark-replay"
    for index in range(5_000):
        events.append(
            UserMessage(
                id=f"event-{index * 2}",
                timestamp=0,
                session_id=session_id,
                content=f"user-{index}",
                sequence=index * 2 + 1,
            )
        )
        events.append(
            AgentMessageCompleted(
                id=f"event-{index * 2 + 1}",
                timestamp=0,
                session_id=session_id,
                content=f"agent-{index}",
                sequence=index * 2 + 2,
            )
        )

    projector = SessionProjector(session_id)
    started = time.perf_counter_ns()
    for event in events:
        projector.apply(event)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    if projector.cursor != 10_000 or projector.applied_events != 10_000:
        raise RuntimeError("replay10k did not apply exactly 10,000 events")
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "eventsApplied": projector.applied_events,
        "cursor": projector.cursor,
    }


async def _runtime_concurrency(
    *, sessions: int, same_session: bool, seed: int
) -> dict[str, Any]:
    provider = _GateProvider(target=1 if same_session else sessions)
    coordinator = InMemoryTurnCoordinator()
    ids = _Ids(seed)
    runtime = (
        AgentBuilder()
        .provider(provider)
        .coordinator(coordinator)
        .id_factory(ids)
        .clock(_RuntimeClock())
        .build(store=InMemoryEventStore(max_sessions=max(100, sessions + 1)))
    )
    started = time.perf_counter_ns()
    tasks = [
        asyncio.create_task(
            runtime.turn(
                f"prompt-{index}",
                session_id="shared" if same_session else f"session-{index}",
            )
        )
        for index in range(sessions)
    ]
    await provider.all_entered.wait()
    provider.release.set()
    results = await asyncio.gather(*tasks)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    if coordinator.entry_count or coordinator.waiter_count:
        raise RuntimeError("turn coordinator did not return to steady state")
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "maxActive": provider.max_active,
        "turns": len(results),
        "coordinatorEntries": coordinator.entry_count,
        "coordinatorWaiters": coordinator.waiter_count,
    }


async def _tool_batch100(seed: int) -> dict[str, Any]:
    active = 0
    max_active = 0
    entered = 0
    first_batch_entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(_invocation: Any) -> dict[str, bool]:
        nonlocal active, max_active, entered
        entered += 1
        active += 1
        max_active = max(max_active, active)
        if entered == 4:
            first_batch_entered.set()
        try:
            await release.wait()
            return {"ok": True}
        finally:
            active -= 1

    spec = ToolSpec(
        name="benchmark",
        description="offline benchmark tool",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
        parallel_safe=True,
    )
    planner = ToolPlanner(
        execute,
        specs={spec.name: spec},
        id_factory=_Ids(seed),
        clock=_RuntimeClock(),
    )

    async def emit(_event: Any) -> None:
        return None

    started = time.perf_counter_ns()
    pending = asyncio.create_task(
        planner.execute_batch(
            "benchmark-tools",
            [
                {"id": f"call-{index}", "name": spec.name, "arguments": {}}
                for index in range(100)
            ],
            emit,
            turn_id="benchmark-turn",
            turn_context=TurnContext(
                principal_id="benchmark",
                request_id="benchmark-request",
                trace_id="benchmark-trace",
            ),
            cancellation_token=CancellationToken(),
        )
    )
    await first_batch_entered.wait()
    release.set()
    results = await pending
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    stuck = await planner.controller.drain_tools(0)
    if stuck:
        raise RuntimeError(f"tool controller leaked calls: {stuck}")
    return {
        "durationMs": duration_ms,
        "peakMiB": _peak_mib(),
        "maxActive": max_active,
        "calls": len(results),
        "stuckCalls": len(stuck),
    }


async def _run_sample(
    case: str, seed: int, context_variant: str | None = None
) -> dict[str, Any]:
    if case == "replay10k":
        return await _replay10k()
    if case == "crossSession100":
        return await _runtime_concurrency(sessions=100, same_session=False, seed=seed)
    if case == "sameSession25":
        return await _runtime_concurrency(sessions=25, same_session=True, seed=seed)
    if case == "toolBatch100":
        return await _tool_batch100(seed)
    if case == "context10kIterations5":
        if context_variant == "replay":
            return await _context_replay_baseline(seed)
        return await _context10k_iterations5(seed)
    if case == "crossSessionCommit100":
        return await _cross_session_commit100(seed)
    if case == "streamDeltas10k":
        return await _stream_deltas10k(seed)
    if case == "toolArgDeltas10k":
        return await _tool_arg_deltas10k()
    raise ValueError(f"unknown benchmark case: {case}")


def _child_sample(
    case: str, seed: int, context_variant: str | None = None
) -> dict[str, Any]:
    random.seed(seed)
    return asyncio.run(_run_sample(case, seed, context_variant))


def _spawn_raw_sample(
    case: str, seed: int, context_variant: str | None = None
) -> dict[str, Any]:
    variant_args = (
        [] if context_variant is None else ["--_context-variant", context_variant]
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--case",
            case,
            "--seed",
            str(seed),
            "--_sample",
            "--json",
            *variant_args,
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": str(seed)},
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("benchmark child emitted non-JSON stdout") from error


def _spawn_sample(case: str, seed: int) -> dict[str, Any]:
    if case != "context10kIterations5":
        return _spawn_raw_sample(case, seed)
    replay = _spawn_raw_sample(case, seed, "replay")
    indexed = _spawn_raw_sample(case, seed, "indexed")
    indexed["incrementalRssBytes"] = max(
        0, int(indexed.pop("peakBytes")) - int(replay["peakBytes"])
    )
    return indexed


def _run_parent(case: str, samples: int, warmups: int, seed: int) -> dict[str, Any]:
    for index in range(warmups):
        _spawn_sample(case, seed + index)
    measured = [_spawn_sample(case, seed + warmups + index) for index in range(samples)]
    durations = [float(sample["durationMs"]) for sample in measured]
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "runtime": "python",
        "case": case,
        "samples": samples,
        "warmups": warmups,
        "seed": seed,
        "sampleResults": measured,
        "medianMs": statistics.median(durations),
        "maxPeakMiB": max(float(sample["peakMiB"]) for sample in measured),
    }
    active = [sample.get("maxActive") for sample in measured]
    if all(value is not None for value in active):
        result["maxActive"] = max(int(value) for value in active)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=CASES)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--_sample", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--_context-variant",
        choices=("replay", "indexed"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.samples < 1 or args.warmups < 0:
        parser.error("--samples must be positive and --warmups non-negative")
    return args


def main() -> int:
    args = _parse_args()
    result = (
        _child_sample(args.case, args.seed, args._context_variant)
        if args._sample
        else _run_parent(args.case, args.samples, args.warmups, args.seed)
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
