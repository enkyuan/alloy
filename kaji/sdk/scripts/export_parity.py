#!/usr/bin/env python3
"""Export deterministic Python SDK behavior for the shared parity scenarios."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, AsyncIterator, Mapping, cast

from pydantic import TypeAdapter

from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.replay import ApprovalKey, SessionState, replay_session
from kaji.infra.events.schemas import (
    KajiEvent,
    StoredKajiEvent,
    ToolApprovalApproved,
    require_stored_event,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents.approval import ApprovalDecision, ApprovalRequestContext
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.coordinator import InMemoryTurnCoordinator
from kaji.runtime.agents.limits import TurnExecutionLimits, TurnTimeoutError
from kaji.runtime.agents.runtime import AgentRuntime, TurnResult
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.context import ToolInvocation, TurnContext
from kaji.runtime.determinism import Clock, IdFactory, IdScope, ScheduledCallback
from kaji.runtime.providers.anthropic import AnthropicProvider
from kaji.runtime.providers.errors import ServiceError, normalize_provider_error
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.types import ModelResponseChunk
from kaji.runtime.tools.errors import ToolValidationError
from kaji.runtime.tools.execution import (
    ToolExecutionController,
    ToolExecutionLimits,
    _ToolExecutionFailure,
    _ToolExecutionOutcome,
)
from kaji.runtime.tools.idempotency import (
    InMemoryToolIdempotencyLedger,
    ToolIdempotencyFailure,
)
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolSpec
from kaji.runtime.tools.validation import ToolSchemaValidator


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "kaji" / "contracts"
SCENARIOS_PATH = CONTRACTS / "parity" / "scenarios.json"
EVENT_ADAPTER = TypeAdapter(KajiEvent)
SNAPSHOT_KEYS = (
    "result",
    "events",
    "replay",
    "operation_trace",
    "provider_requests",
    "provider_responses",
)


class QueueIdFactory(IdFactory):
    """Strict per-scope queue: unexpected identifier demand fails the export."""

    def __init__(self, queues: Mapping[str, list[str]]) -> None:
        self._queues = {scope: deque(values) for scope, values in queues.items()}

    def next(self, scope: IdScope) -> str:
        queue = self._queues.get(scope)
        if queue is None or not queue:
            raise RuntimeError(f"deterministic id queue exhausted: {scope}")
        return queue.popleft()


class FixedClock(Clock):
    def __init__(self, *, wall_seconds: float, monotonic: float) -> None:
        self.wall_seconds = float(wall_seconds)
        self.monotonic = float(monotonic)

    def now_wall_seconds(self) -> float:
        return self.wall_seconds

    def now_monotonic(self) -> float:
        return self.monotonic

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds


class DeterministicTimer(ScheduledCallback):
    def __init__(
        self,
        *,
        due: float,
        order: int,
        callback: Callable[[], None],
    ) -> None:
        self.due = due
        self.order = order
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class DeterministicTimerScheduler:
    def __init__(self, clock: FixedClock) -> None:
        self.clock = clock
        self.timers: list[DeterministicTimer] = []
        self._order = 0

    def call_later(
        self, delay_seconds: float, callback: Callable[[], None]
    ) -> DeterministicTimer:
        timer = DeterministicTimer(
            due=self.clock.now_monotonic() + max(0.0, delay_seconds),
            order=self._order,
            callback=callback,
        )
        self._order += 1
        self.timers.append(timer)
        return timer

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)
        while True:
            due = sorted(
                (
                    timer
                    for timer in self.timers
                    if not timer.cancelled and timer.due <= self.clock.now_monotonic()
                ),
                key=lambda timer: (timer.due, timer.order),
            )
            if not due:
                return
            timer = due[0]
            timer.cancelled = True
            timer.callback()


def empty_snapshot() -> dict[str, Any]:
    return {
        "result": {},
        "events": [],
        "replay": {},
        "operation_trace": [],
        "provider_requests": [],
        "provider_responses": [],
    }


def event_wire(event: StoredKajiEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    fields = event.__class__.model_fields
    return {
        key: value
        for key, value in payload.items()
        if value is not None or fields[key].is_required()
    }


def neutral_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for call in calls:
        arguments = deepcopy(call.get("arguments", {}))
        if isinstance(arguments, dict) and "__parse_error" in arguments:
            arguments = {"__parse_error": "invalid JSON"}
        normalized.append(
            {
                "id": call.get("id"),
                "name": call.get("name", ""),
                "arguments": arguments,
            }
        )
    return normalized


def neutral_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": message["role"],
            "content": message.get("content", ""),
        }
        if message.get("name") is not None:
            item["name"] = message["name"]
        if message.get("tool_call_id") is not None:
            item["tool_call_id"] = message["tool_call_id"]
        if message.get("tool_calls") is not None:
            item["tool_calls"] = neutral_tool_calls(message["tool_calls"])
        normalized.append(item)
    return normalized


class ScriptedProvider:
    provider_family = "fixture"

    def __init__(
        self,
        batches: list[dict[str, Any]],
        operation_trace: list[str],
    ) -> None:
        self._batches = deque(deepcopy(batches))
        self.operation_trace = operation_trace
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **_: Any,
    ) -> AsyncIterator[ModelResponseChunk]:
        index = len(self.requests)
        if not self._batches:
            raise RuntimeError("scripted provider response queue exhausted")
        batch = self._batches.popleft()
        self.operation_trace.append(f"provider:start:{index}")
        self.requests.append(
            {
                "messages": neutral_messages(messages),
                "tools": deepcopy(tools),
            }
        )
        response = {
            "content": batch.get("content", ""),
            "tool_calls": neutral_tool_calls(batch.get("tool_calls", [])),
        }
        self.responses.append(response)
        content = response["content"]
        if content:
            yield ModelResponseChunk(delta=content)
        if response["tool_calls"]:
            yield ModelResponseChunk(tool_calls=response["tool_calls"])
        self.operation_trace.append(f"provider:end:{index}")


class DeadlineFixtureProvider:
    provider_family = "fixture"

    def __init__(self, *, stream_first: bool) -> None:
        self.stream_first = stream_first
        self.entered = asyncio.Event()
        self.operation_trace: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **options: Any,
    ) -> AsyncIterator[ModelResponseChunk]:
        index = len(self.requests)
        self.operation_trace.append(f"provider:start:{index}")
        self.requests.append(
            {
                "messages": neutral_messages(messages),
                "tools": deepcopy(tools),
            }
        )
        content = "partial" if self.stream_first else ""
        self.responses.append({"content": content, "tool_calls": []})
        try:
            if content:
                yield ModelResponseChunk(delta=content)
            self.entered.set()
            token = options.get("cancellation_token")
            if token is None:
                raise AssertionError("deadline fixture requires a cancellation token")
            await token.wait()
            token.raise_if_cancelled()
        finally:
            self.operation_trace.append(f"provider:end:{index}")


class FixtureExecutionController(ToolExecutionController):
    """Deterministic lifecycle driver for parity-only timeout/cancel fixtures."""

    def __init__(
        self,
        fixture: str,
        operation_trace: list[str],
        entered: Mapping[str, asyncio.Event],
        released: Mapping[str, asyncio.Event],
        clock: Clock,
    ) -> None:
        super().__init__(
            ToolExecutionLimits(max_parallel=4),
            clock=clock.now_monotonic,
        )
        self.fixture = fixture
        self.operation_trace = operation_trace
        self.entered = entered
        self.released = released

    @staticmethod
    def _failure(
        error: str,
        error_code: str,
        retryable: bool,
        outcome: str,
        cause: BaseException | None = None,
    ) -> _ToolExecutionOutcome:
        return _ToolExecutionOutcome(
            failure=_ToolExecutionFailure(
                error=error,
                error_code=error_code,
                retryable=retryable,
                outcome=cast(Any, outcome),
                cause=cause,
            )
        )

    async def execute(
        self,
        invocation: ToolInvocation,
        spec: ToolSpec,
        executor: Any,
        emit_started: Any,
    ) -> _ToolExecutionOutcome:
        if self.fixture == "queue-timeout":
            return self._failure(
                "Tool execution timed out", "TOOL_TIMEOUT", True, "not_started"
            )
        if self.fixture == "cancellation-before-start":
            return self._failure(
                "Tool execution cancelled", "TOOL_CANCELLED", True, "not_started"
            )

        await emit_started()
        label = invocation.name.removesuffix("_tool")
        self.operation_trace.append(f"tool:start:{label}")
        if label in self.entered:
            self.entered[label].set()
            await self.released[label].wait()
        if self.fixture == "started-timeout":
            self.operation_trace.append(f"tool:end:{label}")
            return self._failure(
                "Tool execution timed out", "TOOL_TIMEOUT", False, "unknown"
            )
        if self.fixture == "cancellation-after-start":
            self.operation_trace.append(f"tool:end:{label}")
            return self._failure(
                "Tool execution cancelled", "TOOL_CANCELLED", False, "unknown"
            )
        try:
            result = await executor(invocation)
        except BaseException as error:
            self.operation_trace.append(f"tool:end:{label}")
            return self._failure(
                "Tool execution failed",
                "TOOL_EXECUTION_FAILED",
                False,
                "unknown",
                error,
            )
        self.operation_trace.append(f"tool:end:{label}")
        return _ToolExecutionOutcome(result=result)


class FixtureApprovalHandler:
    def __init__(self, code: str) -> None:
        self.code = code

    async def request(
        self,
        _call: ToolInvocation,
        _context: ApprovalRequestContext,
    ) -> ApprovalDecision:
        if self.code == "approved":
            return ApprovalDecision(True, "approved")
        return ApprovalDecision(
            False,
            cast(Any, self.code),
            {
                "rejected": "Fixture rejected",
                "timeout": "Fixture timed out",
            }[self.code],
        )


class ExternalRecordedApprovalHandler:
    event_backed = True

    async def request(
        self,
        call: ToolInvocation,
        context: ApprovalRequestContext,
    ) -> ApprovalDecision:
        requested = await context.request()
        stored = await context.journal.commit(
            ToolApprovalApproved(
                session_id=call.context.session_id,
                turn_id=call.context.turn_id,
                tool_name=call.name,
                tool_call_id=call.context.tool_call_id,
                metadata=deepcopy(requested.metadata),
            )
        )
        await context.observe(stored)
        return ApprovalDecision(True, "approved", recorded=True)


def runtime_definition(fixture: str) -> dict[str, Any]:
    final = {"content": "handled", "tool_calls": []}
    one_call = {
        "content": "",
        "tool_calls": [
            {"id": "call-1", "name": "fixture_tool", "arguments": {"value": 1}}
        ],
    }
    if fixture == "text-one-turn":
        return {"batches": [{"content": "hello back", "tool_calls": []}]}
    if fixture == "text-multi-turn":
        return {
            "batches": [
                {"content": "first reply", "tool_calls": []},
                {"content": "second reply", "tool_calls": []},
            ]
        }
    if fixture == "one-tool":
        return {"batches": [one_call, {"content": "tool done", "tool_calls": []}]}
    if fixture in {"parallel-tools-reverse", "sequential-tools"}:
        return {
            "batches": [
                {
                    "content": "",
                    "tool_calls": [
                        {"id": "call-first", "name": "first_tool", "arguments": {}},
                        {"id": "call-second", "name": "second_tool", "arguments": {}},
                    ],
                },
                {"content": "tools done", "tool_calls": []},
            ]
        }
    if fixture == "max-iteration-exhaustion":
        return {
            "batches": [
                one_call,
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-2",
                            "name": "fixture_tool",
                            "arguments": {"value": 2},
                        }
                    ],
                },
            ],
            "max_iterations": 2,
        }
    return {"batches": [one_call, final]}


def controls_for(
    document: dict[str, Any], scenario: dict[str, Any]
) -> tuple[QueueIdFactory, FixedClock]:
    controls = document["controlSets"][scenario["controls"]]
    return (
        QueueIdFactory(controls["ids"]),
        FixedClock(
            wall_seconds=controls["wallSeconds"],
            monotonic=controls["monotonic"],
        ),
    )


TURN_DEADLINE_FIXTURES = {
    "turn-queue-timeout",
    "turn-provider-open-timeout",
    "turn-provider-stream-timeout",
    "turn-cancellation-deadline-tie",
}


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("deterministic parity barrier was not reached")


async def run_turn_deadline(
    document: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any]:
    snapshot = empty_snapshot()
    fixture = scenario["fixture"]
    session_id = scenario["input"]["session_id"]
    id_factory, clock = controls_for(document, scenario)
    scheduler = DeterministicTimerScheduler(clock)
    coordinator = InMemoryTurnCoordinator()
    provider = DeadlineFixtureProvider(
        stream_first=fixture == "turn-provider-stream-timeout"
    )
    store = InMemoryEventStore()
    runtime = AgentRuntime(
        bus=None,
        store=store,
        provider=cast(Any, provider),
        journal=InMemoryEventJournal(store),
        coordinator=coordinator,
        default_context=TurnContext(
            principal_id="parity-principal",
            request_id="request-fixed",
            trace_id="trace-fixed",
        ),
        turn_execution_limits=TurnExecutionLimits(timeout_seconds=1.0),
        id_factory=id_factory,
        clock=clock,
        timer_scheduler=scheduler,
    )
    token = CancellationToken()
    holder: Any = None
    if fixture == "turn-queue-timeout":
        holder = await coordinator.acquire(session_id).__aenter__()

    turn_task = asyncio.create_task(
        runtime.turn(
            scenario["input"]["prompts"][0],
            session_id=session_id,
            cancellation_token=token,
        )
    )
    if fixture == "turn-queue-timeout":
        await _wait_until(lambda: coordinator.waiter_count == 1)
    else:
        await provider.entered.wait()
    if fixture == "turn-cancellation-deadline-tie":
        token.cancel()
    scheduler.advance(1.0)

    try:
        turn = await turn_task
    except TurnTimeoutError as error:
        snapshot["result"] = {
            "error": {
                "code": error.code,
                "phase": error.phase,
                "retryable": error.retryable,
                "outcome": error.outcome,
            }
        }
    else:
        snapshot["result"] = {
            "turns": [
                {
                    "session_id": turn.session_id,
                    "turn_id": turn.turn_id,
                    "text": turn.text,
                }
            ]
        }
    finally:
        if holder is not None:
            await holder.release()

    snapshot["events"] = [
        event_wire(event) for event in await runtime.history(session_id)
    ]
    snapshot["operation_trace"] = provider.operation_trace
    snapshot["provider_requests"] = provider.requests
    snapshot["provider_responses"] = provider.responses
    return snapshot


async def run_runtime(
    document: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any]:
    snapshot = empty_snapshot()
    fixture = scenario["fixture"]
    if fixture in TURN_DEADLINE_FIXTURES:
        return await run_turn_deadline(document, scenario)
    if fixture == "missing-risk":
        try:
            ToolSpec(
                name="fixture_tool",
                description="fixture",
                parameters={"type": "object"},
            )
        except ToolValidationError as error:
            snapshot["result"] = {
                "error": {
                    **error.normalized(),
                    "retryable": error.retryable,
                    "outcome": error.outcome,
                }
            }
            return snapshot
        raise AssertionError("missing-risk fixture unexpectedly constructed")

    id_factory, clock = controls_for(document, scenario)
    operation_trace: list[str] = []
    definition = runtime_definition(fixture)
    provider = ScriptedProvider(definition["batches"], operation_trace)
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    barrier_names = {"first", "second"} if scenario["schedule"] else set()
    entered = {name: asyncio.Event() for name in barrier_names}
    released = {name: asyncio.Event() for name in barrier_names}
    controller = FixtureExecutionController(
        fixture, operation_trace, entered, released, clock
    )

    parallel = fixture == "parallel-tools-reverse"
    tool_names = (
        ["first_tool", "second_tool"]
        if fixture in {"parallel-tools-reverse", "sequential-tools"}
        else ([] if fixture.startswith("text-") else ["fixture_tool"])
    )
    risk = "write" if fixture.startswith("approval-") else "read"
    specs = [
        ToolSpec(
            name=name,
            description="fixture tool",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "additionalProperties": False,
            },
            risk=cast(Any, risk),
            parallel_safe=parallel,
        )
        for name in tool_names
    ]

    async def execute(invocation: ToolInvocation) -> dict[str, Any]:
        if fixture == "executor-error":
            raise RuntimeError("private fixture failure")
        return {"tool": invocation.name, "arguments": dict(invocation.arguments)}

    policy: ToolPolicy | None = None
    approval: Any = None
    if fixture == "policy-deny":
        policy = ToolPolicy(denied={"fixture_tool"})
    elif fixture.startswith("approval-"):
        policy = ToolPolicy(require_approval_for={"write"})
        if fixture == "approval-reject":
            approval = FixtureApprovalHandler("rejected")
        elif fixture == "approval-timeout":
            approval = FixtureApprovalHandler("timeout")
        elif fixture == "approval-external-recorded":
            approval = ExternalRecordedApprovalHandler()

    runtime = AgentRuntime(
        bus=None,
        store=store,
        journal=journal,
        provider=cast(Any, provider),
        tools=specs,
        tool_executor=execute,
        policy=policy,
        approval_handler=approval,
        strategy=AgentStrategy(max_iterations=definition.get("max_iterations", 5)),
        default_context=TurnContext(
            principal_id="parity-principal",
            request_id="request-fixed",
            trace_id="trace-fixed",
        ),
        tool_execution_controller=controller,
        id_factory=id_factory,
        clock=clock,
    )

    async def execute_turns() -> list[TurnResult]:
        return [
            await runtime.turn(prompt, session_id=scenario["input"]["session_id"])
            for prompt in scenario["input"]["prompts"]
        ]

    turns_task = asyncio.create_task(execute_turns())
    for label in scenario["schedule"]:
        await entered[label].wait()
        released[label].set()
    turns = await turns_task
    events = [event_wire(event) for turn in turns for event in turn.events]
    snapshot["result"] = {
        "turns": [
            {
                "session_id": turn.session_id,
                "turn_id": turn.turn_id,
                "text": turn.text,
            }
            for turn in turns
        ]
    }
    snapshot["events"] = events
    snapshot["operation_trace"] = operation_trace
    snapshot["provider_requests"] = provider.requests
    snapshot["provider_responses"] = provider.responses
    return snapshot


def run_tool_schema(scenario: dict[str, Any]) -> dict[str, Any]:
    snapshot = empty_snapshot()
    fixture_path = CONTRACTS / "tools" / scenario["fixtureFile"]
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"]
    case = next(item for item in cases if item["name"] == scenario["fixture"])
    spec = ToolSpec(
        name="fixture_tool",
        description=case["name"],
        parameters=case["schema"],
        risk="read",
    )
    try:
        validator = ToolSchemaValidator({"fixture_tool": spec})
        validator.validate("fixture_tool", case["arguments"])
    except ToolValidationError as error:
        snapshot["result"] = {
            "fixture": case["name"],
            "accepted": False,
            "error": {
                **error.normalized(),
                "retryable": error.retryable,
                "outcome": error.outcome,
            },
        }
    else:
        snapshot["result"] = {"fixture": case["name"], "accepted": True}
    return snapshot


def approval_records(values: Any) -> list[dict[str, str]]:
    records = [
        {
            "turn_id": key.turn_id,
            "tool_call_id": key.tool_call_id,
            "tool_name": key.tool_name,
        }
        for key in values
    ]
    return sorted(
        records,
        key=lambda item: (
            item["turn_id"],
            item["tool_call_id"],
            item["tool_name"],
        ),
    )


def rejected_records(values: Mapping[ApprovalKey, str]) -> list[dict[str, str]]:
    return [
        {**record, "error_code": values[ApprovalKey(**record)]}
        for record in approval_records(values)
    ]


def replay_events() -> list[StoredKajiEvent]:
    raw: list[dict[str, Any]] = [
        {"type": "session.created"},
        {"type": "agent.reasoning.started", "turn_id": "turn-replay"},
        {
            "type": "tool.call.requested",
            "turn_id": "turn-replay",
            "tool_name": "lookup",
            "tool_call_id": "call-ok",
            "tool_args": {"q": "café"},
        },
        {
            "type": "tool.approval.requested",
            "turn_id": "turn-replay",
            "tool_name": "lookup",
            "tool_call_id": "call-ok",
            "tool_args": {"q": "café"},
            "risk": "write",
        },
        {
            "type": "tool.approval.approved",
            "turn_id": "turn-replay",
            "tool_name": "lookup",
            "tool_call_id": "call-ok",
        },
        {
            "type": "tool.call.completed",
            "turn_id": "turn-replay",
            "tool_name": "lookup",
            "tool_call_id": "call-ok",
            "result": {"z": 1, "a": [2]},
        },
        {
            "type": "tool.call.requested",
            "turn_id": "turn-replay",
            "tool_name": "write",
            "tool_call_id": "call-failed",
            "tool_args": {"value": 3},
        },
        {
            "type": "tool.approval.requested",
            "turn_id": "turn-replay",
            "tool_name": "write",
            "tool_call_id": "call-failed",
            "tool_args": {"value": 3},
            "risk": "write",
        },
        {
            "type": "tool.approval.rejected",
            "turn_id": "turn-replay",
            "tool_name": "write",
            "tool_call_id": "call-failed",
            "error_code": "APPROVAL_TIMEOUT",
            "reason": "Fixture timed out",
        },
        {
            "type": "tool.call.failed",
            "turn_id": "turn-replay",
            "tool_name": "write",
            "tool_call_id": "call-failed",
            "error": "Tool approval timed out",
            "error_code": "APPROVAL_TIMEOUT",
            "retryable": True,
            "outcome": "not_started",
        },
    ]
    events: list[StoredKajiEvent] = []
    for index, payload in enumerate(raw, start=1):
        event = EVENT_ADAPTER.validate_python(
            {
                "id": f"replay-event-{index}",
                "version": "1.0",
                "timestamp": 1700000000,
                "session_id": "session-replay",
                "metadata": {},
                "sequence": index,
                **payload,
            }
        )
        events.append(require_stored_event(event))
    return events


def replay_wire(state: SessionState) -> dict[str, Any]:
    return {
        "session_id": state.session_id,
        "is_active": state.is_active,
        "messages": neutral_messages(state.messages),
        "pending_approvals": approval_records(state.pending_approvals),
        "approved_approvals": approval_records(state.approved_approvals),
        "rejected_approvals": rejected_records(state.rejected_approvals),
    }


JSON_REPLAY_RESULTS: dict[str, Any] = {
    "json-boolean": True,
    "json-null": None,
    "json-number": 7.5,
    "json-integral-float": 1.0,
    "json-negative-zero": -0.0,
    "json-exponent-boundaries": [
        1e-6,
        1.25e-7,
        4503599627370495.5,
        -4503599627370495.5,
    ],
    "json-numeric-keys": {"2": "two", "10": "ten"},
    "json-safe-integer-boundary": 9007199254740991,
    "json-unrepresentable-integer": 9007199254740992,
    "json-utf16-keys": {"\ue000": "bmp", "\U00010000": "astral"},
    "json-string": "café",
    "json-array": [1, False, None],
}


def replay_json_events(
    result: Any, *, replay_rejected_value: bool = False
) -> list[StoredKajiEvent]:
    raw = [
        {"type": "session.created"},
        {
            "type": "tool.call.requested",
            "turn_id": "turn-json",
            "tool_name": "fixture",
            "tool_call_id": "call-json",
            "tool_args": {},
        },
        {
            "type": "tool.call.completed",
            "turn_id": "turn-json",
            "tool_name": "fixture",
            "tool_call_id": "call-json",
            "result": None if replay_rejected_value else result,
        },
    ]
    events = [
        require_stored_event(
            EVENT_ADAPTER.validate_python(
                {
                    "id": f"json-event-{index}",
                    "version": "1.0",
                    "timestamp": 1700000000,
                    "session_id": "session-json",
                    "metadata": {},
                    "sequence": index,
                    **payload,
                }
            )
        )
        for index, payload in enumerate(raw, start=1)
    ]
    if replay_rejected_value:
        cast(Any, events[-1]).result = result
    return events


def run_replay(scenario: dict[str, Any]) -> dict[str, Any]:
    snapshot = empty_snapshot()
    fixture = scenario["fixture"]
    events = (
        replay_events()
        if fixture == "approvals-completed-failed"
        else replay_json_events(
            JSON_REPLAY_RESULTS[fixture],
            replay_rejected_value=fixture == "json-unrepresentable-integer",
        )
    )
    if fixture == "json-unrepresentable-integer":
        try:
            replay_session(events)
        except EventSchemaIncompatibleError as error:
            if error.path != "/result":
                raise
        else:
            raise RuntimeError("unrepresentable integer was accepted by replay")
        snapshot["result"] = {
            "event_count": len(events),
            "rejection": "integer_outside_i_json_safe_range",
        }
        return snapshot
    state = replay_session(events)
    snapshot["events"] = [event_wire(event) for event in events]
    snapshot["replay"] = replay_wire(state)
    snapshot["result"] = {
        "event_count": len(events),
        **(
            {"tool_content": state.messages[-1]["content"]}
            if fixture != "approvals-completed-failed"
            else {}
        ),
    }
    return snapshot


class BarrierProvider:
    provider_family = "fixture"

    def __init__(self) -> None:
        self.entered: dict[str, asyncio.Event] = {}
        self.released: dict[str, asyncio.Event] = {}
        self.active = 0
        self.max_active = 0
        self.trace: list[str] = []

    def barrier(self, label: str) -> tuple[asyncio.Event, asyncio.Event]:
        return (
            self.entered.setdefault(label, asyncio.Event()),
            self.released.setdefault(label, asyncio.Event()),
        )

    async def generate_stream(
        self, messages: list[dict[str, Any]], _tools: Any, **_: Any
    ) -> AsyncIterator[ModelResponseChunk]:
        label = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        )
        entered, released = self.barrier(label)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.trace.append(f"provider:start:{label}")
        entered.set()
        await released.wait()
        self.trace.append(f"provider:end:{label}")
        self.active -= 1
        yield ModelResponseChunk(delta=f"reply:{label}")


async def run_concurrency(
    document: dict[str, Any], scenario: dict[str, Any]
) -> dict[str, Any]:
    snapshot = empty_snapshot()
    id_factory, clock = controls_for(document, scenario)
    provider = BarrierProvider()
    store = InMemoryEventStore()
    runtime = AgentRuntime(
        bus=None,
        store=store,
        journal=InMemoryEventJournal(store),
        provider=cast(Any, provider),
        id_factory=id_factory,
        clock=clock,
    )
    if scenario["fixture"] == "same-session-serialized":
        first = asyncio.create_task(runtime.turn("first", session_id="same"))
        await provider.barrier("first")[0].wait()
        second = asyncio.create_task(runtime.turn("second", session_id="same"))
        await asyncio.sleep(0)
        active_before_release = provider.active
        provider.barrier("first")[1].set()
        await provider.barrier("second")[0].wait()
        provider.barrier("second")[1].set()
        results = await asyncio.gather(first, second)
    else:
        turns: dict[str, asyncio.Task[TurnResult]] = {}
        turns["left"] = asyncio.create_task(runtime.turn("left", session_id="left"))
        await provider.barrier("left")[0].wait()
        turns["right"] = asyncio.create_task(runtime.turn("right", session_id="right"))
        await provider.barrier("right")[0].wait()
        active_before_release = provider.active
        for label in scenario["release"]:
            provider.barrier(label)[1].set()
            await turns[label]
        results = await asyncio.gather(turns["left"], turns["right"])
    snapshot["result"] = {
        "active_before_release": active_before_release,
        "max_active": provider.max_active,
        "texts": [result.text for result in results],
    }
    snapshot["events"] = [
        event_wire(event) for result in results for event in result.events
    ]
    snapshot["operation_trace"] = provider.trace
    return snapshot


def response_wire(response: Any) -> dict[str, Any]:
    metrics = response.metrics
    result = {
        "content": response.text,
        "tool_calls": neutral_tool_calls(response.tool_calls),
        "tokens": {
            "input": metrics.prompt_tokens if metrics else 0,
            "output": metrics.completion_tokens if metrics else 0,
        },
    }
    if response.cost_usd is not None:
        result["cost_usd"] = response.cost_usd
    return result


def chunk_wire(chunk: ModelResponseChunk) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": chunk.delta,
        "tool_calls": neutral_tool_calls(chunk.tool_calls),
    }
    if chunk.metrics is not None:
        result["tokens"] = {
            "input": chunk.metrics.prompt_tokens,
            "output": chunk.metrics.completion_tokens,
        }
    if chunk.cost_usd is not None:
        result["cost_usd"] = chunk.cost_usd
    return result


def aggregate_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": "".join(chunk["content"] for chunk in chunks),
        "tool_calls": [
            call for chunk in chunks for call in chunk.get("tool_calls", [])
        ],
    }
    for chunk in chunks:
        if "tokens" in chunk:
            result["tokens"] = chunk["tokens"]
        if "cost_usd" in chunk:
            result["cost_usd"] = chunk["cost_usd"]
    return result


async def run_provider_adapter(scenario: dict[str, Any]) -> dict[str, Any]:
    # Adapter fixtures are intentionally self-contained and never construct a
    # vendor client. Each provider receives a fake object through its lazy seam.
    if scenario["provider"] == "openai":
        return await run_openai_adapter(scenario["mode"])
    return await run_anthropic_adapter(scenario["mode"])


async def run_openai_adapter(mode: str) -> dict[str, Any]:
    snapshot = empty_snapshot()
    captured: list[dict[str, Any]] = []
    provider = object.__new__(OpenAIProvider)
    provider.api_key = "fixture"
    provider.model_name = "gpt-5.4-mini"
    provider.base_url = None
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "lookup"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "prior-call", "name": "lookup", "arguments": {"q": "old"}}
            ],
        },
        {
            "role": "tool",
            "name": "lookup",
            "content": '{"ok":true}',
            "tool_call_id": "prior-call",
        },
    ]
    tools = [
        {"name": "lookup", "description": "Lookup", "parameters": {"type": "object"}}
    ]

    if mode == "non-stream":
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="provider text",
                        tool_calls=[
                            SimpleNamespace(
                                id="call-ok",
                                type="function",
                                function=SimpleNamespace(
                                    name="lookup", arguments='{"q":"new"}'
                                ),
                            ),
                            SimpleNamespace(
                                id="call-bad",
                                type="function",
                                function=SimpleNamespace(
                                    name="lookup", arguments='{"q":'
                                ),
                            ),
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )

        async def create(**kwargs: Any) -> Any:
            captured.append(deepcopy(kwargs))
            return response

        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        result = await provider.generate(messages, tools, max_tokens=64)
        snapshot["result"] = response_wire(result)
    else:
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="provider ", tool_calls=[])
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call-ok",
                                    function=SimpleNamespace(
                                        name="lookup", arguments='{"q":'
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=SimpleNamespace(
                                        name=None, arguments='"new"}'
                                    ),
                                ),
                                SimpleNamespace(
                                    index=1,
                                    id="call-bad",
                                    function=SimpleNamespace(
                                        name="lookup", arguments='{"q":'
                                    ),
                                ),
                            ],
                        )
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="text", tool_calls=[])
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=5, completion_tokens=3, total_tokens=8
                ),
            ),
        ]

        class Stream:
            def __aiter__(self) -> AsyncIterator[Any]:
                return self._items()

            async def _items(self) -> AsyncIterator[Any]:
                for item in chunks:
                    yield item

        async def create(**kwargs: Any) -> Any:
            captured.append(deepcopy(kwargs))
            return Stream()

        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        chunks = [
            chunk_wire(chunk)
            async for chunk in provider.generate_stream(messages, tools, max_tokens=64)
        ]
        snapshot["result"] = aggregate_chunks(chunks)

    async def fail_create(**_kwargs: Any) -> Any:
        raise OSError("fixture transport failure")

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail_create))
    )
    try:
        if mode == "non-stream":
            await provider.generate(messages, tools, max_tokens=64)
        else:
            async for _ in provider.generate_stream(messages, tools, max_tokens=64):
                pass
    except ServiceError as error:
        snapshot["result"]["provider_error"] = normalize_provider_error(error)
    else:
        raise AssertionError("OpenAI provider error fixture did not fail")
    snapshot["provider_requests"] = [
        canonical_openai_request(item) for item in captured
    ]
    snapshot["provider_responses"] = [snapshot["result"]]
    return snapshot


def canonical_openai_request(request: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for raw in request["messages"]:
        message = {"role": raw["role"], "content": raw.get("content") or ""}
        if raw.get("name") is not None:
            message["name"] = raw["name"]
        if raw.get("tool_call_id") is not None:
            message["tool_call_id"] = raw["tool_call_id"]
        if raw.get("tool_calls"):
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": json.loads(call["function"]["arguments"]),
                }
                for call in raw["tool_calls"]
            ]
        messages.append(message)
    return {
        "model": request["model"],
        "messages": messages,
        "tools": [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "parameters": tool["function"]["parameters"],
            }
            for tool in request.get("tools", [])
        ],
        "stream": bool(request.get("stream", False)),
    }


async def run_anthropic_adapter(mode: str) -> dict[str, Any]:
    snapshot = empty_snapshot()
    captured: list[dict[str, Any]] = []
    provider = object.__new__(AnthropicProvider)
    provider.api_key = "fixture"
    provider.model_name = "claude-sonnet-4-6"
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "lookup"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "prior-call",
                    "name": "lookup",
                    "arguments": {"q": "old"},
                }
            ],
        },
        {
            "role": "tool",
            "name": "lookup",
            "content": '{"ok":true}',
            "tool_call_id": "prior-call",
        },
    ]
    tools = [
        {"name": "lookup", "description": "Lookup", "parameters": {"type": "object"}}
    ]
    if mode == "non-stream":
        response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="provider text"),
                SimpleNamespace(
                    type="tool_use", id="call-ok", name="lookup", input={"q": "new"}
                ),
            ],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )

        async def create(**kwargs: Any) -> Any:
            captured.append(deepcopy(kwargs))
            return response

        provider._client = SimpleNamespace(messages=SimpleNamespace(create=create))
        result = await provider.generate(messages, tools, max_tokens=64)
        snapshot["result"] = response_wire(result)
    else:
        events = [
            SimpleNamespace(
                type="message_start",
                usage=SimpleNamespace(input_tokens=5, output_tokens=0),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="provider text"),
                usage=None,
            ),
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(
                    type="tool_use", id="call-ok", name="lookup"
                ),
                usage=None,
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"q":'),
                usage=None,
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='"new"}'),
                usage=None,
            ),
            SimpleNamespace(type="content_block_stop", usage=None),
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(
                    type="tool_use", id="call-bad", name="lookup"
                ),
                usage=None,
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"q":'),
                usage=None,
            ),
            SimpleNamespace(type="content_block_stop", usage=None),
            SimpleNamespace(
                type="message_delta", usage=SimpleNamespace(output_tokens=3)
            ),
        ]

        class Stream:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *_: Any) -> None:
                return None

            def __aiter__(self) -> AsyncIterator[Any]:
                return self._items()

            async def _items(self) -> AsyncIterator[Any]:
                for item in events:
                    yield item

        def stream(**kwargs: Any) -> Any:
            captured.append(deepcopy(kwargs))
            return Stream()

        provider._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
        chunks = [
            chunk_wire(chunk)
            async for chunk in provider.generate_stream(messages, tools, max_tokens=64)
        ]
        snapshot["result"] = aggregate_chunks(chunks)

    async def fail_create(**_kwargs: Any) -> Any:
        raise OSError("fixture transport failure")

    def fail_stream(**_kwargs: Any) -> Any:
        raise OSError("fixture transport failure")

    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=fail_create, stream=fail_stream)
    )
    try:
        if mode == "non-stream":
            await provider.generate(messages, tools, max_tokens=64)
        else:
            async for _ in provider.generate_stream(messages, tools, max_tokens=64):
                pass
    except ServiceError as error:
        snapshot["result"]["provider_error"] = normalize_provider_error(error)
    else:
        raise AssertionError("Anthropic provider error fixture did not fail")
    snapshot["provider_requests"] = [
        canonical_anthropic_request(item, stream=mode == "stream") for item in captured
    ]
    snapshot["provider_responses"] = [snapshot["result"]]
    return snapshot


def canonical_anthropic_request(
    request: dict[str, Any], *, stream: bool
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for raw in request["messages"]:
        content = raw.get("content", "")
        if isinstance(content, list):
            tool_results = [
                block for block in content if block["type"] == "tool_result"
            ]
            tool_uses = [block for block in content if block["type"] == "tool_use"]
            text = "".join(
                block.get("text", "") for block in content if block["type"] == "text"
            )
            if tool_results:
                for block in tool_results:
                    messages.append(
                        {
                            "role": "tool",
                            "content": block["content"],
                            "tool_call_id": block["tool_use_id"],
                        }
                    )
                continue
            item: dict[str, Any] = {"role": raw["role"], "content": text}
            if tool_uses:
                item["tool_calls"] = [
                    {
                        "id": block["id"],
                        "name": block["name"],
                        "arguments": deepcopy(block.get("input", {})),
                    }
                    for block in tool_uses
                ]
            messages.append(item)
            continue
        messages.append({"role": raw["role"], "content": content})
    return {
        "model": request["model"],
        "system": request.get("system", ""),
        "messages": messages,
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
            for tool in request.get("tools", [])
        ],
        "stream": stream,
    }


def assert_json_value(value: Any, path: str = "") -> None:
    value_type = type(value)
    if value is None or value_type in {bool, int, float, str}:
        if value_type is float and not (-float("inf") < value < float("inf")):
            raise TypeError(f"non-finite number at {path or '/'}")
        return
    if value_type is list:
        for index, item in enumerate(value):
            assert_json_value(item, f"{path}/{index}")
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"non-string object key at {path or '/'}")
            assert_json_value(item, f"{path}/{key}")
        return
    raise TypeError(f"non-JSON value {value_type.__name__} at {path or '/'}")


async def run_idempotency(scenario: dict[str, Any]) -> dict[str, Any]:
    ledger = InMemoryToolIdempotencyLedger(clock=lambda: 1.0)
    claim_kinds: list[str] = []
    handler_count = 1
    first = await ledger.claim(
        session_id="idempotency-session",
        tool_call_id="call",
        tool_name="integration",
        tool_args={},
    )
    if first.kind != "owner":
        raise AssertionError("first idempotency claim must own")
    claim_kinds.append(first.kind)
    failure: ToolIdempotencyFailure | None = None
    result: Any | None = None
    if scenario["fixture"] == "completed":
        result = {"ok": True}
        await ledger.complete(first, result)
    else:
        retryable = scenario["fixture"] == "transient-failed"
        outcome = "unknown" if scenario["fixture"] == "unknown" else "failed"
        failure = ToolIdempotencyFailure(
            error="Tool execution failed",
            error_code=(
                "TOOL_EXECUTION_FAILED"
                if scenario["fixture"] == "unknown"
                else "INTEGRATION_API_ERROR"
            ),
            retryable=retryable,
            outcome=outcome,
        )
        if outcome == "failed":
            await ledger.retryable_failure(first, failure)
        else:
            await ledger.unknown_outcome(first, failure)
    second = await ledger.claim(
        session_id="idempotency-session",
        tool_call_id="call",
        tool_name="integration",
        tool_args={},
    )
    claim_kinds.append(second.kind)
    if second.kind == "owner":
        handler_count += 1
        assert failure is not None
        await ledger.retryable_failure(second, failure)
    elif second.kind in {"completed", "unknown"}:
        assert second.resolution is not None
        result = second.resolution.result
        failure = second.resolution.failure
    snapshot = empty_snapshot()
    snapshot["result"] = {
        "claim_kinds": claim_kinds,
        "handler_count": handler_count,
        **(
            {"result": result}
            if failure is None
            else {
                "failure": {
                    "error_code": failure.error_code,
                    "retryable": failure.retryable,
                    "outcome": failure.outcome,
                }
            }
        ),
    }
    return snapshot


async def export_parity() -> dict[str, Any]:
    document = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    snapshots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scenario in document["scenarios"]:
        scenario_id = scenario["id"]
        if scenario_id in seen:
            raise ValueError(f"duplicate scenario id: {scenario_id}")
        seen.add(scenario_id)
        kind = scenario["kind"]
        if kind == "runtime":
            snapshot = await run_runtime(document, scenario)
        elif kind == "tool-schema":
            snapshot = run_tool_schema(scenario)
        elif kind == "replay":
            snapshot = run_replay(scenario)
        elif kind == "concurrency":
            snapshot = await run_concurrency(document, scenario)
        elif kind == "provider-adapter":
            snapshot = await run_provider_adapter(scenario)
        elif kind == "idempotency":
            snapshot = await run_idempotency(scenario)
        else:
            raise ValueError(f"unknown scenario kind: {kind}")
        if tuple(snapshot) != SNAPSHOT_KEYS:
            raise AssertionError(f"incomplete snapshot envelope: {scenario_id}")
        snapshots.append({"id": scenario_id, "snapshot": snapshot})
    result = {"version": document["version"], "scenarios": snapshots}
    assert_json_value(result)
    return result


def main() -> int:
    try:
        payload = asyncio.run(export_parity())
        sys.stdout.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
        return 0
    except BaseException as error:
        print(
            f"parity exporter failed: {type(error).__name__}: {error}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
