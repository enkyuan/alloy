import ast
from pathlib import Path

import agentkit


def test_public_api_exports_stable_runtime_surface():
    expected = {
        "AgentBuilder",
        "AgentRuntime",
        "CancellationToken",
        "FunctionTool",
        "GetProvider",
        "InMemoryEventBus",
        "InMemoryEventStore",
        "Integration",
        "ModelProvider",
        "ProviderAPIError",
        "ProviderConfigError",
        "ProviderError",
        "RegisterProvider",
        "RegisterTool",
        "SessionManager",
        "Tool",
        "ToolContext",
        "ToolRegistry",
        "ToolSpec",
    }

    assert expected.issubset(set(agentkit.__all__))


def test_public_api_exports_pep8_decorator_aliases():
    """Decorators and registration helpers ship under their PEP 8 snake_case
    names alongside the legacy UpperCamel aliases."""
    pep8_aliases = {
        "tool",
        "function_tool",
        "register_tool",
        "list_tool_specs",
        "register_provider",
        "get_provider",
    }
    assert pep8_aliases.issubset(set(agentkit.__all__))


def test_public_api_keeps_camel_case_for_non_helper_extras_hidden():
    """Stay conservative: low-level registry verbs that aren't headline DX
    (execute_tool, clear_tools, tool_spec_from_model) stay accessible via
    their submodule rather than the top-level alias."""
    hidden_snake_case = {
        "clear_tools",
        "execute_tool",
        "tool_spec_from_model",
    }

    assert hidden_snake_case.isdisjoint(set(agentkit.__all__))


def test_public_api_hides_non_mvp_extensions_from_top_level():
    non_mvp = {
        "Chunk",
        "ChunkText",
        "Document",
        "DocumentRAG",
        "GetToolRetriever",
        "GetTTSProvider",
        "InMemoryVectorStore",
        "TextModalityAdapter",
        "TextSession",
        "TextSessionConfig",
        "ToolRetriever",
        "TTSProvider",
        "VectorStore",
        "VoiceTTSAdapter",
    }

    assert non_mvp.isdisjoint(set(agentkit.__all__))


def test_public_api_hides_snake_case_non_mvp_helpers_from_top_level():
    snake_case_non_mvp_helpers = {
        "chunk_text",
        "get_tool_retriever",
        "get_tts_provider",
    }

    assert snake_case_non_mvp_helpers.isdisjoint(set(agentkit.__all__))


def test_non_mvp_extensions_remain_importable_from_submodules():
    from agentkit.knowledge import ChunkText, Document, DocumentRAG
    from agentkit.modalities.text import TextModalityAdapter
    from agentkit.modalities.voice.tts import GetTTSProvider
    from agentkit.runtime.tools.retriever import GetToolRetriever, ToolRetriever

    assert ChunkText is not None
    assert Document is not None
    assert DocumentRAG is not None
    assert GetToolRetriever is not None
    assert GetTTSProvider is not None
    assert TextModalityAdapter is not None
    assert ToolRetriever is not None


def test_public_api_does_not_export_service_owned_names():
    service_owned = {
        "EncryptedText",
        "GetDB",
        "HTTPService",
        "SupabaseAuthService",
        "WebSocketMessage",
    }

    assert service_owned.isdisjoint(set(agentkit.__all__))


def test_public_api_does_not_export_snake_case_service_owned_names():
    service_owned = {
        "get_db",
    }

    assert service_owned.isdisjoint(set(agentkit.__all__))


def test_sdk_package_exports_do_not_advertise_snake_case_names():
    package_root = Path(agentkit.__file__).parent

    offenders: dict[str, list[str]] = {}
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                )
                and isinstance(node.value, (ast.List, ast.Tuple))
            ):
                continue

            names = [
                item.value
                for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            snake_case_names = [
                name
                for name in names
                if "_" in name and not (name.startswith("__") and name.endswith("__"))
            ]
            if snake_case_names:
                offenders[str(path.relative_to(package_root))] = snake_case_names

    assert offenders == {}
