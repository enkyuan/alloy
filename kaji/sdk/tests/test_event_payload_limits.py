from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Literal, cast

import pytest
from pydantic import ValidationError

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.infra.events.replay import replay_session
from kaji.infra.events.schemas import (
    BaseEvent,
    EventType,
    MAX_DURABLE_TOOL_ARGUMENT_BYTES,
    StoredKajiEvent,
    ToolApprovalRequested,
    ToolCallRequested,
    durable_tool_arguments_size,
    require_stored_event,
    validate_event_json,
    validate_event_python,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.store.base import EventStore
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.errors import ToolArgumentValidationError
from kaji.runtime.tools.registry import ToolSpec


def _arguments_of_size(
    size: int, *, marker: str = "", multibyte: bool = False
) -> dict[str, str]:
    empty_size = len(json.dumps({"value": ""}, separators=(",", ":")).encode())
    remaining = size - empty_size - len(marker.encode())
    if multibyte:
        value = marker + "😀" * (remaining // 4) + "x" * (remaining % 4)
    else:
        value = marker + "x" * remaining
    return {"value": value}


@pytest.mark.parametrize(
    "event_type,extra",
    [
        (ToolCallRequested, {}),
        (ToolApprovalRequested, {"risk": "write"}),
    ],
)
@pytest.mark.parametrize("size", [64 * 1024 - 1, 64 * 1024])
@pytest.mark.parametrize("multibyte", [False, True])
def test_durable_tool_arguments_accept_up_to_64_kib(
    event_type: type, extra: dict, size: int, multibyte: bool
) -> None:
    event = event_type(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args=_arguments_of_size(size, multibyte=multibyte),
        **extra,
    )

    serialized = json.dumps(
        event.tool_args, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert len(serialized) == size


@pytest.mark.parametrize(
    "event_type,extra",
    [
        (ToolCallRequested, {}),
        (ToolApprovalRequested, {"risk": "write"}),
    ],
)
@pytest.mark.parametrize("multibyte", [False, True])
def test_durable_tool_arguments_reject_oversize_without_echoing_payload(
    event_type: type, extra: dict, multibyte: bool
) -> None:
    secret = "sk-release-payload-secret"
    with pytest.raises(ValueError) as captured:
        event_type(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            tool_args=_arguments_of_size(
                MAX_DURABLE_TOOL_ARGUMENT_BYTES + 1,
                marker=secret,
                multibyte=multibyte,
            ),
            **extra,
        )

    message = str(captured.value)
    assert "65536 serialized bytes" in message
    assert secret not in message


@pytest.mark.parametrize("encoding", ["python", "json"])
def test_closed_event_validation_helpers_redact_oversized_tool_arguments(
    encoding: str,
) -> None:
    secret = f"sk-{encoding}-event-helper-secret"
    payload = {
        "type": EventType.TOOL_CALL_REQUESTED,
        "session_id": "session",
        "turn_id": "turn",
        "tool_name": "tool",
        "tool_call_id": "call",
        "tool_args": _arguments_of_size(
            MAX_DURABLE_TOOL_ARGUMENT_BYTES + 1,
            marker=secret,
        ),
        "sequence": 1,
    }
    if encoding == "json":
        with pytest.raises(ValidationError) as captured:
            validate_event_json(json.dumps(payload))
    else:
        with pytest.raises(ValidationError) as captured:
            validate_event_python(payload)

    message = str(captured.value)
    assert secret not in message
    assert len(message) < 2_000


def test_durable_tool_argument_size_uses_shared_number_policy_at_boundary() -> None:
    empty = {"numbers": [1.0, -0.0, 1e-7, 1e20], "value": ""}
    canonical = '{"numbers":[1,0,1e-7,100000000000000000000],"value":""}'
    assert durable_tool_arguments_size(empty) == len(canonical.encode())

    exact = {
        **empty,
        "value": "x" * (MAX_DURABLE_TOOL_ARGUMENT_BYTES - len(canonical.encode())),
    }
    ToolCallRequested(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args=exact,
    )
    with pytest.raises(ValueError, match="65536 serialized bytes"):
        ToolCallRequested(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            tool_args={**exact, "value": exact["value"] + "x"},
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"value": (1, 2)},
        {1: "non-string-key"},
    ],
)
def test_durable_tool_arguments_reject_non_json_values(arguments: dict) -> None:
    with pytest.raises(ValueError) as captured:
        ToolCallRequested(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            tool_args=arguments,
        )
    assert "input_value" not in str(captured.value)


def test_durable_tool_arguments_reject_cycles_without_reflection() -> None:
    arguments: dict[str, object] = {"secret": "sk-cyclic-secret"}
    arguments["cycle"] = arguments
    with pytest.raises(ValueError) as captured:
        ToolCallRequested(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            tool_args=arguments,
        )
    assert "sk-cyclic-secret" not in str(captured.value)


@pytest.mark.parametrize("value", ["\ud800", "\udc00"])
def test_durable_tool_arguments_reject_unpaired_surrogates(value: str) -> None:
    with pytest.raises(ValueError) as captured:
        ToolCallRequested(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            tool_args={"value": value},
        )
    assert "only JSON values" in str(captured.value)


def test_durable_tool_argument_supplementary_character_size_is_utf8_exact() -> None:
    arguments = {"value": "😀"}
    assert durable_tool_arguments_size(arguments) == len(
        '{"value":"😀"}'.encode("utf-8")
    )
    ToolCallRequested(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args=arguments,
    )


@pytest.mark.asyncio
async def test_planner_normalizes_unpaired_surrogate_before_persistence() -> None:
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="read")
    planner = ToolPlanner(
        lambda _invocation: cast(Any, None),
        specs={"tool": spec},
    )
    events: list[object] = []

    async def emit(event: object) -> None:
        events.append(event)

    with pytest.raises(ToolArgumentValidationError, match="only JSON values"):
        await planner.execute_batch(
            "session",
            [
                {
                    "id": "call",
                    "name": "tool",
                    "arguments": {"value": "\ud800"},
                }
            ],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
        )
    assert events == []


@pytest.mark.asyncio
async def test_planner_detaches_arguments_before_event_emission_await() -> None:
    raw_arguments: dict[str, Any] = {"nested": {"value": "before"}}
    executed: list[dict[str, Any]] = []
    emitted: list[Any] = []

    async def executor(invocation: Any) -> dict[str, bool]:
        executed.append(deepcopy(dict(invocation.arguments)))
        return {"ok": True}

    planner = ToolPlanner(
        executor,
        specs={
            "tool": ToolSpec(
                name="tool", description="tool", parameters={}, risk="read"
            )
        },
    )

    async def emit(event: Any) -> None:
        emitted.append(event)
        if event.type == EventType.TOOL_CALL_REQUESTED:
            raw_arguments["nested"]["value"] = "after"
            raw_arguments["oversize"] = "x" * 70_000

    results = await planner.execute_batch(
        "session",
        [{"id": "call", "name": "tool", "arguments": raw_arguments}],
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )

    requested = next(
        event for event in emitted if event.type == EventType.TOOL_CALL_REQUESTED
    )
    expected = {"nested": {"value": "before"}}
    assert requested.tool_args == expected
    assert executed == [expected]
    assert durable_tool_arguments_size(requested.tool_args) < 64 * 1024
    assert results == [{"id": "call", "name": "tool", "result": {"ok": True}}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type,extra",
    [
        (ToolCallRequested, {}),
        (ToolApprovalRequested, {"risk": "write"}),
    ],
)
async def test_store_revalidates_tool_arguments_after_model_mutation(
    event_type: type, extra: dict[str, str]
) -> None:
    secret = "sk-mutated-event-secret"
    event = event_type(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args={},
        **extra,
    )
    event.tool_args["secret"] = secret + "x" * 70_000

    with pytest.raises(ValidationError) as captured:
        await InMemoryEventStore().append(event)

    assert secret not in str(captured.value)


@pytest.mark.asyncio
async def test_bus_revalidates_tool_arguments_after_model_mutation() -> None:
    secret = "sk-mutated-bus-secret"
    event = ToolCallRequested(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args={},
        sequence=1,
    )
    event.tool_args["secret"] = secret + "x" * 70_000

    with pytest.raises(ValidationError) as captured:
        await InMemoryEventBus().publish(require_stored_event(event))

    assert secret not in str(captured.value)


class _ForgedToolCallRequested(BaseEvent):
    type: Literal[EventType.TOOL_CALL_REQUESTED] = EventType.TOOL_CALL_REQUESTED


@pytest.mark.asyncio
async def test_store_rejects_forged_base_event_subclass() -> None:
    forged = _ForgedToolCallRequested(session_id="session", turn_id="turn")

    with pytest.raises(ValidationError):
        await InMemoryEventStore().append(cast(Any, forged))


class _NeverAppendStore:
    def __init__(self) -> None:
        self.append_calls = 0

    async def append(self, _event: object) -> object:
        self.append_calls += 1
        raise AssertionError("journal must validate before calling the store")

    async def get_events(
        self,
        _session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[object]:
        _ = after_sequence, limit
        return []

    async def last_sequence(self, _session_id: str) -> int:
        return 0


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [False, True])
async def test_journals_revalidate_before_custom_store_append(split: bool) -> None:
    event = ToolApprovalRequested(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args={},
        risk="write",
    )
    event.tool_args["value"] = "x" * 70_000
    store = _NeverAppendStore()
    typed_store = cast(EventStore, store)
    journal = (
        SplitEventJournal(typed_store, InMemoryEventBus())
        if split
        else InMemoryEventJournal(typed_store)
    )

    with pytest.raises(ValidationError):
        await journal.commit(event)
    assert store.append_calls == 0


def test_replay_revalidates_mutated_stored_tool_arguments() -> None:
    secret = "sk-mutated-replay-secret"
    event = ToolCallRequested(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        tool_args={},
        sequence=1,
    )
    event.tool_args["secret"] = secret + "x" * 70_000

    with pytest.raises(ValidationError) as captured:
        replay_session([require_stored_event(event)])

    assert secret not in str(captured.value)


def test_replay_rejects_forged_base_event_subclass() -> None:
    forged = _ForgedToolCallRequested(
        session_id="session",
        turn_id="turn",
        sequence=1,
    )

    with pytest.raises(ValidationError):
        replay_session([cast(StoredKajiEvent, forged)])
