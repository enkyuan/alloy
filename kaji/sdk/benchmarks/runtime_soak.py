#!/usr/bin/env python3
"""Fixed-seed, offline Kaji runtime soak workload."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncGenerator
import gc
import json
import os
from pathlib import Path
import random
import resource
import statistics
import sys
import time
import tracemalloc
from typing import Any

from kaji.infra.events.errors import EventBufferOverflowError
from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.schemas import SessionClosed, UserMessage
from kaji.infra.observability.protocols import Measurement
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents import CancellationToken, InMemoryTurnCoordinator
from kaji.runtime.agents.approval import ApprovalDecision
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.providers.types import GenerateResponse, ModelResponseChunk
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from kaji.runtime.tools.idempotency import InMemoryToolIdempotencyLedger
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolSpec


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


class _Diagnostics:
    def __init__(self) -> None:
        self.max_tool_active = 0
        self.max_subscriber_depth = 0
        self.subscriber_overflows = 0
        self.max_context_messages = 0
        self.max_context_characters = 0

    def record(self, measurement: Measurement) -> None:
        value = int(measurement.value)
        if measurement.name == "kaji.tool.active":
            self.max_tool_active = max(self.max_tool_active, value)
        elif measurement.name == "kaji.subscriber.lag_events":
            self.max_subscriber_depth = max(self.max_subscriber_depth, value)
        elif measurement.name == "kaji.subscriber.overflow":
            self.subscriber_overflows += 1
        elif measurement.name == "kaji.context.messages":
            self.max_context_messages = max(self.max_context_messages, value)
        elif measurement.name == "kaji.context.characters":
            self.max_context_characters = max(self.max_context_characters, value)


def _rss_mib() -> float:
    statm = Path("/proc/self/statm")
    if statm.exists():
        resident_pages = int(statm.read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return peak / divisor


class _SoakProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_ids = 0
        self.active = 0
        self.max_active = 0
        self.max_messages = 0
        self.max_characters = 0
        self.multi_tool_batches = 0
        self.approvals = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="ok")

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        *_args: Any,
        cancellation_token: CancellationToken | None = None,
        **_kwargs: Any,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.max_messages = max(self.max_messages, len(messages))
        self.max_characters = max(
            self.max_characters,
            sum(len(str(message.get("content", ""))) for message in messages),
        )
        try:
            prompt = next(
                (
                    str(message.get("content", ""))
                    for message in reversed(messages)
                    if message.get("role") == "user"
                ),
                "",
            )
            if prompt.startswith("cancel"):
                if cancellation_token is not None:
                    await cancellation_token.wait()
                raise asyncio.CancelledError()
            if (
                prompt.startswith(("tool", "approve"))
                and messages[-1]["role"] == "user"
            ):
                tool_name = "charge" if prompt.startswith("approve") else "batch"
                call_count = 1 if tool_name == "charge" else 3
                if call_count > 1:
                    self.multi_tool_batches += 1
                else:
                    self.approvals += 1
                tool_calls = []
                for _ in range(call_count):
                    self.tool_ids += 1
                    tool_calls.append(
                        {
                            "id": f"soak-call-{self.tool_ids}",
                            "name": tool_name,
                            "arguments": {"value": self.tool_ids},
                        }
                    )
                await asyncio.sleep(0)
                yield ModelResponseChunk(tool_calls=tool_calls)
                return
            await asyncio.sleep(0)
            yield ModelResponseChunk(delta="ok")
        finally:
            self.active -= 1


class _Approve:
    def __init__(self) -> None:
        self.requests = 0

    async def request(self, _call: Any, _context: Any) -> ApprovalDecision:
        self.requests += 1
        return ApprovalDecision(True, "approved")


async def _exercise_noncooperative_timeouts(sequence: int) -> int:
    releases = [asyncio.Event() for _ in range(4)]
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=4, timeout_seconds=0.002)
    )
    spec = ToolSpec(
        name="timeout",
        description="non-cooperative timeout probe",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
        parallel_safe=True,
    )

    async def handler(invocation: Any) -> dict[str, bool]:
        index = int(invocation.context.tool_call_id.rsplit("-", 1)[-1])
        try:
            await releases[index].wait()
        except asyncio.CancelledError:
            await releases[index].wait()
        return {"settled": True}

    planner = ToolPlanner(
        handler,
        specs={spec.name: spec},
        controller=controller,
        id_factory=_Ids(sequence),
        clock=_RuntimeClock(),
    )

    async def emit(_event: Any) -> None:
        return None

    pending = asyncio.create_task(
        planner.execute_batch(
            f"timeout-session-{sequence}",
            [
                {"id": f"timeout-{index}", "name": spec.name, "arguments": {}}
                for index in range(4)
            ],
            emit,
            turn_id=f"timeout-turn-{sequence}",
            turn_context=TurnContext(
                principal_id="soak",
                request_id=f"timeout-request-{sequence}",
                trace_id=f"timeout-trace-{sequence}",
            ),
            cancellation_token=CancellationToken(),
        )
    )
    results = await pending
    unknown = sum(
        result.get("error_code") == "TOOL_TIMEOUT"
        and result.get("outcome") == "unknown"
        for result in results
    )
    for release in releases:
        release.set()
    if await controller.drain_tools(1):
        raise RuntimeError("non-cooperative timeout probe did not drain")
    return unknown


async def _exercise_cooperative_timeout(sequence: int) -> int:
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=0.002)
    )
    spec = ToolSpec(
        name="cooperative-timeout",
        description="cooperative timeout probe",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
        parallel_safe=True,
    )

    async def handler(invocation: Any) -> dict[str, bool]:
        await invocation.context.cancellation_token.wait()
        return {"cancelled": invocation.context.cancellation_token.is_cancelled}

    planner = ToolPlanner(
        handler,
        specs={spec.name: spec},
        controller=controller,
        id_factory=_Ids(sequence + 1),
        clock=_RuntimeClock(),
    )

    async def emit(_event: Any) -> None:
        return None

    results = await planner.execute_batch(
        f"cooperative-timeout-session-{sequence}",
        [{"id": "cooperative-timeout", "name": spec.name, "arguments": {}}],
        emit,
        turn_id=f"cooperative-timeout-turn-{sequence}",
        turn_context=TurnContext(
            principal_id="soak",
            request_id=f"cooperative-timeout-request-{sequence}",
            trace_id=f"cooperative-timeout-trace-{sequence}",
        ),
        cancellation_token=CancellationToken(),
    )
    if await controller.drain_tools(1):
        raise RuntimeError("cooperative timeout probe did not drain")
    return sum(
        result.get("error_code") == "TOOL_TIMEOUT"
        and result.get("outcome") == "unknown"
        for result in results
    )


def _sample_memory(minute: float) -> dict[str, float]:
    gc.collect()
    heap_bytes, _ = tracemalloc.get_traced_memory()
    return {
        "minute": minute,
        "heapMiB": heap_bytes / (1024 * 1024),
        "rssMiB": _rss_mib(),
    }


def _late_growth(samples: list[dict[str, float]]) -> float | None:
    prior = [sample["heapMiB"] for sample in samples if 21 <= sample["minute"] <= 25]
    late = [sample["heapMiB"] for sample in samples if 26 <= sample["minute"] <= 30]
    if not prior or not late:
        return None
    prior_median = statistics.median(prior)
    late_median = statistics.median(late)
    if prior_median == 0:
        return 0.0 if late_median == 0 else float("inf")
    return (late_median - prior_median) / prior_median * 100


async def _run(minutes: float, minimum_turns: int, seed: int) -> dict[str, Any]:
    randomizer = random.Random(seed)
    provider = _SoakProvider()
    diagnostics = _Diagnostics()
    coordinator = InMemoryTurnCoordinator()
    ids = _Ids(seed)
    clock = _RuntimeClock()
    ledger = InMemoryToolIdempotencyLedger()
    controller = ToolExecutionController(ledger=ledger, metrics_sink=diagnostics)
    specs = {
        "batch": ToolSpec(
            name="batch",
            description="offline batch tool",
            parameters={"type": "object", "additionalProperties": True},
            risk="read",
            parallel_safe=True,
        ),
        "charge": ToolSpec(
            name="charge",
            description="offline approval tool",
            parameters={"type": "object", "additionalProperties": True},
            risk="destructive",
        ),
    }

    async def execute(invocation: Any) -> dict[str, Any]:
        return {"value": invocation.arguments.get("value")}

    approval_bridge = _Approve()
    store = InMemoryEventStore(max_sessions=1_000, max_events_per_session=10_000)
    journal = InMemoryEventJournal(
        store, subscriber_queue_capacity=1_024, metrics_sink=diagnostics
    )
    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=approval_bridge,
        specs=specs,
        controller=controller,
        id_factory=ids,
        clock=clock,
    )
    runtime = AgentRuntime(
        bus=None,
        store=store,
        journal=journal,
        provider=provider,
        planner=planner,
        tools=list(specs.values()),
        coordinator=coordinator,
        strategy=AgentStrategy(max_iterations=5),
        default_context=TurnContext(principal_id="soak"),
        id_factory=ids,
        clock=clock,
        metrics_sink=diagnostics,
    )

    attempted = completed = failed = 0
    terminal_outcomes = {"completed": 0, "failed": 0, "cancelled": 0}
    timeout_unknown = 0
    cooperative_timeout_unknown = 0
    batch = 0
    subscriber_generation = 0
    subscriber_session = f"slow-subscriber-{subscriber_generation}"
    subscriber = await journal.open_subscription(subscriber_session)
    subscriber_events = 0
    subscriber_count = 1
    subscriber_resumes = 0
    subscriber_overflows = 0
    samples: list[dict[str, float]] = []
    started = time.monotonic()
    deadline = started + minutes * 60
    next_sample = started + 60
    tracemalloc.start()
    try:
        while time.monotonic() < deadline:
            batch += 1
            shared = f"shared-{batch}"
            session_ids = [shared] * 4 + [
                f"cross-{batch}-{index}" for index in range(12)
            ]
            prompts: list[str] = []
            for index in range(len(session_ids)):
                choice = randomizer.randrange(100)
                prefix = "approve" if choice == 0 else "tool" if choice < 12 else "turn"
                prompts.append(f"{prefix}-{batch}-{index}")
            turns = [
                asyncio.create_task(runtime.turn(prompt, session_id=session_id))
                for prompt, session_id in zip(prompts, session_ids, strict=True)
            ]
            attempted += len(turns)
            outcomes = await asyncio.gather(*turns, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    failed += 1
                    terminal_outcomes["failed"] += 1
                else:
                    completed += 1
                    terminal_outcomes["completed"] += 1

            if batch % 20 == 0:
                token = CancellationToken()
                token.cancel()
                attempted += 1
                try:
                    await runtime.turn(
                        f"cancel-{batch}",
                        session_id=f"cancel-{batch}",
                        cancellation_token=token,
                    )
                except asyncio.CancelledError:
                    failed += 1
                    terminal_outcomes["cancelled"] += 1

            if batch % 250 == 0:
                timeout_unknown += await _exercise_noncooperative_timeouts(batch)
                cooperative_timeout_unknown += await _exercise_cooperative_timeout(
                    batch
                )

            for _ in range(2):
                await runtime.append_event(
                    UserMessage(
                        id=ids.next("event"),
                        timestamp=clock.now_wall_seconds(),
                        session_id=subscriber_session,
                        content=f"subscriber-{subscriber_events + 1}",
                    )
                )
                subscriber_events += 1
                if subscriber_events != 1_025:
                    continue
                try:
                    await anext(subscriber)
                except EventBufferOverflowError as overflow:
                    if overflow.last_sequence != 0 or overflow.latest_sequence != 1_025:
                        raise RuntimeError("subscriber overflow cursor was not exact")
                else:
                    raise RuntimeError("slow subscriber did not overflow at capacity")
                subscriber_count = 0
                replayed = await store.get_events(subscriber_session)
                if [event.sequence for event in replayed] != list(range(1, 1_026)):
                    raise RuntimeError("subscriber overflow replay was not lossless")
                resumed = await journal.open_subscription(
                    subscriber_session, after_sequence=1_024
                )
                if (await anext(resumed)).sequence != 1_025:
                    raise RuntimeError("subscriber did not resume from its cursor")
                await resumed.aclose()
                subscriber_resumes += 1
                subscriber_overflows += 1
                await runtime.append_event(SessionClosed(session_id=subscriber_session))
                subscriber_generation += 1
                subscriber_session = f"slow-subscriber-{subscriber_generation}"
                subscriber = await journal.open_subscription(subscriber_session)
                subscriber_events = 0
                subscriber_count = 1

            for session_id in set(session_ids):
                await runtime.append_event(SessionClosed(session_id=session_id))

            now = time.monotonic()
            if now >= next_sample:
                samples.append(_sample_memory((now - started) / 60))
                while next_sample <= now:
                    next_sample += 60
    finally:
        elapsed_seconds = time.monotonic() - started
        if not samples or samples[-1]["minute"] < elapsed_seconds / 60:
            samples.append(_sample_memory(elapsed_seconds / 60))
        tracemalloc.stop()

    await subscriber.aclose()
    subscriber_count = 0
    if await store.last_sequence(subscriber_session):
        await runtime.append_event(SessionClosed(session_id=subscriber_session))
    stuck = await controller.drain_tools(0)
    growth = _late_growth(samples)
    internal = {
        "coordinatorEntries": coordinator.entry_count,
        "coordinatorWaiters": coordinator.waiter_count,
        "projectionCacheSize": runtime.projection_cache_size,
        "projectionCacheLimit": store.max_sessions,
        "ledgerSize": ledger.size,
        "ledgerLimit": 10_000,
        "stuckToolCalls": len(stuck),
        "subscriberCount": subscriber_count,
        "maxSubscriberQueueDepth": diagnostics.max_subscriber_depth,
        "subscriberOverflows": subscriber_overflows,
        "subscriberResumes": subscriber_resumes,
        "maxToolActive": diagnostics.max_tool_active,
        "maxContextMessages": diagnostics.max_context_messages,
        "maxContextCharacters": diagnostics.max_context_characters,
    }
    bounds_ok = (
        internal["coordinatorEntries"] == 0
        and internal["coordinatorWaiters"] == 0
        and internal["projectionCacheSize"] <= internal["projectionCacheLimit"]
        and internal["ledgerSize"] <= internal["ledgerLimit"]
        and internal["stuckToolCalls"] == 0
        and internal["subscriberCount"] == 0
        and internal["maxSubscriberQueueDepth"] == 1_024
        and diagnostics.subscriber_overflows == subscriber_overflows
        and internal["maxToolActive"] <= 4
        and internal["maxContextCharacters"] <= 100_000
        and provider.max_messages == internal["maxContextMessages"]
        and provider.max_characters <= internal["maxContextCharacters"]
        and provider.max_characters <= 100_000
        and provider.active == 0
    )
    required_minutes = 30
    required_turns = max(10_000, minimum_turns)
    passed = (
        minutes >= required_minutes
        and elapsed_seconds >= max(minutes, required_minutes) * 60
        and attempted >= required_turns
        and growth is not None
        and growth <= 5
        and bounds_ok
        and provider.multi_tool_batches > 0
        and provider.approvals > 0
        and approval_bridge.requests > 0
        and terminal_outcomes["cancelled"] > 0
        and cooperative_timeout_unknown > 0
        and timeout_unknown > 0
        and subscriber_overflows > 0
        and subscriber_resumes == subscriber_overflows
    )
    return {
        "schemaVersion": 1,
        "runtime": "python",
        "seed": seed,
        "requestedMinutes": minutes,
        "elapsedSeconds": elapsed_seconds,
        "minimumTurns": required_turns,
        "attemptedTurns": attempted,
        "completedTurns": completed,
        "failedTurns": failed,
        "throughputTurnsPerSecond": attempted / elapsed_seconds,
        "terminalOutcomes": terminal_outcomes,
        "noncooperativeTimeouts": timeout_unknown,
        "cooperativeTimeouts": cooperative_timeout_unknown,
        "lateWindowHeapGrowthPercent": growth,
        "memorySamples": samples,
        "provider": {
            "calls": provider.calls,
            "maxActive": provider.max_active,
            "maxMessages": provider.max_messages,
            "maxCharacters": provider.max_characters,
            "multiToolBatches": provider.multi_tool_batches,
            "chargeRequests": provider.approvals,
            "approvalBridgeRequests": approval_bridge.requests,
        },
        "internal": internal,
        "passed": passed,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--minimum-turns", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.minutes <= 0 or args.minimum_turns < 1:
        parser.error("--minutes and --minimum-turns must be positive")
    return args


def main() -> int:
    args = _parse_args()
    result = asyncio.run(_run(args.minutes, args.minimum_turns, args.seed))
    if args.artifacts_dir is not None:
        args.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (args.artifacts_dir / "python-heap-samples.json").write_text(
            json.dumps(result["memorySamples"], indent=2) + "\n"
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
