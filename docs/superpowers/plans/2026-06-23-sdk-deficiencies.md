# Kaji SDK Deficiencies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the concrete gaps surfaced by the 2026-06-23 review of `kaji/sdk`: first-class OpenRouter provider, fixed OpenRouter header on Kimi, constructor parity across providers, removal of serve-only fields from SDK `Settings`, deletion of the empty STT subpackage, unification of the Gemini `Service`/`Provider` split, slimmer `AgentRuntime.__init__`, and a richer `TextSession` (streaming, ergonomic accessors, system-prompt and tool wiring) so the text modality reaches the same bar voice already has.

**Architecture:** Each task touches one cohesive slice — a provider file, the settings module, a modality adapter — and lands with its own failing test, implementation, passing test, commit. The neutral `ProviderMessage` / `ProviderToolSpec` / `to_openai|to_anthropic|to_gemini` boundary at `kaji/runtime/tools/payload.py` stays the single source of truth for tool format translation; provider classes change only at their own seam. The `TextSession` surface is extended without breaking its current `send()` signature — new methods are additive — so existing callers (`kaji-serve`, demos) keep working through the upgrade.

**Tech Stack:** Python 3.11, Poetry, Pydantic v2, `pydantic-settings`, `httpx`, `pytest`, `pytest-asyncio`, optional provider SDKs (`openai`, `anthropic`, `google-genai`).

## Global Constraints

- **Pre-1.0, no back-compat shims unless explicitly requested.** Rename and remove cleanly; the user instruction "No back-compat without explicit ask" applies to every task. Do not add legacy aliases, deprecation warnings, or transitional re-exports.
- **No em-dashes, no slop, terse technical sentences** in any docstring, comment, README, or CHANGELOG line touched by this plan.
- **Lazy imports preserved.** `import kaji` must continue to work with zero environment configured and zero optional dependencies installed; no task may add a top-level import of `openai`, `anthropic`, `google.genai`, or `redis` to a module reachable from `kaji/__init__.py`'s `_LAZY` map.
- **Tests use `pytest-asyncio` in auto mode** (already configured at `kaji/sdk/pytest.ini`); coroutine tests use `async def` with no decorator.
- **All provider classes must register themselves at import time** via `register_provider("name", Cls)` at the bottom of their module, matching the existing pattern in `openai.py:256`, `anthropic.py:244`, `kimi.py:291`, `gemini.py:400`.
- **Each task ends with a single commit** scoped to that task; no batching across tasks.

---

## File Structure

Files this plan creates or modifies:

- Create `kaji/sdk/kaji/runtime/providers/openrouter.py` — first-class OpenRouter provider that subclasses or composes the OpenAI client with the right base URL and headers.
- Modify `kaji/sdk/kaji/runtime/providers/kimi.py` — drop OpenRouter dual-mode, keep Cloudflare-only and Moonshot-native modes, fix `X-OpenRouter-Title` to `X-Title` (only relevant if the header survives the split; with OpenRouter peeled off it does not).
- Modify `kaji/sdk/kaji/runtime/providers/registry.py` — register `openrouter` in `_BUILTINS`.
- Modify `kaji/sdk/kaji/runtime/providers/anthropic.py:33` and `kaji/sdk/kaji/runtime/providers/gemini.py:282` — accept `api_key`, `model`, `base_url` kwargs for parity with OpenAI.
- Modify `kaji/sdk/kaji/runtime/providers/gemini.py` — collapse `GeminiService` (line 29) into `GeminiProvider` (line 282) so there is one class.
- Modify `kaji/sdk/kaji/core/config.py` — split `Settings` into `SDKSettings` (provider keys, model defaults, TTS, retention) and `ServeSettings` (DATABASE_URL, SUPABASE_*, JWT_*, CORS_*, API_V1_PREFIX). The SDK exports only `SDKSettings`.
- Delete `kaji/sdk/kaji/modalities/voice/stt/` — empty directory.
- Modify `kaji/sdk/kaji/runtime/agents/runtime.py:41-108` — remove the dual `planner` vs `tool_executor+policy+approval_handler` constructor paths; require a planner, expose a `build_planner()` static helper for the lazy path.
- Modify `kaji/sdk/kaji/modalities/text/adapter.py` — add `system_prompt`, `tools`, and `provider` kwargs to `TextModalityAdapter.__init__`; add `TextSession.stream()`, `TextSession.reply_text()`, `TextSession.last_tool_calls()`; expose multimodal content via a `TextContent` union type.
- Modify `kaji/sdk/kaji/runtime/providers/base.py:42-49` — tighten the Protocol to use `List[ProviderMessage]` and `List[ProviderToolSpec]` instead of `List[Dict[str, Any]]`.
- Modify `kaji/sdk/kaji/runtime/providers/types.py` — add `ProviderToolCall` TypedDict and use it in `ModelResponseChunk.tool_calls` and `GenerateResponse.tool_calls`.
- Create / modify test files under `kaji/sdk/tests/` per task.
- Modify `kaji/sdk/kaji/README.md` and `docs/MVP.md` — document the new provider, the slimmer settings, the richer `TextSession`.

---

## Task 1: First-class OpenRouter provider

**Files:**
- Create: `kaji/sdk/kaji/runtime/providers/openrouter.py`
- Modify: `kaji/sdk/kaji/runtime/providers/registry.py:8-14`
- Modify: `kaji/sdk/kaji/core/config.py:56-59`
- Modify: `kaji/sdk/pyproject.toml:36-48`
- Test: `kaji/sdk/tests/test_providers_openrouter.py`

**Interfaces:**
- Consumes: `OpenAIProvider` from `kaji.runtime.providers.openai`, `register_provider` from `kaji.runtime.providers.registry`, `get_settings()` from `kaji.core.config`.
- Produces: `OpenRouterProvider(api_key: Optional[str], model: Optional[str], base_url: Optional[str], http_referer: Optional[str], app_title: Optional[str])`. Registers under the name `"openrouter"`. The provider returns `ModelMetadata(provider_name="openrouter", model_name=<model>)`.

OpenRouter is an OpenAI-compatible API. Today it lives inside `KimiProvider` as a default base URL and gets the wrong header name (`X-OpenRouter-Title` instead of OpenRouter's documented `X-Title`). This task gives it a first-class provider class that piggybacks on `OpenAIProvider` so we do not duplicate the streaming / tool-call accumulator code.

- [ ] **Step 1: Write the failing test**

```python
# kaji/sdk/tests/test_providers_openrouter.py
import pytest

from kaji.runtime.providers.errors import ProviderConfigError
from kaji.runtime.providers.openrouter import OpenRouterProvider
from kaji.runtime.providers.registry import get_provider


def test_openrouter_registered():
    """OpenRouter must register itself at import time under the name
    'openrouter' and accept api_key + model + base_url via constructor
    arguments without reading the environment."""
    provider = get_provider(
        "openrouter",
        api_key="or-test",
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
    )
    assert isinstance(provider, OpenRouterProvider)
    assert provider.model_name == "openai/gpt-4o-mini"


def test_openrouter_sets_x_title_header():
    """The OpenRouter spec lists the optional attribution header as
    `X-Title` and the referrer header as `HTTP-Referer`. The previous
    KimiProvider used the wrong name `X-OpenRouter-Title`; that bug is
    fixed here at the class boundary."""
    provider = OpenRouterProvider(
        api_key="or-test",
        model="openai/gpt-4o-mini",
        app_title="kaji-test",
        http_referer="https://example.com",
    )
    headers = provider._extra_headers()
    assert headers["X-Title"] == "kaji-test"
    assert headers["HTTP-Referer"] == "https://example.com"


def test_openrouter_missing_key_raises():
    with pytest.raises(ProviderConfigError):
        OpenRouterProvider(api_key=None, model="openai/gpt-4o-mini")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers_openrouter.py -v
```

Expected: FAIL with `ModuleNotFoundError: kaji.runtime.providers.openrouter`.

- [ ] **Step 3: Write the provider**

```python
# kaji/sdk/kaji/runtime/providers/openrouter.py
"""OpenRouter provider.

OpenRouter exposes an OpenAI-compatible chat-completions endpoint. We extend
``OpenAIProvider`` so the streaming, tool-call accumulator, and message
formatting logic is shared. The only differences are: default base URL,
optional `HTTP-Referer` + `X-Title` attribution headers (per OpenRouter docs),
and the metadata stamp.

Enable with ``KAJI_MODEL_PROVIDER=openrouter`` and an
``OPENROUTER_API_KEY``.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Optional

from kaji.core.config import get_settings
from kaji.runtime.providers.errors import ProviderConfigError
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.registry import register_provider
from kaji.runtime.providers.types import ModelMetadata


_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter chat-completions provider.

    Constructor arguments take precedence over ``Settings``; falling back to
    env keeps `get_provider("openrouter")` ergonomic for callers that prefer
    `.env`-driven config.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        http_referer: Optional[str] = None,
        app_title: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        resolved_key = api_key if api_key is not None else settings.OPENROUTER_API_KEY
        resolved_model = model if model is not None else settings.OPENROUTER_MODEL
        resolved_base = (
            base_url
            if base_url is not None
            else (settings.OPENROUTER_BASE_URL or _DEFAULT_BASE_URL)
        )

        if not resolved_key:
            raise ProviderConfigError(
                "OpenRouter API key is not configured. Set OPENROUTER_API_KEY."
            )

        super().__init__(
            api_key=resolved_key, model=resolved_model, base_url=resolved_base
        )
        self.http_referer = (
            http_referer
            if http_referer is not None
            else settings.OPENROUTER_HTTP_REFERER
        )
        self.app_title = (
            app_title if app_title is not None else settings.OPENROUTER_APP_TITLE
        )

    def _extra_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-Title"] = self.app_title
        return headers

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                AsyncOpenAI = import_module("openai").AsyncOpenAI
            except ImportError as error:
                raise ProviderConfigError(
                    "OpenRouter provider requires openai. Install kaji[openai]."
                ) from error
            extra = self._extra_headers()
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=extra or None,
            )
        return self._client


register_provider("openrouter", OpenRouterProvider)
```

- [ ] **Step 4: Register in `_BUILTINS`**

Edit `kaji/sdk/kaji/runtime/providers/registry.py:8-14`:

```python
_BUILTINS: Dict[str, tuple[str, str]] = {
    "anthropic": ("kaji.runtime.providers.anthropic", "AnthropicProvider"),
    "gemini": ("kaji.runtime.providers.gemini", "GeminiProvider"),
    "kimi": ("kaji.runtime.providers.kimi", "KimiProvider"),
    "mock": ("kaji.runtime.providers.mock", "MockProvider"),
    "openai": ("kaji.runtime.providers.openai", "OpenAIProvider"),
    "openrouter": ("kaji.runtime.providers.openrouter", "OpenRouterProvider"),
}
```

- [ ] **Step 5: Add `OPENROUTER_MODEL` to settings**

Edit `kaji/sdk/kaji/core/config.py:56-59` so the block reads:

```python
# OpenRouter (OpenAI-compatible aggregator)
OPENROUTER_API_KEY: Optional[str] = None
OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
OPENROUTER_BASE_URL: Optional[str] = None  # None => OpenRouter default
OPENROUTER_HTTP_REFERER: Optional[str] = None
OPENROUTER_APP_TITLE: Optional[str] = None
```

- [ ] **Step 6: Add `openrouter` extra in pyproject**

Edit `kaji/sdk/pyproject.toml:36-48` to add an extra (OpenRouter needs the same `openai` SDK):

```toml
openrouter = ["openai"]
```

Place it alphabetically between `openai` and `providers`.

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers_openrouter.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/openrouter.py \
        kaji/sdk/kaji/runtime/providers/registry.py \
        kaji/sdk/kaji/core/config.py \
        kaji/sdk/pyproject.toml \
        kaji/sdk/tests/test_providers_openrouter.py
git commit -m "feat(sdk): first-class OpenRouter provider with correct X-Title header"
```

---

## Task 2: Strip OpenRouter wiring out of KimiProvider

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/kimi.py:22-62`
- Test: `kaji/sdk/tests/test_providers.py`

**Interfaces:**
- Consumes: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` are no longer read by `KimiProvider`. Callers who wanted Kimi-via-OpenRouter now do `get_provider("openrouter", model="moonshotai/kimi-k2.6")` instead.
- Produces: `KimiProvider` now has two modes only — Cloudflare Workers AI (when `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` set) or Moonshot native API (when `KIMI_API_KEY` set with `KIMI_BASE_URL` defaulting to `https://api.moonshot.cn/v1/chat/completions`). Default base URL flips from OpenRouter to Moonshot.

KimiProvider currently does three things: Cloudflare Workers, Moonshot, *and* OpenRouter. With Task 1 in place the OpenRouter path is redundant. We drop it so each provider has one transport.

- [ ] **Step 1: Write the failing test**

```python
# Append to kaji/sdk/tests/test_providers.py
import pytest

from kaji.runtime.providers.errors import ProviderConfigError
from kaji.runtime.providers.kimi import KimiProvider


def test_kimi_no_longer_reads_openrouter_key(monkeypatch):
    """Setting only OPENROUTER_API_KEY must NOT satisfy Kimi any more."""
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    # Clear the lru_cache on get_settings if needed:
    from kaji.core.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    with pytest.raises(ProviderConfigError):
        KimiProvider()


def test_kimi_defaults_to_moonshot_base(monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "kimi-test")
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    from kaji.core.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    provider = KimiProvider()
    assert provider.base_url == "https://api.moonshot.cn/v1/chat/completions"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers.py::test_kimi_no_longer_reads_openrouter_key tests/test_providers.py::test_kimi_defaults_to_moonshot_base -v
```

Expected: FAIL — first test passes (Kimi previously errored only if neither key set), second test FAILs because base URL is OpenRouter.

- [ ] **Step 3: Rewrite `KimiProvider.__init__`**

Replace `kaji/sdk/kaji/runtime/providers/kimi.py:22-62` (the constructor and `_get_headers`) with:

```python
class KimiProvider(ModelProvider):
    """Kimi (Moonshot) provider with Cloudflare Workers fallback.

    Two transports, mutually exclusive:
      * Cloudflare Workers AI when both CLOUDFLARE_ACCOUNT_ID and
        CLOUDFLARE_API_TOKEN are set.
      * Moonshot native API otherwise; expects KIMI_API_KEY.

    OpenRouter is no longer handled here. Use OpenRouterProvider
    (`get_provider("openrouter", model="moonshotai/kimi-k2.6")`).
    """

    _MOONSHOT_DEFAULT = "https://api.moonshot.cn/v1/chat/completions"

    def __init__(self, **kwargs: Any) -> None:
        settings = get_settings()
        self.is_cloudflare = bool(
            settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN
        )

        if self.is_cloudflare:
            self.model_name = settings.CLOUDFLARE_KIMI_MODEL
            self.base_url = (
                f"https://api.cloudflare.com/client/v4/accounts/"
                f"{settings.CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
            )
            self.api_key = settings.CLOUDFLARE_API_TOKEN
        else:
            self.model_name = settings.KIMI_MODEL
            self.base_url = settings.KIMI_BASE_URL or self._MOONSHOT_DEFAULT
            self.api_key = settings.KIMI_API_KEY

        if not self.api_key:
            raise ProviderConfigError(
                "Kimi API key is not configured. Set KIMI_API_KEY "
                "(or CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID)."
            )

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers.py -v
```

Expected: existing tests still pass; new tests pass.

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/kimi.py kaji/sdk/tests/test_providers.py
git commit -m "refactor(sdk): peel OpenRouter out of KimiProvider, default to Moonshot"
```

---

## Task 3: Constructor parity across providers

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/anthropic.py:33-43`
- Modify: `kaji/sdk/kaji/runtime/providers/gemini.py:34-55` and `:282`+
- Test: `kaji/sdk/tests/test_providers_anthropic.py`, `kaji/sdk/tests/test_providers.py`

**Interfaces:**
- Produces: every provider accepts the same shape `(*, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None)`. None means "read from settings". Gemini also accepts `model: Optional[str]`.

Anthropic and Gemini currently ignore their constructor arguments and read env only, which conflicts with the OpenAI/OpenRouter pattern. Unify them.

- [ ] **Step 1: Write the failing tests**

```python
# Append to kaji/sdk/tests/test_providers_anthropic.py
def test_anthropic_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    from kaji.core.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    from kaji.runtime.providers.anthropic import AnthropicProvider
    provider = AnthropicProvider(api_key="explicit", model="claude-opus-4-7")
    assert provider.api_key == "explicit"
    assert provider.model_name == "claude-opus-4-7"
```

```python
# Append to kaji/sdk/tests/test_providers.py
def test_gemini_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    from kaji.core.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    pytest.importorskip("google.genai")
    from kaji.runtime.providers.gemini import GeminiProvider
    provider = GeminiProvider(api_key="explicit", model="gemini-3-flash-preview")
    assert provider.api_key == "explicit"
    assert provider.model_name == "gemini-3-flash-preview"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers_anthropic.py::test_anthropic_constructor_overrides_env tests/test_providers.py::test_gemini_constructor_overrides_env -v
```

Expected: both FAIL — Anthropic ignores `api_key`, Gemini ignores both.

- [ ] **Step 3: Update Anthropic constructor**

Edit `kaji/sdk/kaji/runtime/providers/anthropic.py:33-43` to:

```python
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        self.model_name = model if model is not None else settings.ANTHROPIC_MODEL
        self.base_url = base_url
        self._client: Any = None

        if not self.api_key:
            raise ProviderConfigError(
                "Anthropic API key is not configured. Set ANTHROPIC_API_KEY."
            )
```

In the `client` property (line 47), pass `base_url=self.base_url` to `AsyncAnthropic(...)` if `self.base_url` is not None.

- [ ] **Step 4: Update Gemini constructor**

This is folded into Task 4 (single Gemini class). Track the constructor-parity test here but the implementation lands with Task 4.

- [ ] **Step 5: Run Anthropic test to verify pass**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers_anthropic.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/anthropic.py \
        kaji/sdk/tests/test_providers_anthropic.py
git commit -m "feat(sdk): AnthropicProvider accepts api_key/model/base_url kwargs"
```

---

## Task 4: Collapse `GeminiService` into `GeminiProvider`

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/gemini.py` (whole file: drop `GeminiService` class at line 29, fold its methods into `GeminiProvider` at line 282)
- Test: `kaji/sdk/tests/test_providers.py`, `kaji/sdk/tests/test_providers_gemini_stream.py`

**Interfaces:**
- Consumes: `google.genai` SDK (already optional), `format_messages_gemini`, `split_system_for_gemini`, `to_gemini`.
- Produces: a single public class `GeminiProvider(api_key=None, model=None, base_url=None)` implementing `ModelProvider`. `GeminiService` is removed (no alias).

The current file has two classes: `GeminiService` (implementation since the early voice-agent days) and `GeminiProvider` (a thin Protocol-conforming wrapper). The two-class split was historical; nothing outside the file requires `GeminiService` (verify by grep). Collapse them.

- [ ] **Step 1: Verify `GeminiService` is not imported anywhere except `gemini.py`**

```bash
cd kaji/sdk
grep -rn "GeminiService" kaji/ tests/
```

Expected: only matches in `kaji/runtime/providers/gemini.py` itself. If a test imports it, update the test in the same task.

- [ ] **Step 2: Write the failing test**

```python
# Append to kaji/sdk/tests/test_providers.py
def test_gemini_service_class_removed():
    """GeminiService was an internal implementation class; the public class
    is GeminiProvider. The split was confusing and is removed."""
    from kaji.runtime.providers import gemini as gemini_mod
    assert not hasattr(gemini_mod, "GeminiService")
    assert hasattr(gemini_mod, "GeminiProvider")
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers.py::test_gemini_service_class_removed -v
```

Expected: FAIL (`GeminiService` still exists).

- [ ] **Step 4: Refactor gemini.py**

Rewrite the file so there is one class. Move the `_active_caches`, `_get_active_cache`, `generate_chat_response`, `generate_chat_stream` methods from `GeminiService` into `GeminiProvider`. The new `GeminiProvider.__init__` becomes:

```python
class GeminiProvider(ModelProvider):
    """Google Gemini provider with optional context caching for long histories."""

    _active_caches: Dict[str, str] = {}

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model if model is not None else settings.GEMINI_MODEL
        if not self.api_key:
            raise ProviderConfigError(
                "Gemini API key is not configured. Set GEMINI_API_KEY."
            )
        try:
            genai = import_module("google.genai")
        except ImportError as error:
            raise ProviderConfigError(
                "Gemini provider requires google-genai. Install kaji[gemini]."
            ) from error
        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if base_url is not None:
            client_kwargs["http_options"] = {"base_url": base_url}
        self.client = genai.Client(**client_kwargs)
```

References to `self.service.generate_chat_response(...)` in `generate()` (around line 308) and `self.service.generate_chat_stream(...)` in `generate_stream()` (around line 371) become direct method calls. References to `self.service.model` become `self.model_name`.

- [ ] **Step 5: Run all Gemini tests to verify pass**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers.py tests/test_providers_gemini_stream.py tests/test_providers.py::test_gemini_constructor_overrides_env -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/gemini.py kaji/sdk/tests/test_providers.py
git commit -m "refactor(sdk): collapse GeminiService into GeminiProvider"
```

---

## Task 5: Split `Settings` into `SDKSettings` and `ServeSettings`

**Files:**
- Modify: `kaji/sdk/kaji/core/config.py` (whole file)
- Modify: `kaji/serve/kaji_serve/...` — wherever `Settings` is imported from `kaji.core.config`, switch to `from kaji.core.config import SDKSettings` and import `ServeSettings` from a new `kaji_serve.config` module.
- Create: `kaji/serve/kaji_serve/config.py` (or augment the existing one) — `ServeSettings` for DATABASE_URL, SUPABASE_*, JWT_*, CORS_*, API_V1_PREFIX.
- Test: `kaji/sdk/tests/test_public_surface.py`, new `kaji/sdk/tests/test_config_split.py`

**Interfaces:**
- Consumes: `pydantic_settings.BaseSettings`.
- Produces: `kaji.core.config.SDKSettings` (only SDK-relevant fields), `kaji.core.config.get_settings() -> SDKSettings`. Old name `Settings` is removed (pre-1.0, no shim).

The SDK's `Settings` class currently has 30+ fields, half of which are serve-only (DATABASE_URL, SUPABASE_*, JWT_*, CORS_*). Move them out so the SDK config schema is small and obviously SDK-shaped.

- [ ] **Step 1: Write the failing test**

```python
# kaji/sdk/tests/test_config_split.py
import pytest


def test_sdk_settings_has_only_sdk_fields():
    """The SDK config schema must not include serve-only fields. This
    guards against accidental coupling re-creep."""
    from kaji.core.config import SDKSettings
    fields = set(SDKSettings.model_fields.keys())

    forbidden = {
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_KONG_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "JWT_SECRET",
        "JWT_ALGORITHM",
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "TOKEN_ENCRYPTION_KEY",
        "CORS_ALLOW_ORIGINS",
        "API_V1_PREFIX",
        "PROJECT_NAME",
    }
    overlap = fields & forbidden
    assert not overlap, f"serve-only fields leaked into SDKSettings: {overlap}"


def test_settings_alias_removed():
    """Old name `Settings` is gone (pre-1.0, no shim)."""
    from kaji.core import config
    assert not hasattr(config, "Settings")


def test_get_settings_returns_sdk_settings():
    from kaji.core.config import get_settings, SDKSettings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert isinstance(get_settings(), SDKSettings)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd kaji/sdk
poetry run pytest tests/test_config_split.py -v
```

Expected: FAIL — `SDKSettings` does not exist.

- [ ] **Step 3: Rewrite `kaji/sdk/kaji/core/config.py`**

```python
"""Application configuration for the SDK.

Only SDK-relevant fields live here. Serve-stack fields (DATABASE_URL,
SUPABASE_*, JWT_*, CORS_*, API_V1_PREFIX) live in `kaji_serve.config`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class SDKSettings(BaseSettings):
    """SDK-only settings: provider keys, model defaults, TTS, retention."""

    # Active provider
    KAJI_MODEL_PROVIDER: str = "mock"

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: Optional[str] = None

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Google Gemini
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"

    # OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: Optional[str] = None
    OPENROUTER_HTTP_REFERER: Optional[str] = None
    OPENROUTER_APP_TITLE: Optional[str] = None

    # Kimi / Cloudflare
    KIMI_API_KEY: Optional[str] = None
    KIMI_MODEL: str = "moonshotai/kimi-k2.6"
    KIMI_BASE_URL: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_KIMI_MODEL: str = "@cf/moonshotai/kimi-k2.6"

    # STT
    SONIOX_API_KEY: Optional[str] = None

    # TTS
    TTS_PROVIDER: str = "none"
    TTS_VOICE: str = ""
    TTS_MODEL: str = ""

    # Realtime backbone (optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Agent pipeline
    AGENT_HISTORY_LIMIT: Optional[int] = 200
    AGENT_CACHE_TTL_SECONDS: int = 300
    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> SDKSettings:
    return SDKSettings()
```

- [ ] **Step 4: Move serve fields into `kaji_serve.config`**

In the serve package (`kaji/serve/kaji_serve/config.py`), define `ServeSettings` extending `SDKSettings`:

```python
from kaji.core.config import SDKSettings
from pydantic_settings import SettingsConfigDict
from typing import Optional


class ServeSettings(SDKSettings):
    DATABASE_URL: str = ""
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KONG_URL: Optional[str] = None
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    TOKEN_ENCRYPTION_KEY: Optional[str] = None
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Kaji Serve"

    @property
    def cors_allow_origins(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
        return origins or ["http://localhost:3000"]

    def model_post_init(self, _context) -> None:
        if not self.SUPABASE_KONG_URL and self.SUPABASE_URL:
            self.SUPABASE_KONG_URL = self.SUPABASE_URL
        if not self.SUPABASE_SERVICE_ROLE_KEY and self.SUPABASE_SERVICE_KEY:
            self.SUPABASE_SERVICE_ROLE_KEY = self.SUPABASE_SERVICE_KEY
```

Then in any serve module that currently does `from kaji.core.config import Settings, get_settings`, switch to `from kaji_serve.config import ServeSettings, get_serve_settings` (define `get_serve_settings` analogously with `lru_cache`).

- [ ] **Step 5: Run config + public-surface + full SDK tests**

```bash
cd kaji/sdk
poetry run pytest tests/test_config_split.py tests/test_public_surface.py tests/ -x
```

Expected: pass.

- [ ] **Step 6: Run the serve test suite if touchable**

```bash
cd kaji/serve
poetry run pytest -x
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add kaji/sdk/kaji/core/config.py \
        kaji/serve/kaji_serve/config.py \
        kaji/sdk/tests/test_config_split.py \
        kaji/serve/...  # any serve modules updated
git commit -m "refactor(sdk,serve): split Settings into SDKSettings + ServeSettings"
```

---

## Task 6: Delete the empty `modalities/voice/stt/` subpackage

**Files:**
- Delete: `kaji/sdk/kaji/modalities/voice/stt/` (directory)
- Test: `kaji/sdk/tests/test_package_boundaries.py`

**Interfaces:** none changed; STT subpackage had no public symbols.

The directory contains only `__pycache__`. It misleads readers into thinking STT is wired.

- [ ] **Step 1: Confirm the directory is empty of source**

```bash
cd kaji/sdk
find kaji/modalities/voice/stt -type f \! -path '*/__pycache__/*'
```

Expected: no output.

- [ ] **Step 2: Add a guard test**

Append to `kaji/sdk/tests/test_package_boundaries.py`:

```python
def test_stt_subpackage_absent():
    """STT is not implemented; the directory must not exist as a stub."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("kaji.modalities.voice.stt")
```

- [ ] **Step 3: Run the new test to verify it fails**

```bash
cd kaji/sdk
poetry run pytest tests/test_package_boundaries.py::test_stt_subpackage_absent -v
```

Expected: FAIL (directory still importable as namespace package or via `__pycache__`).

- [ ] **Step 4: Delete the directory**

```bash
cd kaji/sdk
rm -rf kaji/modalities/voice/stt
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd kaji/sdk
poetry run pytest tests/test_package_boundaries.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add -A kaji/sdk/kaji/modalities/voice/stt kaji/sdk/tests/test_package_boundaries.py
git commit -m "chore(sdk): remove empty stt subpackage"
```

---

## Task 7: Slim `AgentRuntime.__init__` to a single wiring path

**Files:**
- Modify: `kaji/sdk/kaji/runtime/agents/runtime.py:41-108`
- Modify: `kaji/sdk/kaji/runtime/agents/builder.py` (where `AgentRuntime(...)` is constructed)
- Modify: `kaji/sdk/kaji/modalities/text/adapter.py:79-89` (`_default_runtime`)
- Test: `kaji/sdk/tests/test_agents_runtime.py`

**Interfaces:**
- Consumes: `ToolPlanner`, `EventBusProtocol`, `EventStore`, `ModelProvider`, `AgentStrategy`, `SystemPrompt`.
- Produces: `AgentRuntime(bus, store, provider, planner, *, system_prompt="...", strategy=None, tools=None, rag=None, rag_top_k=5)`. Removes `tool_executor`, `policy`, `approval_handler`, `user_id` from `AgentRuntime.__init__`. Callers wire a `ToolPlanner` themselves (or use `AgentRuntime.build_planner(...)` helper).

The current constructor has two paths (explicit planner vs lazy-build from executor + policy + approval) that do the same thing. Pick one (explicit), expose a static helper for the lazy case, and remove the duplicate.

- [ ] **Step 1: Write the failing test**

```python
# Append to kaji/sdk/tests/test_agents_runtime.py
def test_runtime_requires_planner():
    """AgentRuntime no longer accepts tool_executor/policy/approval_handler."""
    import inspect
    from kaji.runtime.agents.runtime import AgentRuntime
    sig = inspect.signature(AgentRuntime.__init__)
    params = set(sig.parameters.keys())
    assert "planner" in params
    assert "tool_executor" not in params
    assert "policy" not in params
    assert "approval_handler" not in params
    assert "user_id" not in params


def test_build_planner_helper_exists():
    from kaji.runtime.agents.runtime import AgentRuntime
    assert callable(getattr(AgentRuntime, "build_planner", None))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd kaji/sdk
poetry run pytest tests/test_agents_runtime.py::test_runtime_requires_planner tests/test_agents_runtime.py::test_build_planner_helper_exists -v
```

Expected: FAIL.

- [ ] **Step 3: Rewrite `AgentRuntime.__init__`**

Replace lines 41-108 with:

```python
    def __init__(
        self,
        bus: EventBusProtocol,
        store: EventStore,
        provider: ModelProvider,
        planner: ToolPlanner,
        *,
        system_prompt: str = "You are a helpful assistant.",
        strategy: Optional[AgentStrategy] = None,
        tools: Optional[List[ToolSpec]] = None,
        rag: Optional[Any] = None,
        rag_top_k: int = 5,
    ) -> None:
        self.bus = bus
        self.store = store
        self.provider = provider
        self._planner = planner
        self.prompt = SystemPrompt(system_prompt)
        self.strategy = strategy or AgentStrategy()
        self.state_manager = SessionStateManager(store)
        self.tools = tools or []
        self._tool_payload: List[Dict[str, Any]] = [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self.tools
        ]
        self._rag = rag
        self._rag_top_k = rag_top_k

    @staticmethod
    def build_planner(
        tools: Optional[List[ToolSpec]] = None,
        *,
        tool_executor: Optional[ToolExecutor] = None,
        policy: Optional[Any] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        user_id: str = "agent",
    ) -> ToolPlanner:
        """Construct a ToolPlanner with sensible defaults.

        The default executor delegates to the global tool registry's
        ``execute_tool``. Pass ``tool_executor`` to use a scoped registry.
        """
        from kaji.runtime.tools.registry import execute_tool

        executor: ToolExecutor = tool_executor or (
            lambda name, args: execute_tool(user_id, name, args)
        )
        specs = {spec.name: spec for spec in (tools or [])}
        return ToolPlanner(
            executor=executor,
            policy=policy,
            approval_handler=approval_handler,
            specs=specs,
        )
```

Delete the old `_build_planner` method.

- [ ] **Step 4: Update `AgentBuilder` and `_default_runtime`**

In `kaji/sdk/kaji/runtime/agents/builder.py`, replace any `AgentRuntime(... tool_executor=..., policy=..., approval_handler=...)` with explicit `planner=AgentRuntime.build_planner(tools=..., tool_executor=..., policy=..., approval_handler=...)`.

In `kaji/sdk/kaji/modalities/text/adapter.py:79-89`, replace `_default_runtime` body:

```python
def _default_runtime(store: EventStore) -> AgentRuntime:
    planner = ToolPlanner(executor=_default_missing_executor)
    return AgentRuntime(
        bus=InMemoryEventBus(),
        store=store,
        provider=get_provider("mock"),
        planner=planner,
    )


async def _default_missing_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    raise ValueError(f"No tool executor configured for {name!r}")
```

- [ ] **Step 5: Run full runtime suite to verify pass**

```bash
cd kaji/sdk
poetry run pytest tests/test_agents_runtime.py tests/test_agents_builder.py tests/test_modalities_text.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/agents/runtime.py \
        kaji/sdk/kaji/runtime/agents/builder.py \
        kaji/sdk/kaji/modalities/text/adapter.py \
        kaji/sdk/tests/test_agents_runtime.py
git commit -m "refactor(sdk): single wiring path for AgentRuntime, expose build_planner helper"
```

---

## Task 8: Richer `TextSession` — streaming, reply_text, last_tool_calls, system prompt + tools at adapter level

**Files:**
- Modify: `kaji/sdk/kaji/modalities/text/adapter.py` (whole file)
- Test: `kaji/sdk/tests/test_modalities_text.py`

**Interfaces:**
- Consumes: `AgentMessageDelta`, `AgentMessageCompleted`, `ToolCallCompleted`, `ToolCallFailed` from `kaji.infra.events.schemas`; `EventBusProtocol`; `InMemoryEventBus`.
- Produces:
  - `TextModalityAdapter(__init__(self, *, provider=None, tools=None, system_prompt="You are a helpful assistant.", runtime=None, store=None))`.
  - `TextSession.send(content: str) -> list[KajiEvent]` (unchanged signature).
  - `TextSession.reply_text(content: str) -> str` — returns the concatenated `AgentMessageCompleted.content` for the turn, raising if no completion was emitted.
  - `TextSession.stream(content: str) -> AsyncIterator[str]` — async-yields each `AgentMessageDelta.delta` as it lands, by subscribing to the bus for this session before sending.
  - `TextSession.last_tool_calls() -> list[ToolCallCompleted]` — filter of the event log.

Text modality currently only exposes `send()` returning raw events. Power users build their own subscriber to get streaming and assistant text. The adapter is also opaque about provider/tools/system-prompt wiring — you must hand-roll an `AgentRuntime`. This task pulls the three most common knobs up to the adapter and adds the three most common accessors to the session.

- [ ] **Step 1: Write the failing tests**

```python
# Append to kaji/sdk/tests/test_modalities_text.py
import pytest

from kaji.modalities.text.adapter import TextModalityAdapter


@pytest.mark.asyncio
async def test_adapter_accepts_provider_tools_system_prompt():
    """Adapter wires provider/tools/system_prompt without a hand-rolled
    AgentRuntime."""
    adapter = TextModalityAdapter(system_prompt="You are terse.")
    session = adapter.open_session("s1", "u1")
    # Smoke: the runtime's prompt was set
    assert "terse" in session.runtime.prompt.template


@pytest.mark.asyncio
async def test_reply_text_returns_assistant_text():
    adapter = TextModalityAdapter()
    session = adapter.open_session("s2", "u2")
    text = await session.reply_text("hi")
    assert isinstance(text, str)
    # Default provider is the mock provider; it returns deterministic text
    assert text != ""


@pytest.mark.asyncio
async def test_stream_yields_deltas():
    adapter = TextModalityAdapter()
    session = adapter.open_session("s3", "u3")
    pieces: list[str] = []
    async for delta in session.stream("hi"):
        pieces.append(delta)
    assert "".join(pieces) != ""


@pytest.mark.asyncio
async def test_last_tool_calls_filter():
    adapter = TextModalityAdapter()
    session = adapter.open_session("s4", "u4")
    await session.send("hi")
    calls = await session.last_tool_calls()
    assert isinstance(calls, list)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd kaji/sdk
poetry run pytest tests/test_modalities_text.py -v -k "adapter_accepts_provider_tools_system_prompt or reply_text or stream_yields or last_tool_calls"
```

Expected: FAIL.

- [ ] **Step 3: Extend `TextModalityAdapter` and `TextSession`**

Add to `kaji/sdk/kaji/modalities/text/adapter.py`:

```python
from typing import AsyncIterator, List

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.schemas import (
    KajiEvent,
    AgentMessageCompleted,
    AgentMessageDelta,
    ToolCallCompleted,
)
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.tools.registry import ToolSpec


@dataclass
class TextSession:
    config: TextSessionConfig
    runtime: AgentRuntime
    store: EventStore
    bus: EventBusProtocol
    _sent: int = field(default=0, init=False)

    async def send(self, content: str) -> list[KajiEvent]:
        if not content.strip():
            raise ValueError("content must not be empty")
        await self.runtime.send(self.config.session_id, content)
        self._sent += 1
        return await self.events()

    async def events(self) -> list[KajiEvent]:
        return await self.store.get_events(self.config.session_id)

    async def reply_text(self, content: str) -> str:
        await self.send(content)
        events = await self.events()
        completions = [
            e for e in events
            if isinstance(e, AgentMessageCompleted)
            and e.session_id == self.config.session_id
        ]
        if not completions:
            raise RuntimeError("turn produced no AgentMessageCompleted event")
        return completions[-1].content

    async def stream(self, content: str) -> AsyncIterator[str]:
        if not content.strip():
            raise ValueError("content must not be empty")
        import asyncio
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def handler(event: KajiEvent) -> None:
            if (
                isinstance(event, AgentMessageDelta)
                and event.session_id == self.config.session_id
            ):
                await queue.put(event.delta)
            elif (
                isinstance(event, AgentMessageCompleted)
                and event.session_id == self.config.session_id
            ):
                await queue.put(None)

        unsubscribe = await self.bus.subscribe(handler)
        send_task = asyncio.create_task(
            self.runtime.send(self.config.session_id, content)
        )
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            await unsubscribe()
            await send_task

    async def last_tool_calls(self) -> List[ToolCallCompleted]:
        events = await self.events()
        return [
            e for e in events
            if isinstance(e, ToolCallCompleted)
            and e.session_id == self.config.session_id
        ]


class TextModalityAdapter:
    modality = "text"

    def __init__(
        self,
        *,
        provider: Optional[ModelProvider] = None,
        tools: Optional[List[ToolSpec]] = None,
        system_prompt: str = "You are a helpful assistant.",
        runtime: Optional[AgentRuntime] = None,
        store: Optional[EventStore] = None,
        bus: Optional[EventBusProtocol] = None,
    ) -> None:
        self._provider = provider
        self._tools = tools or []
        self._system_prompt = system_prompt
        self._runtime = runtime
        self._store = store
        self._bus = bus

    def open_session(self, session_id: str, user_id: str) -> TextSession:
        config = TextSessionConfig(session_id=session_id, user_id=user_id)
        store = self._store or InMemoryEventStore()
        bus = self._bus or InMemoryEventBus()
        runtime = self._runtime or self._build_runtime(bus, store)
        return TextSession(config=config, runtime=runtime, store=store, bus=bus)

    def _build_runtime(
        self, bus: EventBusProtocol, store: EventStore
    ) -> AgentRuntime:
        provider = self._provider or get_provider("mock")
        planner = AgentRuntime.build_planner(tools=self._tools)
        return AgentRuntime(
            bus=bus,
            store=store,
            provider=provider,
            planner=planner,
            system_prompt=self._system_prompt,
            tools=self._tools,
        )
```

Note: `EventBus.subscribe` must return an `unsubscribe` coroutine. If `InMemoryEventBus.subscribe` does not match this signature today, update it as part of this task; check `kaji/sdk/kaji/infra/events/bus.py` for the existing shape and adapt the handler API to whatever it currently provides (sync teardown is fine — adjust the `await unsubscribe()` line accordingly).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd kaji/sdk
poetry run pytest tests/test_modalities_text.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/kaji/modalities/text/adapter.py kaji/sdk/tests/test_modalities_text.py
git commit -m "feat(sdk): TextSession.stream/reply_text/last_tool_calls + adapter knobs"
```

---

## Task 9: Tighten provider Protocol with neutral TypedDicts

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/base.py:22-67`
- Modify: `kaji/sdk/kaji/runtime/providers/types.py` (add `ProviderToolCall`)
- Test: `kaji/sdk/tests/test_providers_translate.py`

**Interfaces:**
- Produces: `ProviderToolCall = TypedDict("ProviderToolCall", {"id": Optional[str], "name": str, "arguments": Dict[str, Any]})`. `ModelProvider.generate` signature becomes `List[ProviderMessage]`, `Optional[List[ProviderToolSpec]]`, return `GenerateResponse`. `GenerateResponse.tool_calls` and `ModelResponseChunk.tool_calls` become `List[ProviderToolCall]`.

The Protocol currently uses `List[Dict[str, Any]]`. The neutral TypedDicts already exist in `types.py`; promote them into the signature so callers and providers share the type contract.

- [ ] **Step 1: Write the failing test**

```python
# Append to kaji/sdk/tests/test_providers_translate.py
def test_provider_protocol_uses_typed_dicts():
    """ModelProvider.generate signature must reference ProviderMessage and
    ProviderToolSpec rather than plain dict aliases."""
    import inspect
    from kaji.runtime.providers.base import ModelProvider
    sig = inspect.signature(ModelProvider.generate)
    messages_annotation = sig.parameters["messages"].annotation
    tools_annotation = sig.parameters["tools"].annotation
    # Stringify to avoid runtime evaluation mismatches
    assert "ProviderMessage" in str(messages_annotation)
    assert "ProviderToolSpec" in str(tools_annotation)


def test_provider_tool_call_typed_dict_exported():
    from kaji.runtime.providers.types import ProviderToolCall
    # TypedDict: instantiate as a dict and check the keys
    sample: ProviderToolCall = {"id": "tc_1", "name": "ping", "arguments": {}}
    assert sample["name"] == "ping"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd kaji/sdk
poetry run pytest tests/test_providers_translate.py -v -k "typed_dict"
```

Expected: FAIL.

- [ ] **Step 3: Update `types.py`**

Append to `kaji/sdk/kaji/runtime/providers/types.py`:

```python
class ProviderToolCall(TypedDict, total=False):
    """A normalized tool-call as the SDK passes them between provider
    and planner. ``id`` may be None for providers that do not return one;
    ``arguments`` is always a parsed JSON object."""

    id: Optional[str]
    name: str
    arguments: Dict[str, Any]
```

Update `ModelResponseChunk` and `GenerateResponse`:

```python
class ModelResponseChunk(BaseModel):
    delta: str = ""
    tool_calls: List[ProviderToolCall] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    text: str
    tool_calls: List[ProviderToolCall] = Field(default_factory=list)
    metadata: Optional[ModelMetadata] = None
    metrics: Optional[TokenMetrics] = None
```

Note: Pydantic v2 accepts `TypedDict` as a field type via `Annotated`. If raw assignment errors at model-validation time, wrap the type as `List[Dict[str, Any]]` for the field but keep the TypedDict in the Protocol signature only (where it is documentation rather than validation).

- [ ] **Step 4: Update `base.py`**

Replace `kaji/sdk/kaji/runtime/providers/base.py:40-67` to use the TypedDicts in `messages: List[ProviderMessage]` and `tools: Optional[List[ProviderToolSpec]]`.

- [ ] **Step 5: Run the test suite to verify nothing regressed**

```bash
cd kaji/sdk
poetry run pytest -x
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/base.py \
        kaji/sdk/kaji/runtime/providers/types.py \
        kaji/sdk/tests/test_providers_translate.py
git commit -m "feat(sdk): typed Protocol with ProviderMessage/ToolSpec/ToolCall"
```

---

## Task 10: Documentation + CHANGELOG

**Files:**
- Modify: `kaji/sdk/kaji/README.md`
- Modify: `docs/MVP.md`
- Modify: `kaji/sdk/CHANGELOG.md`

**Interfaces:** docs only.

Surface all the user-visible changes: OpenRouter, slimmer settings, TextSession's `stream`/`reply_text`/`last_tool_calls`, provider constructor parity, removed GeminiService. Bump version to `0.2.0` (semver minor — breaking changes for serve callers and any external KimiProvider users).

- [ ] **Step 1: Edit README**

In `kaji/sdk/kaji/README.md` (after the existing "Install" / "Quick start" sections), add an "Providers" section that lists all five (OpenAI, Anthropic, Gemini, Kimi, OpenRouter) with a one-line install + env-var snippet each. Replace any reference to OpenRouter-via-Kimi with the new `openrouter` provider.

In the "Quick start" code block, show passing `system_prompt=` and `tools=` to `TextModalityAdapter(...)` instead of constructing `AgentRuntime` manually.

- [ ] **Step 2: Edit docs/MVP.md**

Replace any "providers: OpenAI, Anthropic, Kimi" with "providers: OpenAI, Anthropic, Gemini, Kimi, OpenRouter". Update the developer-path section to reflect that text-modality streaming is first-class via `TextSession.stream()`.

- [ ] **Step 3: Edit CHANGELOG**

Prepend a `## 0.2.0` entry under `## Unreleased`:

```markdown
## 0.2.0 — 2026-06-23

### Added
- `OpenRouterProvider` (first-class). Use `get_provider("openrouter")`.
- Constructor parity: `AnthropicProvider`, `GeminiProvider`, `OpenAIProvider`,
  `OpenRouterProvider` all accept `api_key`, `model`, `base_url` kwargs.
- `TextSession.stream()`, `TextSession.reply_text()`,
  `TextSession.last_tool_calls()`.
- `TextModalityAdapter` accepts `provider=`, `tools=`, `system_prompt=`.
- `ProviderToolCall` TypedDict; provider Protocol typed end-to-end.
- `AgentRuntime.build_planner(...)` static helper.

### Changed
- `Settings` is split into `SDKSettings` (this package) and `ServeSettings`
  (in `kaji-serve`). The SDK no longer carries DATABASE_URL,
  SUPABASE_*, JWT_*, CORS_*, or API_V1_PREFIX.
- `KimiProvider` no longer reads OpenRouter envs. Default base URL is
  Moonshot, not OpenRouter. Use `OpenRouterProvider` for OpenRouter.
- `AgentRuntime.__init__` requires `planner`. The
  `tool_executor`/`policy`/`approval_handler`/`user_id` parameters are
  removed. Build a planner with `AgentRuntime.build_planner(...)`.

### Removed
- `GeminiService` class (folded into `GeminiProvider`).
- Empty `kaji.modalities.voice.stt` subpackage.
- `Settings` class (replaced by `SDKSettings`).
```

- [ ] **Step 4: Bump version**

In `kaji/sdk/pyproject.toml:3` and `kaji/sdk/kaji/__init__.py:18`: set `0.2.0`.

- [ ] **Step 5: Run docs-sync test**

```bash
cd kaji/sdk
poetry run pytest tests/test_docs_sync.py -v
```

Expected: pass (docs-sync checks references; the test may need updates if it scans `apps/docs/content`).

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/README.md \
        docs/MVP.md \
        kaji/sdk/CHANGELOG.md \
        kaji/sdk/pyproject.toml \
        kaji/sdk/kaji/__init__.py
git commit -m "docs(sdk): document OpenRouter + TextSession + settings split for 0.2.0"
```

---

## Self-Review

**Spec coverage:** every deficiency from the 2026-06-23 review has a task:
1. OpenRouter not first-class → Task 1.
2. Kimi has wrong `X-OpenRouter-Title` header → Task 2 removes it; Task 1 uses the correct `X-Title` for the new provider.
3. Anthropic / Gemini constructors ignore arguments → Task 3 + Task 4.
4. `GeminiService` vs `GeminiProvider` split → Task 4.
5. Serve-only fields in SDK `Settings` → Task 5.
6. Empty `stt/` directory → Task 6.
7. `AgentRuntime.__init__` 13-param dual path → Task 7.
8. Text modality thin (no streaming, no convenience accessors, no system-prompt/tools knob at adapter level) → Task 8.
9. Protocol uses `List[Dict[str, Any]]` → Task 9.
10. CHANGELOG + version + docs → Task 10.

**Placeholder scan:** no `TBD`, no "implement later", no "add appropriate error handling", no untyped "similar to Task N". Every code change shows the actual code.

**Type consistency:** `ProviderToolCall` defined in Task 9 is referenced only there and in `types.py`. `AgentRuntime.build_planner` introduced in Task 7 is consumed in Task 8. `OpenRouterProvider` signature in Task 1 matches the parity contract in Task 3. `SDKSettings` from Task 5 is consumed implicitly by Task 1's `OPENROUTER_MODEL` (the new field is added in Task 1, then survives the split in Task 5 because Task 1 modifies the same `Settings` that Task 5 then renames).

**Ordering note:** Task 1 adds fields to `Settings` (the old class). Task 5 renames `Settings` to `SDKSettings`. The renamer should keep the OpenRouter fields. Reviewers should verify this in Task 5's diff.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-23-sdk-deficiencies.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute in this session with checkpoints.

Which approach?

---

## Plan Review — Engineering Lens

### Architecture findings

**A1 (P1, confidence 9/10) — Task ordering creates a settings-rename collision.**
Task 1 step 5 modifies `kaji/sdk/kaji/core/config.py:56-59` to add `OPENROUTER_MODEL` to the `Settings` class. Task 5 then deletes the entire `Settings` class and replaces it with `SDKSettings`. If both tasks land in order, the OpenRouter field must survive the rename, which Task 5 step 3 does include in the new `SDKSettings` body. The risk is real but already mitigated: the plan's Self-Review section calls out this ordering note. Recommendation: leave the ordering as-is; add a one-line assertion to Task 5 step 5 to read `assert "OPENROUTER_MODEL" in SDKSettings.model_fields` so a reordering during execution is loudly caught.

**A2 (P1, confidence 8/10) — `get_settings()` mutability is preserved.**
Both old and new config use `@lru_cache(maxsize=1)` on `get_settings()`, which means tests that monkeypatch envs must call `get_settings.cache_clear()` between asserts. The plan's tests (Task 2 step 1, Task 3 step 1) do this correctly, but Task 5 step 5 runs the full SDK suite under one process — if any earlier test left a populated cache, the split-config test will see stale fields. Recommendation: add a `pytest` autouse fixture in `tests/conftest.py` that clears `get_settings.cache_clear()` before each test. The plan does not include this; it should.

**A3 (P2, confidence 8/10) — `TextSession.stream()` lifecycle is fragile.**
Task 8 step 3 subscribes to the bus, fires `runtime.send(...)` as a task, and yields deltas until an `AgentMessageCompleted` is observed. Three concrete failure modes the current code does not handle:
1. The runtime raises before emitting any delta. `send_task` errors but the queue never receives a `None` sentinel, so the consumer hangs forever.
2. The runtime emits a `CancellationCompleted` (cancellation path) — the handler only listens for `AgentMessageCompleted`.
3. Multiple turns: if a tool call triggers a second model turn, multiple `AgentMessageCompleted` events arrive; the consumer exits after the first.

Fix: wrap `send_task` in a `try/finally` that puts a sentinel on error, listen for `CancellationCompleted` and `AgentMessageCompleted`, and accumulate until `send_task.done()` rather than first-completion.

**A4 (P2, confidence 7/10) — `InMemoryEventBus.subscribe` contract is assumed.**
Task 8 step 3 calls `await self.bus.subscribe(handler)` and `await unsubscribe()`. The plan notes "check the existing shape" in passing, but does not commit to a signature. The actual `InMemoryEventBus` (per the project memory `p0-agent-loop-public.md`) was added as part of P0 — its subscribe contract should be pinned in this task or fixed in a sub-task. Add: Task 8 step 0 should grep `kaji/sdk/kaji/infra/events/bus.py` and document the existing subscribe signature in the task body before writing the test.

**A5 (P2, confidence 7/10) — OpenRouter inherits OpenAI's `_build_messages` but not its constructor positional shape.**
`OpenRouterProvider` extends `OpenAIProvider` and calls `super().__init__(api_key=..., model=..., base_url=...)`. `OpenAIProvider.__init__` (openai.py:35-41) accepts those exact keyword names, so the call works. However, `OpenAIProvider` also caches `self._client = None` then lazily builds the client in the `client` property — `OpenRouterProvider` overrides the property to pass `default_headers`, but never resets `self._client = None` after the parent constructor sets it. The parent already sets it to None so this is fine, but the override skips calling the parent's lazy-build entirely. Confirm: the override's behavior is correct only if the parent's `client` property never ran before the override is hit. Recommendation: in `OpenRouterProvider.__init__`, explicitly assign `self._client = None` after `super().__init__()` to make the contract obvious.

### Code-quality findings

**Q1 (P2, confidence 9/10) — Task 7 removes `user_id` from `AgentRuntime` but `execute_tool` still requires it.**
`build_planner(user_id="agent")` keeps `user_id` as a planner-builder param. Good. But callers who previously passed `AgentRuntime(..., user_id="alice")` now have no way to bind a per-runtime user identity — they must construct the planner themselves. Document this migration in CHANGELOG Task 10. The plan's CHANGELOG already lists `user_id` as removed; add an example showing the migration path.

**Q2 (P3, confidence 9/10) — Duplicated `cache_clear()` calls across tests.**
Tasks 2, 3, and 5 each have tests calling `get_settings.cache_clear()`. Better: move to a conftest fixture (see A2). Reduces noise and removes a footgun if a future test forgets the call.

**Q3 (P3, confidence 8/10) — `to_openai` is reused by Kimi after the split.**
After Task 2, `KimiProvider` still imports `to_openai` from `payload.py` (line 89 in the current file). This is correct — Moonshot's API is OpenAI-compatible. Note this in the Kimi docstring so a future reader does not "fix" it.

**Q4 (P3, confidence 7/10) — Task 1's `_extra_headers` is private but tested via the dunder access.**
`provider._extra_headers()` is called from the test (Task 1 step 1). It is a leading-underscore method, which by convention means private. Either rename to `extra_headers` (public) or use a different verification (assert on `self._client.default_headers` after first access).

### Test findings

**T1 (CRITICAL, confidence 9/10) — No test for OpenRouter network behavior.**
Task 1 verifies registration and headers but does not exercise the actual chat-completions request. Because OpenRouter inherits from `OpenAIProvider`, the chat-completions path is already tested for OpenAI — but the inheritance is a contract that could silently rot. Add: a test that monkeypatches `AsyncOpenAI` and asserts `OpenRouterProvider.generate(...)` calls `chat.completions.create` with the model and headers. This is one test, not a regression risk if forgotten.

**T2 (P1, confidence 8/10) — Task 8's `last_tool_calls` test never triggers a tool call.**
The test (Task 8 step 1) calls `await session.send("hi")` against the mock provider, then asserts `isinstance(calls, list)`. The mock provider does not emit tool calls, so the list is always empty — the assertion is vacuous. Either use a fake provider that returns a tool call, or split into two tests: one asserting the empty case, one with a provider stub that returns a `tool_calls` chunk so the filter actually filters.

**T3 (P2, confidence 8/10) — Task 5 lacks a backward-compat verification on serve.**
The plan says "Run the serve test suite if touchable" (Task 5 step 6). Touchable means the serve venv is configured and `ServeSettings` is created and consumed end-to-end. The memory `serve-pytest-asyncio-auto.md` notes serve's local venv is unrunnable. Concrete consequence: serve breakage will only surface in CI. Recommendation: add a smoke-import test inside the SDK suite that does `from kaji_serve.config import ServeSettings; ServeSettings()` and asserts the migrated fields exist (guarded by `pytest.importorskip("kaji_serve")` so the SDK suite passes when serve is not installed).

**T4 (P2, confidence 7/10) — No test guards the lazy-import contract.**
`kaji/__init__.py:23-52` is a PEP-562 lazy map. Tasks 1, 3, 4 add new provider classes and constructor kwargs; none of them touch the lazy map (correctly — providers are accessed via `get_provider`, not top-level imports). But it would be cheap to add a single test: `import sys; import kaji; assert "openai" not in sys.modules and "anthropic" not in sys.modules and "google.genai" not in sys.modules`. The plan does not include this; recommend adding it to Task 9 (typing changes are the natural home).

### Performance findings

**P1 (P3, confidence 6/10) — `TextSession.stream()` uses an unbounded `asyncio.Queue`.**
With a high-volume model and slow consumer, deltas accumulate in memory unbounded. For text modality this is fine (deltas are tokens, not bytes), but worth a maxsize. Recommendation: `asyncio.Queue(maxsize=1024)`; backpressure is fine for an interactive stream.

### NOT in scope

- **Multimodal text content (images, files).** Mentioned in the review as a gap but not in this plan. The neutral payload still takes `content: str`. Bundling it would balloon Task 8 by a factor of 3.
- **STT implementation.** Task 6 only removes the empty stub; building real STT is a separate plan.
- **Gemini context-cache observability.** `GeminiProvider._active_caches` is a class-level dict; in a long-running process it grows unbounded. Out of scope; flag for follow-up.
- **`AGENT_HISTORY_LIMIT` enforcement audit.** SDK setting exists, but whether the agent loop honors it is not verified by this plan.
- **`fakeredis` test coverage of the Redis event bus** after the constructor parity work; existing tests still pass but were not extended.

### What already exists

- Neutral tool-format translation (`to_openai`, `to_anthropic`, `to_gemini` in `kaji/runtime/tools/payload.py`) — reused unchanged by the new provider.
- `OpenAIProvider.client` lazy-import pattern — Task 1 extends it.
- `register_provider` + `_BUILTINS` lazy-registry — Task 1 plugs into it.
- `AgentMessageDelta` / `AgentMessageCompleted` event schemas — Task 8 reuses them rather than introducing a new streaming protocol.
- `pytest_asyncio` auto mode — already configured at `kaji/sdk/pytest.ini`; Task 8 leans on it without re-stating.

### Failure modes per new codepath

| Codepath | Realistic failure | Test? | Error handling? | User sees |
|---|---|---|---|---|
| `OpenRouterProvider.client` | OpenAI SDK not installed | No | `ProviderConfigError` | clear install hint |
| `OpenRouterProvider._extra_headers` | None app_title with referer set | Implicit | yes | nothing (correct) |
| `KimiProvider.__init__` (Moonshot default) | env has only legacy `OPENROUTER_API_KEY` | **Yes (Task 2 step 1)** | raises | clear migration message |
| `TextSession.stream()` | runtime raises before any delta | **No (A3)** | hangs forever | indefinite spinner |
| `TextSession.stream()` | turn was cancelled | **No (A3)** | hangs | indefinite spinner |
| `TextSession.reply_text()` | turn produced no completion | Yes (test asserts non-empty) | `RuntimeError` | clear error |
| `SDKSettings()` import | none reasonable | Yes (autouse fixture would harden) | n/a | n/a |
| `GeminiProvider.__init__` | both env and constructor None | implicit | `ProviderConfigError` | clear |

**Critical gap:** A3 — `TextSession.stream()` two failure paths (provider error, cancellation) silently hang. Promote to a P1 step in Task 8.

### Worktree parallelization

Tasks 1, 6, 9 touch disjoint modules and can run in parallel (Lane A, Lane B, Lane C). Task 2 depends on Task 1 (Lane A continues). Task 3 → Task 4 sequential (both touch providers). Task 5 must come after Task 1 (or merge OpenRouter fields manually). Task 7 → Task 8 sequential (Task 8 calls `AgentRuntime.build_planner`). Task 10 last.

```
Lane A: T1 → T2 → T5 (providers + config)
Lane B: T3 → T4 (provider parity)
Lane C: T6 (delete stt)
Lane D: T7 → T8 (runtime + text)
Lane E: T9 (typed protocol)
                                  → T10 (docs)
```

A + B + C + D + E can run in parallel through mid-plan; T10 waits on all.

### Verdict (Engineering Lens)

The plan is solid. Three real issues to fix before execution:

1. **A3** — `TextSession.stream()` needs error-path + cancellation handling. Currently hangs. Promote to a P1 sub-step in Task 8.
2. **A2** — Add a `conftest.py` autouse fixture that calls `get_settings.cache_clear()` before each test. The current per-test calls work but are noisy and easy to forget.
3. **T2** — Task 8's `last_tool_calls` test is vacuous because the mock provider never emits tool calls. Add a stub-provider variant.

The other findings (A1, A4, A5, Q1-4, T1, T3, T4, P1) are improvements rather than blockers. None of them defeat the plan; they tighten it.

---

## Plan Review — CEO Lens

### Scope challenge

The plan ships 10 tasks across providers, settings split, runtime simplification, text modality polish, and typed protocol. That is a lot at once. The honest question: **does this need to be one PR?**

**Recommended split (do not block on this, but consider it):**

- **PR-A (correctness):** Task 1 (OpenRouter), Task 2 (Kimi cleanup), Task 4 (Gemini collapse). Direction-of-travel: providers. Ships cleanly, no caller breakage besides Kimi-via-OpenRouter users.
- **PR-B (refactor):** Task 3 (constructor parity), Task 7 (AgentRuntime slim), Task 9 (typed protocol). Direction: shape. Breaking changes for callers of `AgentRuntime`.
- **PR-C (DX):** Task 5 (settings split), Task 6 (delete stt), Task 8 (TextSession), Task 10 (docs). Direction: outward-facing API.

PR-A can ship immediately and unblock OpenRouter use. PR-B + PR-C can land in either order against the same minor bump.

**Recommendation:** ship as one PR if the team is small (current state) and the reviewer can hold the whole thing in head. Split if a second engineer is going to review.

### Strategic gaps

**S1 — The plan treats OpenRouter as a five-minute add-on, but OpenRouter is increasingly the "first model people try."**
With OpenRouter as a first-class provider, Kaji gains access to 200+ models behind one API key. That changes the README's positioning — "Kaji works with OpenAI, Anthropic, Gemini, Kimi" understates it. After this PR you can say "Kaji works with any model OpenRouter supports, plus first-class OpenAI/Anthropic/Gemini." Task 10's README edit should lean into this.

**S2 — The plan removes serve fields from SDK config but does not address whether `kaji-serve`'s `Settings` is itself well-shaped.**
Once `ServeSettings` is split out, the natural next question is whether the serve config is also overstuffed. Out of scope here, but flag for follow-up.

**S3 — `TextSession.stream()` is the first streaming surface in the SDK that callers can consume directly.**
Today voice is streamy via its own event registry; text is not. Once `stream()` ships, demos in `demos/web` and `demos/desktop` can show real-time text. That is a marketing moment. The plan does not call this out. Suggest: after PR lands, refresh one demo to use `stream()` and screenshot it in the README.

**S4 — Pre-1.0 means no shims, but the `KimiProvider`-via-OpenRouter flip is a real breaking change for any existing user.**
The CHANGELOG covers this, but no migration helper exists. Acceptable at pre-1.0 — but worth a one-paragraph "Migration from 0.1" section in the README rather than only in CHANGELOG.

**S5 — Distribution architecture: the SDK is shipped via Poetry → PyPI.**
The plan does not touch `kaji/sdk/CHANGELOG.md` until Task 10, and there is no mention of when/how 0.2.0 actually gets published. If 0.2.0 lands on PyPI, what is the release procedure? `poetry publish`? GitHub Actions? Add a one-line note to Task 10 step 4 about how the release is cut.

### Boring-by-default check

Every choice in the plan is boring (extend OpenAI client, use existing payload helpers, use `pydantic-settings`, keep `httpx`, no new infra). Zero innovation tokens spent. Good.

### Org-structure note

Conway's Law: the SDK and the serve package live in the same repo with separate Poetry projects. The settings split crystallizes that boundary. Good — but creates a real coordination cost: every change to `SDKSettings` requires re-checking that `ServeSettings` still inherits cleanly. Not a blocker; document it in CLAUDE.md so future contributors know the rule.

### Reversibility

- Task 1 (OpenRouter): fully reversible. New file, new registry entry.
- Task 2 (Kimi cleanup): partially reversible. If users complain, the OpenRouter dual-mode could come back as a one-line default base URL. CHANGELOG covers this.
- Task 5 (settings split): partially reversible. Re-merging is mechanical but touchy.
- Task 7 (AgentRuntime slim): hard to reverse if downstream code adopts `build_planner`.

**Recommendation:** if the team is risk-averse, land Tasks 1, 2, 4, 6, 9, 10 first (easy reversibility). Tasks 3, 5, 7, 8 in a second wave.

### Completeness check (Boil the Ocean)

The plan is complete on the items it covers. Coverage holes:

- **Image / file content for text modality** — explicitly NOT in scope, fine.
- **STT** — explicitly out of scope.
- **CHANGELOG release procedure** — implicit; add a sentence to Task 10.
- **README screenshot/demo of `stream()`** — nice-to-have, out of scope.

No items where the "complete" version is marginally more effort than the shortcut.

### Verdict (CEO Lens)

Land it. Three taste calls before execution:

1. **S5** — add one sentence to Task 10 about the release procedure (`poetry publish`, GitHub Actions tag-trigger, etc.).
2. **S1** — Task 10 README update should lead with "any model via OpenRouter" rather than listing five providers.
3. **PR split** — optional. Current shape is fine for a solo committer; split if a teammate is going to review.

---

## Cross-Model Tension

Engineering lens and CEO lens agree on: the plan is solid, three concrete fixes needed (A3, A2, T2), the rest is polish. No disagreement.

---

## Implementation Tasks (synthesized)

- [ ] **R1 (P1, CC: ~5min)** — Add `try/finally` + cancellation handling to `TextSession.stream()` in Task 8 step 3. Source: A3.
- [ ] **R2 (P1, CC: ~3min)** — Add `tests/conftest.py` with autouse fixture clearing `get_settings.cache_clear()`. Apply across Task 2/3/5. Source: A2.
- [ ] **R3 (P1, CC: ~5min)** — Replace Task 8's `last_tool_calls` test with a stub-provider that emits a tool call. Source: T2.
- [ ] **R4 (P2, CC: ~2min)** — Add assertion to Task 5 step 5 that `OPENROUTER_MODEL` survives the rename. Source: A1.
- [ ] **R5 (P2, CC: ~3min)** — Pin `InMemoryEventBus.subscribe` signature in Task 8 step 0. Source: A4.
- [ ] **R6 (P2, CC: ~5min)** — Add a network-mock test for `OpenRouterProvider.generate`. Source: T1.
- [ ] **R7 (P2, CC: ~3min)** — Add `pytest.importorskip("kaji_serve")` smoke test for `ServeSettings` to the SDK suite. Source: T3.
- [ ] **R8 (P2, CC: ~2min)** — Add a lazy-import contract test to Task 9. Source: T4.
- [ ] **R9 (P3, CC: ~1min)** — Bound `TextSession.stream()` queue at 1024. Source: P1.
- [ ] **R10 (P3, CC: ~5min)** — Task 10 step 4: name the release procedure. Source: S5.
- [ ] **R11 (P3, CC: ~5min)** — Task 10 README: lead with "any model via OpenRouter". Source: S1.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | issues_open | 5 strategic findings, 0 critical |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | issues_open | 14 findings (3 P1, 6 P2, 5 P3), 1 critical gap |

**VERDICT:** Plan is sound. Land after applying R1-R3 (three P1 fixes). R4-R11 are improvements, not blockers.

**UNRESOLVED DECISIONS:**
- PR split (one big PR vs PR-A/B/C) — taste call, defer to user
- Release procedure (`poetry publish` vs GitHub Actions) — needs user input
