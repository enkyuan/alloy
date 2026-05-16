from sdk.modalities.text import TextModalityAdapter


def test_text_modality_adapter_create_session():
    adapter = TextModalityAdapter()
    session = adapter.create_session(session_id="sess-1", user_id="user-1")
    assert session == {
        "session_id": "sess-1",
        "user_id": "user-1",
        "modality": "text",
    }
