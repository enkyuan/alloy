# Kaji Codebase Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `kaji/` back into alignment with the current product boundary: a pre-1.0 agent SDK with clean text/tool/session/provider foundations, service code that is honest about durability and auth, and no stale Milo/Hermes-era or third-party integration surface shipped by accident.

**Architecture:** Seven small lanes. First lock the intended product surface with tests, then remove or quarantine stale surfaces, then harden API validation/error handling, then make service durability claims honest, then fix docs and DX. No swarm work, no new integrations, no runtime rewrite unless a task explicitly says "behavioral hardening".

**Tech Stack:** Python 3.12, pytest, FastAPI, SQLAlchemy, Redis extras, TypeScript, Bun, Vitest.

## Review Inputs

- `ast-grep` broad-exception pass across `kaji/sdk/src` and `kaji/serve/src` found typed errors exist but API/service routes still collapse many failures into generic 500s.
- `ast-grep` TypeScript `throw new Error(...)` pass found repeated registry sandbox errors and generic cancellation/provider errors, mostly in TS registry/tool/provider code. Coordinate TS registry work with `docs/superpowers/plans/2026-06-29-kaji-registry-cleanup.md`.
- `cd kaji/ts && bun run test` passed: 330 passed, 6 skipped.
- `cd kaji/sdk && ./.venv/bin/python -m pytest -q` passed: 421 passed, 4 skipped. Coverage was strong in core runtime, weak or zero in realtime Redis, voice legacy, and some TTS surfaces.
- `uv` was not installed in this shell, so serve tests could not be run through the expected `uv run pytest` path here.

## Review Synthesis

- **Plan-tune:** Use direct repo evidence and existing preferences. Do not ask product-scope questions unless a task would otherwise delete live customer value.
- **CEO review:** The publishable story is "pre-beta SDK core", not "production service/realtime/voice". The shipped surface must not imply more.
- **Engineering review:** Tests first for product boundaries, then delete/quarantine. Keep provider errors centralized; do not add parallel `service_errors`.
- **DevEx review:** Stale docs and generic 500s are customer-facing defects. Fix docs parity and error details before any external recommendation.

## Global Constraints

- No behavior changes during cleanup except where a task is explicitly marked **Behavioral hardening**.
- No new third-party integrations, no swarm, no new generic node-graph features.
- Keep CamelCase public voice-modality adapter names when touching voice. Remove legacy Hermes-style names instead of aliasing them.
- Prefer deletion or quarantine over leaving legacy artifacts in the main tree.
- Test names must use current domains: `test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`.
- Use `bun` in `kaji/ts`; use the existing SDK venv in `kaji/sdk` unless a local toolchain update adds `uv`.
- Do not edit generated/cache directories: `.venv`, `node_modules`, `.turbo`, `__pycache__`, `*.pyc`, `logs`.

## Success Criteria

- Public SDK package no longer ships stale third-party integration registry modules or legacy `ToolDefinition` voice/tool modules unless they are explicitly quarantined outside the public package.
- Serve provider routes validate inputs and map typed provider/service errors to stable HTTP statuses.
- `/api/v1/tools` follows the same auth policy as other non-health service routes.
- Docs no longer claim old paths, missing TS CLI parity, or production-grade service durability where the code does not provide it.
- SDK and TS suites still pass. Serve tests pass once the serve test runner is available.

## Execution Order

```
Boundary tests -> product-surface cleanup -> API hardening -> durability/docs -> TS DRY cleanup -> final verification
```

---

### Task 1: Add product-boundary tests for stale surfaces

**Files:**
- Modify: `kaji/sdk/tests/test_package_boundaries.py`

**Interfaces:**
- Consumes: current source tree and `pyproject.toml`.
- Produces: failing tests that force intentional cleanup instead of silent shipping.

- [ ] **Step 1: Add a test banning third-party integration registry packages from the SDK**

Append:

```python
def test_sdk_does_not_ship_third_party_integration_registry() -> None:
    """Third-party integration examples must not be packaged as SDK surface."""
    registry_root = PACKAGE_ROOT / "integrations" / "registry"
    forbidden = {"github", "gmail", "gcal"}
    shipped = {
        path.name
        for path in registry_root.iterdir()
        if path.is_dir() and path.name in forbidden
    } if registry_root.exists() else set()

    assert shipped == set(), (
        "Third-party integration registry modules are shipped in the SDK: "
        + ", ".join(sorted(shipped))
    )
```

- [ ] **Step 2: Add a test banning legacy ToolDefinition from the public SDK package**

Append:

```python
def test_sdk_does_not_ship_legacy_tooldefinition_surface() -> None:
    legacy_paths = [
        PACKAGE_ROOT / "types" / "tool.py",
        PACKAGE_ROOT / "modalities" / "voice" / "legacy",
    ]
    shipped = [str(path.relative_to(PACKAGE_ROOT)) for path in legacy_paths if path.exists()]

    assert shipped == [], (
        "Legacy ToolDefinition surfaces are still packaged: "
        + ", ".join(shipped)
    )
```

- [ ] **Step 3: Run the focused failing tests**

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_package_boundaries.py -q
```

Expected before Task 2 and Task 3: the two new tests fail. If they pass before cleanup, inspect whether the stale files were already removed on another branch.

---

### Task 2: Quarantine or delete third-party integration registry modules

**Files:**
- Delete or move out of package: `kaji/sdk/src/integrations/registry/github/`
- Delete or move out of package: `kaji/sdk/src/integrations/registry/gmail/`
- Delete or move out of package: `kaji/sdk/src/integrations/registry/gcal/`
- Modify: `kaji/sdk/pyproject.toml`
- Modify: `kaji/sdk/tests/test_integrations_registry.py`
- Modify: `kaji/sdk/tests/test_integrations_registry_echo.py`
- Modify docs that mention third-party Python integrations.

**Interfaces:**
- Keeps: the internal `Integration` abstraction if still needed by examples or future registry work.
- Removes: concrete third-party registry code from the SDK package.

- [ ] **Step 1: Decide location**

Default: delete the third-party directories. If product still needs examples, move them under a non-packaged docs/examples path and mark them non-runtime.

- [ ] **Step 2: Remove packaging entries**

In `kaji/sdk/pyproject.toml`, remove concrete package entries and package-data paths that ship `kaji.integrations.registry.github`, `gmail`, or `gcal`. Keep only first-party abstractions that tests prove are still used.

- [ ] **Step 3: Update tests**

Delete or rewrite tests that import the removed third-party modules. Keep echo/scaffold tests only if echo remains first-party and packaged.

- [ ] **Step 4: Verify**

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_package_boundaries.py tests/test_integrations_registry.py tests/test_integrations_registry_echo.py -q
```

---

### Task 3: Remove legacy ToolDefinition voice/tool surface

**Files:**
- Delete: `kaji/sdk/src/types/tool.py`
- Delete: `kaji/sdk/src/types/__init__.py` if the package becomes empty
- Delete: `kaji/sdk/src/modalities/voice/legacy/tool_definition.py`
- Delete: `kaji/sdk/src/modalities/voice/legacy/system_tools.py`
- Delete: `kaji/sdk/src/modalities/voice/legacy/__init__.py` if the package becomes empty
- Modify: `kaji/sdk/pyproject.toml`
- Modify: `kaji/sdk/tests/test_public_api.py`
- Modify: `kaji/sdk/tests/test_public_surface.py`

**Interfaces:**
- Keeps: current `ToolSpec`, `ToolRegistry`, `function_tool`, `tool`.
- Removes: deprecated `ToolDefinition` and voice legacy imports.

- [ ] **Step 1: Search for live imports**

```bash
rg -n "ToolDefinition|kaji\\.types\\.tool|modalities\\.voice\\.legacy" kaji/sdk kaji/serve kaji/ts
```

Expected after cleanup: no live source imports. Historical plan files may still mention these terms.

- [ ] **Step 2: Remove files and package entries**

Remove `kaji.types` and `kaji.modalities.voice.legacy` from `kaji/sdk/pyproject.toml` package lists.

- [ ] **Step 3: Verify**

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_package_boundaries.py tests/test_public_api.py tests/test_public_surface.py -q
```

---

### Task 4: Harden provider API validation and typed error mapping

**Behavioral hardening:** invalid provider input should return 422; typed provider/service failures should return 401, 429, 503, or 502 instead of always 500.

**Files:**
- Modify: `kaji/serve/src/server/v1/providers.py`
- Modify: `kaji/serve/tests/test_api_providers.py`

**Interfaces:**
- Consumes: `kaji.runtime.providers.errors.ServiceError`, `service_error_to_detail`, `service_error_to_http_status`.
- Produces: stable FastAPI responses without creating a parallel service-error module.

- [ ] **Step 1: Add request bounds**

Use:

```python
from typing import Any, Literal, NoReturn
from pydantic import BaseModel, Field
```

Then set:

```python
MAX_PROMPT_CHARS = 20_000
MAX_CHAT_MESSAGES = 128
MAX_OUTPUT_TOKENS = 8_192


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    system_instruction: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=MAX_OUTPUT_TOKENS)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    system_instruction: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
```

- [ ] **Step 2: Map typed service/provider errors**

Add:

```python
from kaji.runtime.providers.errors import (
    ServiceError,
    service_error_to_detail,
    service_error_to_http_status,
)


def _raise_service_http_error(detail: str, *, error: ServiceError) -> NoReturn:
    logger.warning("%s: %s", detail, error, exc_info=True)
    raise HTTPException(
        status_code=service_error_to_http_status(error),
        detail=service_error_to_detail(error, fallback=detail),
    ) from error
```

Catch `ServiceError` before the broad `Exception` in all three provider endpoints.

- [ ] **Step 3: Add tests**

Add tests for:
- empty prompt returns 422
- invalid chat role returns 422
- provider rate limit returns 429 with safe detail
- provider network failure returns 503 with safe detail

Use existing `mock_gemini_service` and import `ServiceNetworkError`, `ServiceRateLimitError`.

- [ ] **Step 4: Verify**

```bash
cd kaji/serve
uv run pytest tests/test_api_providers.py -q
```

If `uv` is still missing locally, record that as an environment blocker and run through the repo-approved serve environment.

---

### Task 5: Require auth for tool discovery

**Behavioral hardening:** `/api/v1/tools` becomes authenticated like cache metrics and cache clear.

**Files:**
- Modify: `kaji/serve/src/server/v1/tools.py`
- Modify: `kaji/serve/tests/test_api_tools.py`

**Interfaces:**
- Consumes: `get_current_supabase_user`.
- Produces: no unauthenticated tool schema discovery.

- [ ] **Step 1: Change route signature**

```python
@router.get("")
async def list_tools(_: dict = Depends(get_current_supabase_user)):
    """List available Agent tool definitions."""
```

- [ ] **Step 2: Update tests**

Change the happy-path test to use `mock_current_user` and an auth header. Add an unauthenticated test:

```python
@pytest.mark.asyncio
async def test_api_tools_list_tools_requires_auth(async_client: AsyncClient):
    response = await async_client.get("/api/v1/tools")
    assert response.status_code in {401, 403}
```

- [ ] **Step 3: Verify**

```bash
cd kaji/serve
uv run pytest tests/test_api_tools.py -q
```

---

### Task 6: Make service durability claims match implementation

**Files:**
- Modify: `kaji/README.md`
- Modify: `kaji/serve/README.md`
- Modify: `kaji/serve/src/server/v1/sessions.py` only if an inline comment prevents future misuse.
- Optional follow-up plan: persistent `EventStore` implementation for serve.

**Interfaces:**
- Current implementation: `sessions.py` builds `SessionManager(InMemoryEventStore(), session_store=PostgresSessionStore(db))`.
- Current docs claim: Redis Streams / durable backend for service runtime.

- [ ] **Step 1: Update docs now**

State that service session listing is durable metadata through Postgres, while SDK event replay is in-memory unless the caller supplies a persistent `EventStore`.

- [ ] **Step 2: Add a follow-up event-store plan if production service replay is required**

The follow-up should specify either:
- `PostgresEventStore` over a new `conversation_events` table and Alembic migration, or
- `RedisStreamEventStore` over existing realtime primitives.

Do not wire this by improvising inside `sessions.py`; durable event replay is a system design task.

- [ ] **Step 3: Verify docs**

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_docs_sync.py -q
```

---

### Task 7: Fix docs parity and stale links

**Files:**
- Modify: `kaji/README.md`
- Modify: `kaji/sdk/README.md`
- Modify: `kaji/ts/README.md`
- Modify: `kaji/sdk/tests/test_docs_sync.py`

**Issues to fix:**
- `kaji/README.md` references old `sdk/kaji/...` paths; actual Python SDK source is under `kaji/sdk/src/...`.
- `kaji/ts/README.md` links `../MVP.md`; actual file is `docs/MVP.md`.
- TS README says CLI scaffold is not ported while the package has CLI commands and tests.
- SDK/package docs should call the core SDK pre-beta and avoid implying realtime/voice/service production hardening.

- [ ] **Step 1: Fix text and links**

Use relative paths that exist from each README.

- [ ] **Step 2: Add doc sync assertions**

Extend `test_docs_sync.py` with targeted path checks:

```python
def test_docs_reference_existing_kaji_paths() -> None:
    missing: list[str] = []
    for path in USER_FACING_DOCS:
        text = path.read_text()
        for match in re.findall(r"`([^`]+)`", text):
            if match.startswith(("kaji/", "sdk/", "ts/", "docs/")):
                candidate = (path.parent / match).resolve()
                repo_candidate = (REPO_ROOT / match).resolve()
                if not candidate.exists() and not repo_candidate.exists():
                    missing.append(f"{path.relative_to(REPO_ROOT)}: {match}")
    assert missing == []
```

Adjust the matcher if it catches command snippets instead of paths.

- [ ] **Step 3: Verify**

```bash
cd kaji/sdk
./.venv/bin/python -m pytest tests/test_docs_sync.py -q
```

---

### Task 8: Quarantine legacy node-graph runtime if unused

**Files:**
- Inspect: `kaji/serve/src/runtime/messaging/`
- Inspect: `kaji/serve/src/runtime/nodes/`
- Inspect: `kaji/serve/src/workers/main.py`
- Modify only after usage is clear.

**Interfaces:**
- `AgentReasoningNode` is tested and used by workers.
- `Bridge`, `Bus`, `RouteBuilder`, and `ReasoningNode` are large, partly legacy, and carry TODOs.

- [ ] **Step 1: Usage map**

```bash
rg -n "Bridge|Bus|RouteBuilder|ReasoningNode|AgentReasoningNode" kaji/serve/src kaji/serve/tests
```

- [ ] **Step 2: Decide**

If `Bridge`/`Bus`/`RouteBuilder` are only worker internals, keep them under service-only runtime and add tests around the active worker path. If any module is unused, delete it. If it is experimental, move it under an explicit experimental namespace and remove public exports.

- [ ] **Step 3: Verify**

```bash
cd kaji/serve
uv run pytest tests/test_agents_node_infra_free.py tests/test_workers_tts_publish.py -q
```

---

### Task 9: DRY TS registry sandbox errors without changing behavior

**Files:**
- Modify: `kaji/ts/registry/fs/index.ts`
- Modify tests only if messages are asserted.

**Interfaces:**
- Keep existing sandbox behavior and error text.
- Extract only repeated path escape checks.

- [ ] **Step 1: Add helper**

Add a local helper such as:

```ts
function assertInsideSandbox(target: string, root: string, operation: string): void {
  if (!target.startsWith(root)) {
    throw new Error(`${operation} path escapes sandbox`);
  }
}
```

Use the exact existing error messages if tests or docs depend on them.

- [ ] **Step 2: Verify**

```bash
cd kaji/ts
bun run test tests/registry.fs.test.ts
```

---

## Final Verification

Run:

```bash
cd kaji/sdk && ./.venv/bin/python -m pytest -q
cd ../ts && bun run test
cd ../serve && uv run pytest -q
```

If serve still cannot run because `uv` is unavailable in the local shell, record that explicitly and do not claim serve verification.

## Expected Outcome

After this plan lands, Kaji is much easier to explain: the Python and TS SDK cores are credible pre-beta packages; stale integration and legacy voice/tool surfaces are gone or quarantined; service APIs have safer validation, auth, and error behavior; docs stop overstating durability and parity. Production-grade service replay/realtime/voice can then be planned as explicit system work instead of being implied by leftover code.
