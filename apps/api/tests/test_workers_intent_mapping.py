from app.services.parser import CommandIntent
from app.workers.helpers.intent_mapping import map_intent_to_tool_call


def test_workers_intent_mapping_play_track_preserves_track_query_with_artist() -> None:
    intent = CommandIntent(
        intent="play_track",
        parameters={"track": "Thunderstruck", "artist": "AC/DC"},
        confidence=0.92,
        requires_clarification=False,
        raw_text="play thunderstruck by ac dc",
    )

    mapped = map_intent_to_tool_call(intent)

    assert mapped is not None
    tool_name, tool_args = mapped
    assert tool_name == "spotify.play"
    assert tool_args["query"] == "Thunderstruck"
    assert tool_args["artist"] == "AC/DC"


def test_workers_intent_mapping_play_track_without_artist_uses_track_only() -> None:
    intent = CommandIntent(
        intent="play_track",
        parameters={"track": "Numb"},
        confidence=0.88,
        requires_clarification=False,
        raw_text="play numb",
    )

    mapped = map_intent_to_tool_call(intent)

    assert mapped is not None
    tool_name, tool_args = mapped
    assert tool_name == "spotify.play"
    assert tool_args == {"query": "Numb"}
