from sdk.agents.context import ContextBuilder
from sdk.agents.prompts import SystemPrompt
from sdk.events.replay import SessionState


def test_context_builder_includes_system_prompt_and_history():
    state = SessionState(
        session_id="s1",
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
    )
    prompt = SystemPrompt("You are AgentKit.")
    messages = ContextBuilder.build_messages(state, prompt, variables={"name": "Ada"})

    assert messages[0]["role"] == "system"
    assert "AgentKit" in messages[0]["content"]
    assert messages[1]["content"] == "hello"
    assert messages[2]["content"] == "hi there"
