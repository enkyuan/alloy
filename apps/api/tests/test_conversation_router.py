from app.services.pipeline.conversation_router import conversation_router


def test_decide_routes_explicit_command_to_parser():
    decision = conversation_router.decide("please play bohemian rhapsody by queen")

    assert decision.should_parse_as_command is True


def test_decide_routes_wake_word_command_to_parser():
    decision = conversation_router.decide("hey milo, play bohemian rhapsody")

    assert decision.should_parse_as_command is True


def test_decide_routes_casual_conversation_to_chat():
    decision = conversation_router.decide("hello, how are you today?")

    assert decision.should_parse_as_command is False


def test_decide_avoids_implicit_play_word_false_positive():
    decision = conversation_router.decide("I like to play songs when I code")

    assert decision.should_parse_as_command is False
