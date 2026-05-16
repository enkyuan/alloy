import importlib
from typing import Dict, Type

from sdk.providers.base import ModelProvider
from sdk.providers.errors import ProviderConfigError

_PROVIDERS: Dict[str, Type[ModelProvider]] = {}
_BUILTINS_LOADED = False


def register_provider(name: str, provider_cls: Type[ModelProvider]) -> None:
    _PROVIDERS[name] = provider_cls


def _ensure_builtin_providers_loaded() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    # Provider modules self-register through register_provider(...)
    importlib.import_module("sdk.providers.gemini")
    importlib.import_module("sdk.providers.kimi")
    _BUILTINS_LOADED = True


def get_provider(name: str, **kwargs) -> ModelProvider:
    _ensure_builtin_providers_loaded()
    provider_cls = _PROVIDERS.get(name)
    if not provider_cls:
        raise ProviderConfigError(f"Provider '{name}' is not registered.")
    return provider_cls(**kwargs)
