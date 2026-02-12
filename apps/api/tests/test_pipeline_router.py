from app.services.pipeline.routers.router import pipeline_router


def test_pipeline_router_decide_routes_explicit_command_to_parser():
    decision = pipeline_router.decide("please play bohemian rhapsody by queen")

    assert decision.should_parse_as_command is True


def test_pipeline_router_decide_routes_wake_word_command_to_parser():
    decision = pipeline_router.decide("hey milo, play bohemian rhapsody")

    assert decision.should_parse_as_command is True


def test_pipeline_router_decide_routes_casual_conversation_to_chat():
    decision = pipeline_router.decide("hello, how are you today?")

    assert decision.should_parse_as_command is False


def test_pipeline_router_decide_avoids_implicit_play_word_false_positive():
    decision = pipeline_router.decide("I like to play songs when I code")

    assert decision.should_parse_as_command is False
