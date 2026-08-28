from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
import json
from typing import Any, Literal, Never, cast

import pytest
from pydantic import ValidationError

from kaji.infra.events import json as event_json
from kaji.infra.events import schemas as event_schemas
from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.errors import (
    DurableJsonLimitError,
    EventSchemaIncompatibleError,
    InvalidDurableValueError,
)
from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.runtime.sessions.replay import replay_session
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


DURABLE_SUBJECTS = {
    "tool_result",
    "workflow_result",
    "event_metadata",
    "memory_document",
    "pending_tool_call",
    "event",
}


def _durable_snapshot(value: object, *, subject: str, max_bytes: int) -> object:
    snapshot = getattr(event_json, "durable_json_snapshot")
    return snapshot(value, subject=subject, max_bytes=max_bytes)


def _hostile_container(kind: Literal["dict", "list"], calls: list[str]) -> object:
    def hostile(name: str) -> Never:
        calls.append(name)
        raise AssertionError(f"hostile container hook called: {name}")

    if kind == "dict":

        class HostileDict(dict[str, object]):
            def __iter__(self) -> Iterator[str]:
                hostile("__iter__")

            def __getattribute__(self, name: str) -> Any:
                hostile(f"__getattribute__:{name}")

        return HostileDict({"safe": True})

    class HostileList(list[object]):
        def __iter__(self) -> Iterator[object]:
            hostile("__iter__")

        def __getattribute__(self, name: str) -> Any:
            hostile(f"__getattribute__:{name}")

    return HostileList([True])


def test_durable_json_snapshot_detaches_and_normalizes() -> None:
    source = {"nested": [{"value": -0.0}], "text": "before"}

    snapshot = _durable_snapshot(source, subject="event", max_bytes=1_024)
    source["nested"][0]["value"] = 1  # type: ignore[index]
    source["text"] = "after"

    assert snapshot == {"nested": [{"value": 0}], "text": "before"}
    assert snapshot is not source


@pytest.mark.parametrize("kind", ["dict", "list"])
def test_canonical_json_rejects_container_subclasses_without_calling_hooks(
    kind: Literal["dict", "list"],
) -> None:
    calls: list[str] = []
    value = _hostile_container(kind, calls)

    with pytest.raises(TypeError, match="non-JSON value"):
        event_json.canonical_json(value, subject="event")

    assert calls == []


@pytest.mark.parametrize(
    "bad",
    [
        object(),
        {"nested": object()},
        float("nan"),
        float("inf"),
        2**53,
        "\ud800",
    ],
)
def test_durable_json_snapshot_rejects_invalid_values_without_reflection(
    bad: object,
) -> None:
    secret = "sk-durable-snapshot-secret"

    with pytest.raises(InvalidDurableValueError) as captured:
        _durable_snapshot(
            {"secret": secret, "bad": bad},
            subject="tool_result",
            max_bytes=64 * 1024,
        )

    assert captured.value.code == "INVALID_DURABLE_VALUE"
    assert captured.value.subject == "tool_result"
    assert captured.value.subject in DURABLE_SUBJECTS
    assert secret not in str(captured.value)


def test_durable_json_snapshot_rejects_cycles_without_reflection() -> None:
    value: dict[str, object] = {"secret": "sk-durable-cycle-secret"}
    value["cycle"] = value

    with pytest.raises(InvalidDurableValueError) as captured:
        _durable_snapshot(value, subject="event", max_bytes=1_024)

    assert captured.value.code == "INVALID_DURABLE_VALUE"
    assert captured.value.subject == "event"
    assert "sk-durable-cycle-secret" not in str(captured.value)


@pytest.mark.parametrize("multibyte", [False, True])
def test_durable_json_snapshot_uses_exact_utf8_limit(multibyte: bool) -> None:
    max_bytes = 256
    empty_size = len('{"value":""}'.encode())
    remaining = max_bytes - empty_size
    value = (
        "😀" * (remaining // 4) + "x" * (remaining % 4)
        if multibyte
        else "x" * remaining
    )

    exact = _durable_snapshot(
        {"value": value}, subject="workflow_result", max_bytes=max_bytes
    )
    assert exact == {"value": value}

    with pytest.raises(DurableJsonLimitError) as captured:
        _durable_snapshot(
            {"value": value + "x"},
            subject="workflow_result",
            max_bytes=max_bytes,
        )
    assert captured.value.code == "EVENT_PAYLOAD_TOO_LARGE"
    assert captured.value.subject == "workflow_result"
    assert captured.value.max_bytes == max_bytes


def test_durable_json_snapshot_rejects_unknown_subject() -> None:
    with pytest.raises(ValueError, match="durable JSON subject"):
        _durable_snapshot({}, subject="not_closed", max_bytes=1)


def _json_value_of_size(size: int, *, multibyte: bool) -> dict[str, str]:
    empty_size = len('{"value":""}'.encode())
    remaining = size - empty_size
    return {
        "value": (
            "😀" * (remaining // 4) + "x" * (remaining % 4)
            if multibyte
            else "x" * remaining
        )
    }


@pytest.mark.parametrize("multibyte", [False, True])
def test_durable_tool_result_uses_exact_utf8_cap(multibyte: bool) -> None:
    max_bytes = getattr(event_schemas, "MAX_DURABLE_TOOL_RESULT_BYTES")
    assert max_bytes == 65_536
    base = {
        "id": "tool-result",
        "version": "1.0",
        "timestamp": 1.0,
        "type": EventType.TOOL_CALL_COMPLETED,
        "session_id": "session",
        "turn_id": "turn",
        "tool_name": "tool",
        "tool_call_id": "call",
        "metadata": {},
    }

    event_schemas.revalidate_new_event(
        {**base, "result": _json_value_of_size(max_bytes, multibyte=multibyte)}
    )
    with pytest.raises(DurableJsonLimitError) as captured:
        event_schemas.revalidate_new_event(
            {
                **base,
                "result": _json_value_of_size(max_bytes + 1, multibyte=multibyte),
            }
        )
    assert captured.value.subject == "tool_result"


@pytest.mark.parametrize("multibyte", [False, True])
def test_whole_durable_event_uses_exact_utf8_cap(multibyte: bool) -> None:
    max_bytes = getattr(event_schemas, "MAX_DURABLE_EVENT_BYTES")
    assert max_bytes == 1_048_576
    base = {
        "id": "whole-event",
        "version": "1.0",
        "timestamp": 1.0,
        "type": EventType.USER_MESSAGE,
        "session_id": "session",
        "content": "",
        "metadata": {},
    }
    base_bytes = len(event_json.canonical_json(base).encode())
    remaining = max_bytes - base_bytes
    content = (
        "😀" * (remaining // 4) + "x" * (remaining % 4)
        if multibyte
        else "x" * remaining
    )
    exact = {**base, "content": content}
    assert len(event_json.canonical_json(exact).encode()) == max_bytes

    event_schemas.revalidate_new_event(exact)
    with pytest.raises(DurableJsonLimitError) as captured:
        event_schemas.revalidate_new_event({**base, "content": content + "x"})
    assert captured.value.subject == "event"


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
        "id": "event",
        "type": EventType.TOOL_CALL_REQUESTED,
        "version": "1.0",
        "timestamp": 1.0,
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
        with pytest.raises(EventSchemaIncompatibleError) as captured:
            validate_event_json(json.dumps(payload))
        assert captured.value.path == "/tool_args"
    else:
        with pytest.raises(ValidationError) as captured:
            validate_event_python(payload)

    message = str(captured.value)
    assert secret not in message
    assert len(message) < 2_000


def test_durable_tool_argument_size_uses_shared_number_policy_at_boundary() -> None:
    empty = {"numbers": [1.0, -0.0, 1.25e-7, 4503599627370495.5], "value": ""}
    canonical = '{"numbers":[1,0,1.25e-7,4503599627370495.5],"value":""}'
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

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        await InMemoryEventStore().append(event)

    assert captured.value.path == "/tool_args"
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

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        await InMemoryEventBus().publish(require_stored_event(event))

    assert captured.value.path == "/tool_args"
    assert secret not in str(captured.value)


class _ForgedToolCallRequested(BaseEvent):
    type: Literal[EventType.TOOL_CALL_REQUESTED] = EventType.TOOL_CALL_REQUESTED


@pytest.mark.asyncio
async def test_store_rejects_forged_base_event_subclass() -> None:
    forged = _ForgedToolCallRequested(session_id="session", turn_id="turn")

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        await InMemoryEventStore().append(cast(Any, forged))
    assert captured.value.path == "/tool_name"


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

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        await journal.commit(event)
    assert captured.value.path == "/tool_args"
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

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        replay_session([require_stored_event(event)])

    assert captured.value.path == "/tool_args"
    assert secret not in str(captured.value)


def test_replay_rejects_forged_base_event_subclass() -> None:
    forged = _ForgedToolCallRequested(
        session_id="session",
        turn_id="turn",
        sequence=1,
    )

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        replay_session([cast(StoredKajiEvent, forged)])
    assert captured.value.path == "/tool_name"
