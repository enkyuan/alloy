from app.services.parser import CommandParser


def test_parser_service_parse_add_to_queue_command():
    parser = CommandParser()
    intent = parser.parse_command("add bohemian rhapsody by queen to queue")

    assert intent.intent == "add_to_queue"
    assert intent.parameters["track"] == "bohemian rhapsody"
    assert intent.parameters["artist"] == "queen"
    assert intent.requires_clarification is False


def test_parser_service_parse_play_track_from_playlist_command():
    parser = CommandParser()
    intent = parser.parse_command("play stargazing from my playlist drive songs")

    assert intent.intent == "play_track_from_playlist"
    assert intent.parameters["track"] == "stargazing"
    assert intent.parameters["playlist"] == "drive songs"
    assert intent.requires_clarification is False


def test_parser_service_parse_command_prefers_n_best_alternative_when_primary_is_noisy():
    parser = CommandParser()
    intent = parser.parse_command(
        "play star gazing from my play list drive songs",
        alternatives=["play stargazing from my playlist drive songs"],
    )

    assert intent.intent == "play_track_from_playlist"
    assert intent.parameters["track"] == "stargazing"
    assert intent.parameters["playlist"] == "drive songs"
    assert intent.requires_clarification is False


def test_parser_service_parse_command_keeps_narrative_phrase_out_of_fast_path():
    parser = CommandParser()
    intent = parser.parse_command("i like to play songs when i code")

    assert intent.intent == "unknown"
    assert intent.requires_clarification is True
    assert intent.parser_meta["command_like"] is False
