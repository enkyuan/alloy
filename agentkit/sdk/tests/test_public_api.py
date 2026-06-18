import agentkit


def test_public_api_exports_stable_runtime_surface():
    expected = {
        "AgentBuilder",
        "AgentRuntime",
        "AgentStrategy",
        "CancellationToken",
        "DocumentRAG",
        "InMemoryEventBus",
        "InMemoryEventStore",
        "InMemorySessionStore",
        "ModelProvider",
        "SessionManager",
        "TextModalityAdapter",
        "TextSession",
        "ToolPlanner",
        "ToolRegistry",
        "ToolSpec",
        "execute_tool",
        "get_provider",
        "register_tool",
    }

    assert expected.issubset(set(agentkit.__all__))


def test_public_api_does_not_export_service_owned_names():
    service_owned = {
        "EncryptedText",
        "HTTPService",
        "SupabaseAuthService",
        "WebSocketMessage",
        "get_db",
    }

    assert service_owned.isdisjoint(set(agentkit.__all__))
