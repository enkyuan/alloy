import ast
from pathlib import Path

import agentkit


def test_public_api_exports_stable_runtime_surface():
    """The headline public surface is PEP 8: classes are CapWords, decorators
    and registration helpers are snake_case."""
    expected = {
        # Classes
        "AgentBuilder",
        "AgentRuntime",
        "CancellationToken",
        "InMemoryEventBus",
        "InMemoryEventStore",
        "Integration",
        "ModelProvider",
        "ProviderAPIError",
        "ProviderConfigError",
        "ProviderError",
        "SessionManager",
        "ToolContext",
        "ToolRegistry",
        "ToolSpec",
        "UnknownToolError",
        # Decorators / function helpers
        "function_tool",
        "get_provider",
        "list_tool_specs",
        "register_provider",
        "register_tool",
        "tool",
    }

    assert expected.issubset(set(agentkit.__all__))


def test_public_api_does_not_re_export_uppercamel_decorator_aliases():
    """The legacy UpperCamel decorator/helper aliases are gone. Importing them
    raises AttributeError."""
    removed = {
        "Tool",
        "FunctionTool",
        "RegisterTool",
        "ListToolSpecs",
        "GetProvider",
        "RegisterProvider",
    }
    assert removed.isdisjoint(set(agentkit.__all__))
    for name in removed:
        try:
            getattr(agentkit, name)
        except AttributeError:
            continue
        else:
            raise AssertionError(f"agentkit.{name} should no longer resolve")


def test_public_api_keeps_low_level_verbs_hidden_from_top_level():
    """Stay conservative: low-level registry verbs that aren't headline DX
    (execute_tool, clear_tools, tool_spec_from_model) stay accessible via
    their submodule rather than the top-level alias."""
    hidden_snake_case = {
        "clear_tools",
        "execute_tool",
        "tool_spec_from_model",
        "provider_safe_tool_name",
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


def test_sdk_package_exports_only_advertise_pep8_names_in_all():
    """Subpackage __all__ entries follow PEP 8: classes/types are CapWords,
    functions and decorators are snake_case. No mixed convention.

    The codebase originally pinned UpperCamel for decorators too. That
    policy was lifted in favor of PEP 8 across the board, so any __all__
    entry that is snake_case must be a function/decorator (no leading
    capital) and any CapWords entry must NOT be a known decorator/helper
    alias name."""
    package_root = Path(agentkit.__file__).parent

    # Names that were UpperCamel decorator/helper aliases. If any subpackage
    # __all__ still lists them, the rename is incomplete.
    forbidden_uppercamel_aliases = {
        "Tool",
        "FunctionTool",
        "RegisterTool",
        "ListToolSpecs",
        "GetProvider",
        "RegisterProvider",
        "ExecuteTool",
        "ClearTools",
        "ToolSpecFromModel",
        "ProviderSafeToolName",
    }

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
            bad = [n for n in names if n in forbidden_uppercamel_aliases]
            if bad:
                offenders[str(path.relative_to(package_root))] = bad

    assert offenders == {}, offenders
