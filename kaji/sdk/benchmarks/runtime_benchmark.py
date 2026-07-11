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
from typing import Any

from kaji.infra.events.schemas import AgentMessageCompleted, UserMessage
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents import AgentBuilder, CancellationToken, InMemoryTurnCoordinator
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.providers.types import GenerateResponse, ModelResponseChunk
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.tools.registry import ToolSpec


CASES = ("replay10k", "crossSession100", "sameSession25", "toolBatch100")


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
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return peak / divisor


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


async def _run_sample(case: str, seed: int) -> dict[str, Any]:
    if case == "replay10k":
        return await _replay10k()
    if case == "crossSession100":
        return await _runtime_concurrency(sessions=100, same_session=False, seed=seed)
    if case == "sameSession25":
        return await _runtime_concurrency(sessions=25, same_session=True, seed=seed)
    if case == "toolBatch100":
        return await _tool_batch100(seed)
    raise ValueError(f"unknown benchmark case: {case}")


def _child_sample(case: str, seed: int) -> dict[str, Any]:
    random.seed(seed)
    return asyncio.run(_run_sample(case, seed))


def _spawn_sample(case: str, seed: int) -> dict[str, Any]:
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
    args = parser.parse_args()
    if args.samples < 1 or args.warmups < 0:
        parser.error("--samples must be positive and --warmups non-negative")
    return args


def main() -> int:
    args = _parse_args()
    result = (
        _child_sample(args.case, args.seed)
        if args._sample
        else _run_parent(args.case, args.samples, args.warmups, args.seed)
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
