import pytest
from pydantic import ValidationError

from kaji.artifacts import artifact, validate_artifact_ref
from kaji.capabilities import capability_result
from kaji.events import ArtifactEmitted, InMemoryEventStore
from kaji.events.schemas import ToolCallCompleted


def test_artifact_accepts_custom_uri_scheme() -> None:
    ref = artifact(
        "refund-1",
        "ryo/refund",
        "ryo+test://refunds/1",
        metadata={"refunded": True},
    )
    assert ref.id == "refund-1"


@pytest.mark.parametrize(
    "value",
    [
        {"id": "", "type": "ryo/refund", "uri": "ryo://refunds/1"},
        {"id": "refund-1", "type": "refund", "uri": "ryo://refunds/1"},
        {"id": "refund-1", "type": "ryo/refund", "uri": "refunds/1"},
    ],
)
def test_artifact_rejects_invalid_required_fields(value: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        validate_artifact_ref(value)


def test_artifact_rejects_invalid_or_oversized_metadata() -> None:
    with pytest.raises(ValidationError):
        artifact("refund-1", "ryo/refund", "ryo://refunds/1", metadata={"bad": object()})
    with pytest.raises(ValidationError):
        artifact(
            "refund-1",
            "ryo/refund",
            "ryo://refunds/1",
            metadata={"text": "x" * (64 * 1024)},
        )


def test_capability_result_artifact_cardinality_and_duplicates() -> None:
    first = artifact("refund-1", "ryo/refund", "ryo://refunds/1")
    second = artifact("refund-2", "ryo/refund", "ryo://refunds/2")
    assert capability_result().artifacts == ()
    assert capability_result({"ok": True}, [first]).artifacts == (first,)
    assert capability_result(artifacts=[first, second]).artifacts == (first, second)
    with pytest.raises(ValueError, match="unique"):
        capability_result(artifacts=[first, first])


@pytest.mark.asyncio
async def test_artifact_event_follows_tool_completion_in_journal() -> None:
    store = InMemoryEventStore()
    completed = await store.append(
        ToolCallCompleted(
            session_id="session-1",
            turn_id="turn-1",
            tool_name="refund",
            tool_call_id="call-1",
            result={"ok": True},
        )
    )
    emitted = await store.append(
        ArtifactEmitted(
            session_id="session-1",
            turn_id="turn-1",
            tool_call_id="call-1",
            artifact=artifact("refund-1", "ryo/refund", "ryo://refunds/1"),
        )
    )
    assert emitted.event.sequence == completed.event.sequence + 1
