import importlib
from typing import Dict, Type

from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.errors import ProviderConfigError

_PROVIDERS: Dict[str, Type[ModelProvider]] = {}
_BUILTINS: Dict[str, tuple[str, str]] = {
    "anthropic": ("kaji.runtime.providers.anthropic", "AnthropicProvider"),
    "gemini": ("kaji.runtime.providers.gemini", "GeminiProvider"),
    "kimi": ("kaji.runtime.providers.kimi", "KimiProvider"),
    "mock": ("kaji.runtime.providers.mock", "MockProvider"),
    "openai": ("kaji.runtime.providers.openai", "OpenAIProvider"),
}


def register_provider(name: str, provider_cls: Type[ModelProvider]) -> None:
    _PROVIDERS[name] = provider_cls


def get_provider(name: str, **kwargs) -> ModelProvider:
    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None and name in _BUILTINS:
        module_name, class_name = _BUILTINS[name]
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            raise ProviderConfigError(
                f"Provider '{name}' requires optional dependencies. "
                f"Install kaji[{name}] or the corresponding provider package."
            ) from None
        provider_cls = _PROVIDERS.get(name) or getattr(module, class_name)
    if provider_cls is None:
        raise ProviderConfigError(f"Provider '{name}' is not registered.")
    return provider_cls(**kwargs)
