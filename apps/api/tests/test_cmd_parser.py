from app.services.pipeline.cmd_parser import CommandParser


def test_parse_add_to_queue_command():
    parser = CommandParser()
    intent = parser.parse_command("add bohemian rhapsody by queen to queue")

    assert intent.intent == "add_to_queue"
    assert intent.parameters["track"] == "bohemian rhapsody"
    assert intent.parameters["artist"] == "queen"
    assert intent.requires_clarification is False


def test_parse_play_track_from_playlist_command():
    parser = CommandParser()
    intent = parser.parse_command("play stargazing from my playlist drive songs")

    assert intent.intent == "play_track_from_playlist"
    assert intent.parameters["track"] == "stargazing"
    assert intent.parameters["playlist"] == "drive songs"
    assert intent.requires_clarification is False
