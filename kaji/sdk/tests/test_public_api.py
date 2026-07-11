import ast
import importlib
import sys
from pathlib import Path

import pytest

import kaji


def test_public_api_exports_stable_runtime_surface():
    """The headline public surface is PEP 8: classes are CapWords, decorators
    and registration helpers are snake_case."""
    expected = {
        # Classes
        "AgentBuilder",
        "AgentRuntime",
        "CancellationToken",
        "Chunk",
        "Document",
        "DocumentRAG",
        "Embedder",
        "EmbeddingCache",
        "EffectiveRuntimeLimits",
        "HistoryStore",
        "InMemoryEventBus",
        "InMemoryEventStore",
        "InMemoryHistoryStore",
        "InMemorySessionStore",
        "InMemoryVectorStore",
        "Integration",
        "ModelProvider",
        "NormalizedProviderError",
        "ProviderAPIError",
        "ProviderConfigError",
        "ProviderError",
        "SessionManager",
        "SessionRecord",
        "SessionStore",
        "ToolContext",
        "ToolRegistry",
        "ToolRetriever",
        "ToolSpec",
        "UnknownToolError",
        "VectorStore",
        # Decorators / function helpers
        "build_tools_payload",
        "function_tool",
        "get_provider",
        "list_tool_specs",
        "normalize_provider_error",
        "register_provider",
        "register_tool",
        "spec_to_neutral",
        "to_anthropic",
        "to_gemini",
        "to_openai",
        "tool",
    }

    assert expected.issubset(set(kaji.__all__))


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
    assert removed.isdisjoint(set(kaji.__all__))
    for name in removed:
        try:
            getattr(kaji, name)
        except AttributeError:
            continue
        else:
            raise AssertionError(f"kaji.{name} should no longer resolve")


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

    assert hidden_snake_case.isdisjoint(set(kaji.__all__))


def test_public_api_hides_non_mvp_extensions_from_top_level():
    """Modality adapters (TTS, text-only session helpers) and the legacy
    UpperCamel retriever factory stay subpackage-only. Knowledge primitives
    (Chunk/Document/DocumentRAG/VectorStore/InMemoryVectorStore) and the
    tool retriever (ToolRetriever/Embedder/EmbeddingCache) were promoted to
    the top-level surface in feat/sdk-audit-fixes Task 2."""
    non_mvp = {
        "ChunkText",
        "GetToolRetriever",
        "GetTTSProvider",
        "TextModalityAdapter",
        "TextSession",
        "TextSessionConfig",
        "TTSProvider",
        "VoiceTTSAdapter",
    }

    assert non_mvp.isdisjoint(set(kaji.__all__))


def test_public_api_hides_snake_case_non_mvp_helpers_from_top_level():
    snake_case_non_mvp_helpers = {
        "chunk_text",
        "get_tool_retriever",
        "get_tts_provider",
    }

    assert snake_case_non_mvp_helpers.isdisjoint(set(kaji.__all__))


def test_non_mvp_extensions_remain_importable_from_submodules():
    from kaji.knowledge import ChunkText, Document, DocumentRAG
    from kaji.modalities.text import TextModalityAdapter
    from kaji.modalities.voice.tts import GetTTSProvider
    from kaji.runtime.tools.retriever import GetToolRetriever, ToolRetriever

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

    assert service_owned.isdisjoint(set(kaji.__all__))


def test_public_api_does_not_export_snake_case_service_owned_names():
    service_owned = {
        "get_db",
    }

    assert service_owned.isdisjoint(set(kaji.__all__))


# Names promoted to the top-level surface in feat/sdk-audit-fixes Task 2.
# Each must resolve through PEP 562 ``__getattr__`` without an eager
# submodule import of providers, infra, or knowledge.
_NEWLY_EXPOSED = [
    "Chunk",
    "Document",
    "DocumentRAG",
    "Embedder",
    "EmbeddingCache",
    "HistoryStore",
    "InMemoryHistoryStore",
    "InMemorySessionStore",
    "InMemoryVectorStore",
    "SessionRecord",
    "SessionStore",
    "ToolRetriever",
    "VectorStore",
    "build_tools_payload",
    "spec_to_neutral",
    "to_anthropic",
    "to_gemini",
    "to_openai",
]


@pytest.mark.parametrize("name", _NEWLY_EXPOSED)
def test_newly_exposed_name_resolves(name: str) -> None:
    """Every Task-2 promoted name resolves via the lazy map."""
    assert getattr(kaji, name) is not None, f"kaji.{name} did not resolve"


def test_import_kaji_does_not_eagerly_load_heavy_submodules() -> None:
    """``import kaji`` must remain side-effect-free: the lazy map adds 18 new
    names but accessing none of them should leave knowledge/providers/infra
    submodules unimported.

    Restores ``sys.modules`` afterwards so this test does not bleed cleared
    module cache into later tests (pytest's monkeypatch resolves dotted
    targets via the live module graph).
    """
    prefixes = (
        "kaji",
        "kaji.knowledge",
        "kaji.runtime",
        "kaji.runtime.providers.openai",
        "kaji.runtime.providers.anthropic",
        "kaji.infra.realtime",
    )
    saved = {name: mod for name, mod in sys.modules.items() if name.startswith("kaji")}
    try:
        for name in list(sys.modules):
            if name.startswith(prefixes):
                sys.modules.pop(name, None)
        importlib.import_module("kaji")
        assert "kaji.knowledge.rag" not in sys.modules
        assert "kaji.runtime.providers.openai" not in sys.modules
        assert "kaji.infra.realtime.redis" not in sys.modules
    finally:
        # Restore everything we cleared so monkeypatch.setattr targets in
        # later tests still resolve to the same module objects.
        for name in list(sys.modules):
            if name.startswith("kaji") and name not in saved:
                sys.modules.pop(name, None)
        sys.modules.update(saved)


def test_sdk_package_exports_only_advertise_pep8_names_in_all():
    """Subpackage __all__ entries follow PEP 8: classes/types are CapWords,
    functions and decorators are snake_case. No mixed convention.

    The codebase originally pinned UpperCamel for decorators too. That
    policy was lifted in favor of PEP 8 across the board, so any __all__
    entry that is snake_case must be a function/decorator (no leading
    capital) and any CapWords entry must NOT be a known decorator/helper
    alias name."""
    package_root = Path(kaji.__file__).parent

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
