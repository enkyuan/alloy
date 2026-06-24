# SDK DX + Docs Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the non-voice engineering DX gaps identified in the SDK assessment (`@kaji/sdk` TS parity, `kaji` Python typing/import ergonomics) and the documentation gaps (CLI page, install commands, API reference, troubleshooting, reference-service runbook, events enum inlining).

**Architecture:** Two work streams. (1) SDK DX: widen TS peer-dep ranges, add `py.typed`, port `request_payment` HTTP tool into both SDKs as an opt-in helper, slim Python public lazy map. (2) Docs: add CLI/troubleshooting/runtime-API/install pages, inline the event enum, register them in fumadocs `meta.json`. Tasks are mostly independent so subagents can run sequentially without cross-task locking.

**Tech Stack:** TypeScript (tsup, vitest, Node ≥22), Python 3.11+ (poetry, pytest, pyrefly), fumadocs MDX.

## Global Constraints

- **Branch:** all work on `feat/sdk-dx-and-docs` (new), never on `main`.
- **No voice modality work** — the user explicitly excluded STT/TTS/barge-in/VAD. Do not touch `kaji/sdk/kaji/modalities/voice/**` or anything that loads it.
- **No new heavy dependencies** anywhere. TS: only the `peerDependencies` already declared. Python: only the optional extras already declared (`anthropic`, `openai`, `gemini`, `realtime`, etc.) plus stdlib.
- **TS sources:** `kaji/ts/src/**`. TS tests: `kaji/ts/tests/**`.
- **Python SDK sources:** `kaji/sdk/kaji/**`. Python tests: `kaji/sdk/tests/**`.
- **Docs:** `apps/docs/content/**` (fumadocs MDX). Sidebar order is controlled by `meta.json` files — every new page must be registered.
- **No em-dashes** in any user-facing copy, docs, or template strings. Use `--` or `-` or a comma instead.
- **DRY across CLIs:** the existing `kaji` CLI shipped in PR #18 — refer to it from docs but do not duplicate its `--help` output verbatim into prose.
- **Tests required.** Each code task ends with TDD evidence (RED + GREEN). Doc-only tasks end with a lint/build pass.
- **Bun for TS package ops.** Never `npm install` or `yarn install`. Use `bun --filter @kaji/sdk` for SDK ops, `bun --filter @kaji/cli` for CLI ops.

---

## File Structure

### TS SDK (`kaji/ts/`)

**Modify:**
- `kaji/ts/package.json` — relax `peerDependencies` ranges; the current `openai@^6.42.0` and `@anthropic-ai/sdk@^0.104.1` are too narrow.

**Create:**
- `kaji/ts/src/tools/payment.ts` — `requestPayment` factory returning a `ToolSpec` + handler that POSTs to an ryo base URL. Infra-free, fetch-based, optional.
- `kaji/ts/tests/tools/payment.test.ts` — vitest covering the factory.

### Python SDK (`kaji/sdk/`)

**Create:**
- `kaji/sdk/kaji/py.typed` — PEP 561 marker (empty file).
- `kaji/sdk/kaji/runtime/tools/payment.py` — `request_payment` builder, parallel to TS.
- `kaji/sdk/tests/test_tools_payment.py` — pytest covering the builder.

**Modify:**
- `kaji/sdk/pyproject.toml` — add `include = ["kaji/py.typed"]` so the marker is shipped in the wheel.
- `kaji/sdk/kaji/__init__.py` — lazy-export `RequestPaymentTool` / `request_payment_tool`.
- `kaji/sdk/kaji/runtime/tools/__init__.py` — re-export the new builder.

### Docs (`apps/docs/content/`)

**Create:**
- `apps/docs/content/cli.mdx` — single-page CLI reference (commands + flags + the parity gap with `mcp`).
- `apps/docs/content/install.mdx` — install + version policy + provider-extras matrix.
- `apps/docs/content/troubleshooting.mdx` — top failure modes.
- `apps/docs/content/concepts/runtime.mdx` — API reference for `AgentBuilder` / `AgentRuntime.send` / `history` / `subscribe`.

**Modify:**
- `apps/docs/content/concepts/events.mdx` — inline the event-type enum table.
- `apps/docs/content/reference-service.mdx` — add real run commands.
- `apps/docs/content/getting-started.mdx` — replace `cd kaji/sdk && poetry install` with the published-package commands; cross-link CLI page.
- `apps/docs/content/meta.json` — register `install`, `cli`, `troubleshooting`.
- `apps/docs/content/concepts/meta.json` — add `runtime`.

---

### Task 1: branch + CI baseline

**Files:** none modified; ensures everyone starts clean.

**Interfaces:**
- Consumes: nothing.
- Produces: branch `feat/sdk-dx-and-docs` checked out from `origin/main`. Sets `BASE_SHA` for downstream review-package generation.

- [ ] **Step 1: Sync main and branch**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git checkout main
git pull --ff-only origin main
git checkout -b feat/sdk-dx-and-docs
git push -u origin feat/sdk-dx-and-docs
```

- [ ] **Step 2: Confirm baseline tests pass before any changes**

Run from repo root:
```bash
bun --filter @kaji/sdk test
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -3
```
Expected: TS SDK tests pass; Python `tests/` non-integration suite passes. If anything is red here, STOP and escalate — do not start tasks on a broken baseline.

---

### Task 2: TS peer-dep range widening

**Files:**
- Modify: `kaji/ts/package.json:38-50`

**Interfaces:**
- Consumes: nothing.
- Produces: relaxed `peerDependencies` so consumers on newer OpenAI/Anthropic SDK majors don't hit peer-dep warnings.

The current declaration:
```json
"peerDependencies": {
  "zod": "^4.3.6",
  "openai": "^6.42.0",
  "@anthropic-ai/sdk": "^0.104.1"
}
```

The provider source files use only the public top-level types from each SDK (`OpenAI`, `Anthropic`). Verify by reading `kaji/ts/src/providers/openai.ts` and `anthropic.ts` (lazy imports, no deep submodule paths). Widen ranges to accept any future major-compatible version the consumer pins. The pattern `>=X.Y <next-major+1` keeps the lower bound and removes the artificial upper.

- [ ] **Step 1: Inspect the provider files to confirm no deep imports**

```bash
grep -nE "from \"openai/|from \"@anthropic-ai/sdk/" kaji/ts/src/providers/*.ts
```
Expected: no matches. Only top-level imports are used.

- [ ] **Step 2: Widen the ranges**

Edit `kaji/ts/package.json` so the `peerDependencies` block reads:

```json
"peerDependencies": {
  "zod": ">=3.23 <5",
  "openai": ">=4 <8",
  "@anthropic-ai/sdk": ">=0.30 <2"
}
```

Rationale, one line per dep:
- `zod`: SDK uses `z.object` / `z.infer` (stable since v3). Allow v3 and v4.
- `openai`: SDK uses `new OpenAI({ apiKey, baseURL })` + `client.chat.completions.create(...)` — stable since v4. Allow v4 through any v7.
- `@anthropic-ai/sdk`: SDK uses `new Anthropic({ apiKey })` + `client.messages.create(...)` / `stream(...)` — stable across the 0.x line.

Keep the same entries in `peerDependenciesMeta` (both optional).

- [ ] **Step 3: Rebuild and re-run tests**

```bash
bun --filter @kaji/sdk build
bun --filter @kaji/sdk test
```
Expected: build clean, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add kaji/ts/package.json
git commit -m "fix(ts-sdk): widen openai/anthropic/zod peer-dep ranges"
```

---

### Task 3: Python `py.typed` marker

**Files:**
- Create: `kaji/sdk/kaji/py.typed` (empty)
- Modify: `kaji/sdk/pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: published wheel advertises type information per PEP 561.

- [ ] **Step 1: Create the marker file**

```bash
touch /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/sdk/kaji/py.typed
```

- [ ] **Step 2: Tell poetry to include it in the wheel**

In `kaji/sdk/pyproject.toml`, in the `[tool.poetry]` block, change:

```toml
packages = [{ include = "kaji" }]
```

to:

```toml
packages = [{ include = "kaji" }]
include = [{ path = "kaji/py.typed", format = ["sdist", "wheel"] }]
```

(Append `include` immediately after `packages`. Do not collapse them onto one line.)

- [ ] **Step 3: Confirm poetry sees it**

```bash
cd kaji/sdk && poetry check && poetry build 2>&1 | tail -5
```
Expected: `poetry check` returns "All set!", and the build output mentions the new file. After the build inspect:

```bash
python -c "import zipfile; z=zipfile.ZipFile(sorted(__import__('pathlib').Path('kaji/sdk/dist').glob('*.whl'))[-1]); print('\n'.join(n for n in z.namelist() if 'py.typed' in n))"
```
Expected: prints `kaji/py.typed`.

- [ ] **Step 4: Clean up the dist artifacts**

```bash
rm -rf kaji/sdk/dist
```

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/kaji/py.typed kaji/sdk/pyproject.toml
git commit -m "feat(py-sdk): ship py.typed for PEP 561 compliance"
```

---

### Task 4: slim the Python public lazy map

**Files:**
- Modify: `kaji/sdk/kaji/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a curated public surface where `import kaji; kaji.<TAB>` shows the names a first-time reader actually needs. Internal-only names remain importable from their subpackages but disappear from the top-level autocomplete.

The current `_LAZY` map has ~30 entries. We trim it to the 18 a v0.1.0 user genuinely composes against. Anything still importable from `kaji.runtime.*` etc. stays accessible — we are not deleting code, just narrowing what `kaji.<TAB>` and `dir(kaji)` surface.

Names to KEEP in `_LAZY` (the "what you compose with" surface):

```
AgentBuilder
AgentRuntime
CancellationToken
EventBus
EventStore
InMemoryEventBus
InMemoryEventStore
UserMessage
FunctionTool
Integration
Tool
ToolContext
ToolRegistry
ToolSpec
RegisterTool
ListToolSpecs
ModelProvider
GetProvider
RegisterProvider
ProviderError
ProviderConfigError
ProviderAPIError
ReplaySession
SessionManager
SessionState
```

Names to REMOVE from `_LAZY` (still importable from `kaji.runtime.*` but no longer top-level):
- `AgentStrategy` (strategy hook, niche)
- `ToolPlanner`, `ToolExecutor` (internal building blocks of `AgentRuntime`)
- `EventBusProtocol` (protocol type, not used by app code)
- `EventType` (use string literals or the schemas module)
- `KajiEvent`, `BaseEvent` (read schemas directly if needed)
- `BoundTool` (internal)
- `InMemorySessionStore`, `SessionStore`, `SessionRecord` (session backing detail)
- `ToolSpecFromModel`, `ExecuteTool`, `ClearTools` (registry internals)
- `ToolPolicy`, `ToolPolicyViolation` (advanced, not v0.1.0 path)

- [ ] **Step 1: Add the regression test FIRST**

Create `kaji/sdk/tests/test_public_surface.py`:

```python
"""Pin the kaji top-level public surface so additions are deliberate."""
from __future__ import annotations

import kaji


EXPECTED_PUBLIC = {
    "AgentBuilder",
    "AgentRuntime",
    "CancellationToken",
    "EventBus",
    "EventStore",
    "InMemoryEventBus",
    "InMemoryEventStore",
    "UserMessage",
    "FunctionTool",
    "Integration",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "RegisterTool",
    "ListToolSpecs",
    "ModelProvider",
    "GetProvider",
    "RegisterProvider",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAPIError",
    "ReplaySession",
    "SessionManager",
    "SessionState",
    "ToolSpec",
}


def test_public_surface_is_pinned() -> None:
    public = {n for n in dir(kaji) if not n.startswith("_") and n != "TYPE_CHECKING"}
    # __version__ is the only non-LAZY exported name.
    public -= {"__version__"}
    assert public == EXPECTED_PUBLIC, sorted(public ^ EXPECTED_PUBLIC)


def test_each_public_name_resolves() -> None:
    for name in EXPECTED_PUBLIC:
        getattr(kaji, name)  # raises if the lazy module is broken


def test_internal_names_still_importable_from_subpackages() -> None:
    # Things removed from the top-level lazy map must still be importable
    # from their canonical subpackage.
    from kaji.runtime.agents import AgentStrategy
    from kaji.runtime.agents.planner import ToolPlanner, ToolExecutor
    from kaji.runtime.sessions.store import (
        InMemorySessionStore,
        SessionStore,
        SessionRecord,
    )
    from kaji.runtime.tools.registry import (
        ExecuteTool,
        ClearTools,
        ToolSpecFromModel,
    )
    from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation

    # Trivial assertions just to suppress unused-import linters and prove the
    # imports executed.
    assert callable(ToolPlanner) or ToolPlanner is not None
    assert SessionStore is not None
    assert ToolPolicy is not None
```

- [ ] **Step 2: Confirm the test fails against the current wide map**

```bash
cd kaji/sdk && poetry run pytest tests/test_public_surface.py -v
```
Expected: `test_public_surface_is_pinned` FAILS because the current `_LAZY` has names we no longer want exposed.

- [ ] **Step 3: Trim the lazy map**

Edit `kaji/sdk/kaji/__init__.py`. Replace the `_LAZY` dict so it contains exactly these 25 entries (alphabetised by key):

```python
_LAZY: dict[str, str] = {
    "AgentBuilder": "kaji.runtime.agents",
    "AgentRuntime": "kaji.runtime.agents",
    "CancellationToken": "kaji.runtime.agents",
    "EventBus": "kaji.infra.events",
    "EventStore": "kaji.infra.events",
    "FunctionTool": "kaji.runtime.integrations",
    "GetProvider": "kaji.runtime.providers",
    "InMemoryEventBus": "kaji.infra.events",
    "InMemoryEventStore": "kaji.infra.events",
    "Integration": "kaji.runtime.integrations",
    "ListToolSpecs": "kaji.runtime.tools.registry",
    "ModelProvider": "kaji.runtime.providers",
    "ProviderAPIError": "kaji.runtime.providers.errors",
    "ProviderConfigError": "kaji.runtime.providers.errors",
    "ProviderError": "kaji.runtime.providers.errors",
    "RegisterProvider": "kaji.runtime.providers",
    "RegisterTool": "kaji.runtime.tools.registry",
    "ReplaySession": "kaji.runtime.sessions",
    "SessionManager": "kaji.runtime.sessions",
    "SessionState": "kaji.runtime.sessions",
    "Tool": "kaji.runtime.integrations",
    "ToolContext": "kaji.runtime.tools.registry",
    "ToolRegistry": "kaji.runtime.tools.registry",
    "ToolSpec": "kaji.runtime.tools.registry",
    "UserMessage": "kaji.infra.events",
}
```

Leave the rest of the file untouched (the `__getattr__`, `__dir__`, `__all__` lines).

- [ ] **Step 4: Run the new regression test + the full Python suite**

```bash
cd kaji/sdk && poetry run pytest tests/test_public_surface.py -v
poetry run pytest -q --ignore=tests/integration 2>&1 | tail -5
```
Expected: `test_public_surface.py` 3/3 pass; full suite passes (or matches pre-task baseline — note the baseline pass count first).

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/kaji/__init__.py kaji/sdk/tests/test_public_surface.py
git commit -m "refactor(py-sdk): slim public lazy map to v0.1.0 surface"
```

---

### Task 5: TS `requestPayment` tool builder

**Files:**
- Create: `kaji/ts/src/tools/payment.ts`
- Create: `kaji/ts/tests/tools/payment.test.ts`
- Modify: `kaji/ts/src/index.ts`

**Interfaces:**
- Consumes: `ToolSpec`, `ToolHandler` from `../tools/registry`.
- Produces:
  - `requestPayment(options: { baseUrl: string; apiKey?: string; fetchImpl?: typeof fetch }): { spec: ToolSpec; handler: ToolHandler }`
  - The handler POSTs `{ amount, description, ... }` to `${baseUrl}/v1/sessions` with optional `Authorization: Bearer <apiKey>` and returns the parsed JSON.

This is the ryo/kaji bridge promised in Roadmap item 12, but infra-free: no Stripe SDK, no axios, just `fetch`. The ryo API is still MISSING per the roadmap, so we ship the tool builder against the documented contract and the test mocks `fetch` rather than hitting a live service.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/tools/payment.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { requestPayment } from "../../src/tools/payment";

describe("requestPayment", () => {
  it("builds a ToolSpec with name and required params", () => {
    const { spec } = requestPayment({ baseUrl: "https://api.example.com" });
    expect(spec.name).toBe("request_payment");
    const params = spec.parameters as Record<string, unknown>;
    expect(params.required).toEqual(["amount", "description"]);
    const props = params.properties as Record<string, { type: string }>;
    expect(props.amount.type).toBe("integer");
    expect(props.description.type).toBe("string");
  });

  it("posts to <baseUrl>/v1/sessions with the args as JSON", async () => {
    const fakeFetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("https://api.example.com/v1/sessions");
      expect(init?.method).toBe("POST");
      expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
      expect(JSON.parse(init?.body as string)).toEqual({ amount: 1500, description: "Coffee" });
      return new Response(JSON.stringify({ checkoutUrl: "https://pay/abc" }), { status: 200 });
    }) as unknown as typeof fetch;

    const { handler } = requestPayment({
      baseUrl: "https://api.example.com",
      fetchImpl: fakeFetch,
    });
    const ctx = { userId: "u1", db: null } as never;
    const result = await handler(ctx, { amount: 1500, description: "Coffee" });
    expect(result).toEqual({ checkoutUrl: "https://pay/abc" });
    expect(fakeFetch).toHaveBeenCalledOnce();
  });

  it("includes Authorization header when apiKey provided", async () => {
    const fakeFetch = vi.fn(async (_url: string, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer sk-test");
      return new Response("{}", { status: 200 });
    }) as unknown as typeof fetch;

    const { handler } = requestPayment({
      baseUrl: "https://x",
      apiKey: "sk-test",
      fetchImpl: fakeFetch,
    });
    await handler({} as never, { amount: 1, description: "x" });
  });

  it("throws on non-2xx response with the status code in the message", async () => {
    const fakeFetch = vi.fn(
      async () => new Response("nope", { status: 502, statusText: "Bad Gateway" }),
    ) as unknown as typeof fetch;

    const { handler } = requestPayment({ baseUrl: "https://x", fetchImpl: fakeFetch });
    await expect(handler({} as never, { amount: 1, description: "x" })).rejects.toThrow(/502/);
  });
});
```

- [ ] **Step 2: Run to confirm failure**

```bash
bun --filter @kaji/sdk test tests/tools/payment.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the builder**

Create `kaji/ts/src/tools/payment.ts`:

```ts
/**
 * requestPayment: a thin kaji -> ryo bridge.
 *
 * Posts to `${baseUrl}/v1/sessions` and returns the JSON payload. Pass a
 * custom fetchImpl in tests; in production it uses the global fetch.
 */
import type { ToolSpec, ToolHandler, ToolContext } from "./registry";

export interface RequestPaymentOptions {
  baseUrl: string;
  apiKey?: string;
  fetchImpl?: typeof fetch;
}

export interface RequestPaymentTool {
  spec: ToolSpec;
  handler: ToolHandler;
}

export function requestPayment(opts: RequestPaymentOptions): RequestPaymentTool {
  const spec: ToolSpec = {
    name: "request_payment",
    description: "Request a payment via ryo. Returns the checkout URL.",
    parameters: {
      type: "object",
      properties: {
        amount: { type: "integer", description: "Amount in the smallest currency unit (cents)." },
        description: { type: "string", description: "Short reason shown to the payer." },
      },
      required: ["amount", "description"],
    },
    risk: "write",
  };

  const fetchImpl = opts.fetchImpl ?? globalThis.fetch;

  const handler: ToolHandler = async (_ctx: ToolContext, args: Record<string, unknown>) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (opts.apiKey) headers.Authorization = `Bearer ${opts.apiKey}`;
    const url = `${opts.baseUrl.replace(/\/$/, "")}/v1/sessions`;
    const r = await fetchImpl(url, { method: "POST", headers, body: JSON.stringify(args) });
    if (!r.ok) {
      throw new Error(`ryo POST /v1/sessions failed: ${r.status} ${r.statusText}`);
    }
    return r.json();
  };

  return { spec, handler };
}
```

- [ ] **Step 4: Export from the public index**

In `kaji/ts/src/index.ts`, append to the tools-export block (after the `executeTool, clearTools` line):

```ts
export { requestPayment } from "./tools/payment";
export type { RequestPaymentOptions, RequestPaymentTool } from "./tools/payment";
```

- [ ] **Step 5: Run tests**

```bash
bun --filter @kaji/sdk test tests/tools/payment.test.ts
bun --filter @kaji/sdk test
```
Expected: 4/4 new tests pass; full suite still green.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/tools/payment.ts kaji/ts/tests/tools/payment.test.ts kaji/ts/src/index.ts
git commit -m "feat(ts-sdk): add requestPayment ryo bridge tool"
```

---

### Task 6: Python `request_payment` tool builder

**Files:**
- Create: `kaji/sdk/kaji/runtime/tools/payment.py`
- Create: `kaji/sdk/tests/test_tools_payment.py`
- Modify: `kaji/sdk/kaji/runtime/tools/__init__.py`
- Modify: `kaji/sdk/kaji/__init__.py` (add to `_LAZY`)

**Interfaces:**
- Consumes: `ToolSpec`, `ToolContext` from `kaji.runtime.tools.registry`.
- Produces:
  - `RequestPaymentTool(base_url: str, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> tuple[ToolSpec, Callable]`
  - Handler signature: `async def handler(ctx: ToolContext, args: dict) -> dict`.

Parity with the TS implementation. `httpx` is already a hard SDK dep, so no new requirements.

- [ ] **Step 1: Write the failing test**

Create `kaji/sdk/tests/test_tools_payment.py`:

```python
"""Tests for the ryo bridge tool."""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from kaji.runtime.tools.payment import RequestPaymentTool


@pytest.mark.asyncio
async def test_request_payment_builds_spec() -> None:
    spec, _handler = RequestPaymentTool(base_url="https://api.example.com")
    assert spec.name == "request_payment"
    props = spec.parameters["properties"]
    assert props["amount"]["type"] == "integer"
    assert props["description"]["type"] == "string"
    assert spec.parameters["required"] == ["amount", "description"]


@pytest.mark.asyncio
async def test_request_payment_posts_to_sessions_endpoint() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content.decode())))
        return httpx.Response(200, json={"checkoutUrl": "https://pay/abc"})

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(base_url="https://api.example.com", client=client)
        result = await handler(ctx=None, args={"amount": 1500, "description": "Coffee"})
        assert result == {"checkoutUrl": "https://pay/abc"}
        assert calls == [
            ("https://api.example.com/v1/sessions", {"amount": 1500, "description": "Coffee"}),
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_payment_sends_authorization_header() -> None:
    captured: dict[str, str] = {}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(
            base_url="https://x", api_key="sk-test", client=client
        )
        await handler(ctx=None, args={"amount": 1, "description": "x"})
        assert captured["authorization"] == "Bearer sk-test"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_payment_raises_on_non_2xx() -> None:
    def transport_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(base_url="https://x", client=client)
        with pytest.raises(RuntimeError, match="502"):
            await handler(ctx=None, args={"amount": 1, "description": "x"})
    finally:
        await client.aclose()
```

- [ ] **Step 2: Confirm failure**

```bash
cd kaji/sdk && poetry run pytest tests/test_tools_payment.py -v
```
Expected: collection error — `kaji.runtime.tools.payment` does not exist.

- [ ] **Step 3: Implement**

Create `kaji/sdk/kaji/runtime/tools/payment.py`:

```python
"""`request_payment`: the ryo bridge tool.

Returns a (ToolSpec, handler) pair. The handler POSTs the args to
``<base_url>/v1/sessions`` and returns the parsed JSON. Pass a custom httpx
client in tests; in production a fresh AsyncClient is created per call.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx

from kaji.runtime.tools.registry import ToolSpec


PaymentHandler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


def RequestPaymentTool(
    *,
    base_url: str,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[ToolSpec, PaymentHandler]:
    """Build the ryo bridge tool.

    Parameters
    ----------
    base_url:
        Root URL of the ryo API (no trailing slash required).
    api_key:
        Optional bearer token. When provided, sent as ``Authorization`` header.
    client:
        Optional pre-built httpx AsyncClient. Useful in tests with MockTransport.
        When omitted, the handler creates a one-shot AsyncClient per call.
    """
    base = base_url.rstrip("/")

    spec = ToolSpec(
        name="request_payment",
        description="Request a payment via ryo. Returns the checkout URL.",
        parameters={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "Amount in the smallest currency unit (cents).",
                },
                "description": {
                    "type": "string",
                    "description": "Short reason shown to the payer.",
                },
            },
            "required": ["amount", "description"],
        },
        risk="write",
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def handler(ctx: Any, args: dict[str, Any]) -> Any:
        url = f"{base}/v1/sessions"

        async def _post(c: httpx.AsyncClient) -> Any:
            r = await c.post(url, headers=headers, json=args)
            if r.status_code >= 400:
                raise RuntimeError(
                    f"ryo POST /v1/sessions failed: {r.status_code} {r.reason_phrase}"
                )
            return r.json()

        if client is not None:
            return await _post(client)
        async with httpx.AsyncClient() as c:
            return await _post(c)

    return spec, handler
```

- [ ] **Step 4: Re-export**

In `kaji/sdk/kaji/runtime/tools/__init__.py`, append:

```python
from kaji.runtime.tools.payment import RequestPaymentTool  # noqa: F401
```

(If the file already has an `__all__` list, also append `"RequestPaymentTool"` to it.)

In `kaji/sdk/kaji/__init__.py`'s `_LAZY` map, add this entry (alphabetical position is between `ReplaySession` and `SessionManager`):

```python
    "RequestPaymentTool": "kaji.runtime.tools.payment",
```

In `kaji/sdk/tests/test_public_surface.py`, add `"RequestPaymentTool"` to `EXPECTED_PUBLIC` so the surface-pinning test stays accurate.

- [ ] **Step 5: Run tests**

```bash
cd kaji/sdk && poetry run pytest tests/test_tools_payment.py tests/test_public_surface.py -v
poetry run pytest -q --ignore=tests/integration 2>&1 | tail -5
```
Expected: 4/4 new + 3/3 surface pinning pass; broader suite still green.

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/tools/payment.py \
        kaji/sdk/kaji/runtime/tools/__init__.py \
        kaji/sdk/kaji/__init__.py \
        kaji/sdk/tests/test_tools_payment.py \
        kaji/sdk/tests/test_public_surface.py
git commit -m "feat(py-sdk): add request_payment ryo bridge tool"
```

---

### Task 7: Docs — install page

**Files:**
- Create: `apps/docs/content/install.mdx`
- Modify: `apps/docs/content/meta.json`
- Modify: `apps/docs/content/getting-started.mdx:11-31`

**Interfaces:** none.

- [ ] **Step 1: Create the install page**

Create `apps/docs/content/install.mdx`:

````mdx
---
title: Install
description: Install kaji in Python or TypeScript, pick the provider extras you need, and learn the v0.x compatibility policy.
---

kaji ships as two SDKs that share the same wire format. Install one
per app; pick provider extras as needed. v0.x is alpha and minor versions
may break the public surface — pin exact versions in production until 1.0.

## Python

```bash
pip install "kaji[openai]"          # one provider
pip install "kaji[openai,anthropic]" # multiple
pip install "kaji[providers]"        # all three: openai, anthropic, gemini
```

The base install has no provider deps. `kaji[openai]` adds the `openai`
client, `kaji[anthropic]` adds `anthropic`, `kaji[gemini]` adds
`google-genai`. The default Python provider is `kimi` (OpenRouter); it
needs no extra package because it speaks the OpenAI chat-completions wire
format. Set `KIMI_API_KEY` to use it.

Optional extras:

| Extra            | Adds                                     |
| ---------------- | ---------------------------------------- |
| `openai`         | `openai`                                 |
| `anthropic`      | `anthropic`                              |
| `gemini`         | `google-genai`                           |
| `providers`      | all of the above                         |
| `realtime`       | `redis` (for `kaji-serve`)           |
| `google-tools`   | Google API clients (for tool sandboxes)  |
| `dev-ui`         | `rich` (for prettier CLI output)         |

## TypeScript

```bash
bun add @kaji/sdk openai
bun add @kaji/sdk @anthropic-ai/sdk
```

`@kaji/sdk` lists `openai` and `@anthropic-ai/sdk` as optional peer
dependencies. Install whichever you'll register as a provider. `zod` is
already a runtime dep of `@kaji/sdk`.

## CLI

The `kaji` CLI is a separate package with the same UX in both
languages.

```bash
pip install kaji       # Python: brings `kaji init/gen/...`
bun add -D @kaji/cli   # TypeScript: brings the same CLI surface plus `mcp`
```

See [CLI](/docs/cli) for the full command list.

## Version policy

| Range            | Behavior                                                 |
| ---------------- | -------------------------------------------------------- |
| `0.x.y`          | alpha. Minor bumps may rename or remove public names.    |
| `>=1.0`          | semver. Public surface is stable across minor versions.  |

Pin exact versions in lockfiles until 1.0 lands. The events wire format
(field names + type strings) is stable across SDKs in 0.x.
````

- [ ] **Step 2: Register the page in `meta.json`**

In `apps/docs/content/meta.json`, change:

```json
{
  "title": "kaji",
  "pages": ["index", "getting-started", "concepts", "architecture", "reference-service"]
}
```

to:

```json
{
  "title": "kaji",
  "pages": ["index", "install", "getting-started", "cli", "concepts", "architecture", "reference-service", "troubleshooting"]
}
```

(`cli` and `troubleshooting` are added here too so subsequent tasks don't have to re-touch this file.)

- [ ] **Step 3: Fix the install commands in getting-started**

In `apps/docs/content/getting-started.mdx`, replace the entire `### Install` step (lines 11–31, the `<Step>` containing the Tabs block) with:

```mdx
  <Step>
    ### Install

    <Tabs items={["python", "typescript"]}>
      <Tab value="python">
        ```bash
        pip install "kaji[openai]"
        ```
      </Tab>
      <Tab value="typescript">
        ```bash
        bun add @kaji/sdk openai
        ```
      </Tab>
    </Tabs>

    These pull the SDK plus one provider client. For other providers or
    optional extras, see [install](/docs/install).

  </Step>
```

- [ ] **Step 4: Build the docs to confirm no broken links**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -10
```
Expected: build succeeds. If `bun --filter docs` is not the right scope, find the docs script with `bun pm ls 2>&1 | grep docs` and use the matching filter.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/content/install.mdx apps/docs/content/meta.json apps/docs/content/getting-started.mdx
git commit -m "docs: add install page + fix getting-started install commands"
```

---

### Task 8: Docs — CLI page

**Files:**
- Create: `apps/docs/content/cli.mdx`

**Interfaces:** none.

- [ ] **Step 1: Create the CLI page**

The `meta.json` was already updated in Task 7 to include `cli`. Now create the page itself.

Create `apps/docs/content/cli.mdx`:

````mdx
---
title: CLI
description: The kaji CLI scaffolds projects, generates tool stubs from OpenAPI specs, and inspects your environment. Same commands in Python and TypeScript.
---

The CLI ships in two parity packages: `kaji` (Python, `pip install
kaji`) and `@kaji/cli` (TypeScript, `bun add -D @kaji/cli`).
Run `kaji --help` to see the live list.

## Commands

| Command   | Purpose                                                | Python | TS  |
| --------- | ------------------------------------------------------ | ------ | --- |
| `init`    | Scaffold a new project (`agent.ts`/`.py`, `.env.example`) | ✓      | ✓   |
| `gen`     | Generate tool stubs from an OpenAPI spec               | ✓      | ✓   |
| `info`    | Show environment + installed kaji packages         | ✓      | ✓   |
| `secret`  | Generate a random 32-byte hex secret                   | ✓      | ✓   |
| `doctor`  | Check the environment for common issues                | ✓      | ✓   |
| `upgrade` | Upgrade installed kaji packages                    | ✓      | ✓   |
| `mcp`     | Register the kaji MCP server with an AI tool       | --     | ✓   |

## init

```bash
kaji init . --provider openai --yes              # python: scaffolds agent.py
kaji init --lang ts --provider openai --yes      # ts: scaffolds agent.ts
```

Writes `agent.{py,ts}` and `.env.example` with the provider you chose
pre-filled. `--force` overwrites; `--yes` skips the interactive prompts.

## gen

```bash
kaji gen --spec openapi.yaml --out tools/ --lang python
kaji gen --spec openapi.yaml --out tools/ --lang ts
```

Parses an OpenAPI 3.x spec and emits one tool spec + handler per
`operationId`. The Python emitter writes `tools.py` (using `httpx`); the
TypeScript emitter writes `index.ts` (using `fetch`).

## info / doctor

```bash
kaji info                # shows platform, node/python, packages, providers
kaji info --json         # machine-readable
kaji doctor              # exit 1 if anything is wrong
```

`doctor` returns a non-zero exit code if any hard check fails (Python
>=3.11 / Node >=22, kaji installed, at least one provider key in env).

## secret / upgrade

```bash
kaji secret              # prints KAJI_SECRET=<64 hex chars>
kaji secret --json
kaji upgrade -y          # bumps @kaji/* (TS) or kaji/kaji-* (PyPI)
```

## mcp (TypeScript only)

```bash
kaji mcp                 # interactive: pick tool (cursor/claude-code/...) and scope
```

Writes the MCP server entry to the appropriate config file
(`.cursor/mcp.json`, `claude_desktop_config.json`, etc.). The Python CLI
does not ship `mcp` — register the Python agent's tools through your AI
tool directly.
````

- [ ] **Step 2: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add apps/docs/content/cli.mdx
git commit -m "docs: add CLI reference page"
```

---

### Task 9: Docs — troubleshooting page

**Files:**
- Create: `apps/docs/content/troubleshooting.mdx`

**Interfaces:** none.

- [ ] **Step 1: Create the troubleshooting page**

Create `apps/docs/content/troubleshooting.mdx`:

````mdx
---
title: Troubleshooting
description: Common errors when importing kaji, running a provider, or installing the CLI -- and how to fix each one.
---

If you see one of these errors, try the matching fix below.

## ModuleNotFoundError: No module named 'openai'

You installed `kaji` without the provider extra.

```bash
pip install "kaji[openai]"        # or [anthropic] / [gemini] / [providers]
```

The same applies in TypeScript -- `@kaji/sdk` lists `openai` and
`@anthropic-ai/sdk` as optional peer deps. Install whichever you'll use:

```bash
bun add @kaji/sdk openai
```

## ProviderConfigError: <PROVIDER>_API_KEY is required

The provider client cannot find its key. Export it in your shell or put
it in a `.env` file that your runtime loads.

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export KIMI_API_KEY=...
```

Run `kaji doctor` to verify at least one provider key is present.

## Peer dep version mismatch (TS)

If `bun add @kaji/sdk openai` warns about a peer-dep version
conflict, you probably have an older `openai` installed elsewhere in the
workspace. `@kaji/sdk` accepts `openai >=4 <8` and
`@anthropic-ai/sdk >=0.30 <2`. Upgrade the dep or pin one that fits the
range.

## Tool calls never fire

Three usual causes, in order of likelihood:

1. The tool was registered with `RegisterTool` / `registerTool` but not
   passed to `AgentBuilder().tool(...)`. The runtime only sees tools
   bound to it.
2. The model wasn't given the spec. Check `kaji info --json` for the
   provider, and confirm your provider's API supports function calling.
3. The model decided not to call the tool. Reduce ambiguity in the
   tool's `description` and parameter docs.

## Events log is empty after a turn

`runtime.history(sessionId)` reads from the `EventStore` you passed (or
the default `InMemoryEventStore`). If you instantiated a fresh store
between the turn and the read, it will be empty. Reuse the store; or, to
stream events as they happen, subscribe to the bus -- see
[event bus](/docs/concepts/event-bus).

## `import kaji` is slow

The Python SDK uses PEP 562 lazy loading. The top-level import is
cheap; first attribute access triggers a submodule import. If a specific
name is slow on first access, import it directly from its subpackage
(e.g. `from kaji.runtime.tools.registry import ToolSpec`).

## kaji CLI not on PATH after `pip install`

Your shell hasn't picked up the new entrypoint. Restart the shell or
run `hash -r` (bash/zsh). If the CLI is installed inside a virtualenv,
activate the venv (`poetry shell` or `source .venv/bin/activate`)
before running `kaji`.
````

- [ ] **Step 2: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add apps/docs/content/troubleshooting.mdx
git commit -m "docs: add troubleshooting page"
```

---

### Task 10: Docs — inline the event-type enum

**Files:**
- Modify: `apps/docs/content/concepts/events.mdx`

**Interfaces:** none.

- [ ] **Step 1: Read the source enum**

Verify the Python event-type names by reading
`kaji/sdk/kaji/infra/events/schemas.py` (the `class EventType(StrEnum)` block) and `kaji/ts/src/events/types.ts` (the `enum EventType` block). They are identical strings; if they have diverged, surface that as a finding before continuing.

```bash
grep -nE '"[a-z]+\.[a-z.]+"' kaji/sdk/kaji/infra/events/schemas.py | head -30
grep -nE '"[a-z]+\.[a-z.]+"' kaji/ts/src/events/types.ts | head -30
```

- [ ] **Step 2: Rewrite the events page**

Replace the entire contents of `apps/docs/content/concepts/events.mdx` with:

````mdx
---
title: Events
description: All kaji session state derives from an append-only event log. Wire-format type strings are identical across the Python and TypeScript SDKs.
---

Session state in kaji is a deterministic projection of an append-only
event log. The runtime appends events as you call `send`; `replaySession`
reads them back into a usable `SessionState`.

You usually don't emit events yourself -- the runtime does. Reach into
the log when you want to inspect, persist, or replay a session.

## Event types

The same strings are used over the wire by both SDKs. A log written by
the Python SDK can be replayed by the TypeScript SDK and vice versa.

| Type                          | Emitted by                                  |
| ----------------------------- | ------------------------------------------- |
| `user.message`                | Caller (via `runtime.send`)                 |
| `agent.message.delta`         | Provider streaming a text chunk             |
| `agent.message.completed`     | Provider finished a turn                    |
| `tool.call.requested`         | Model decided to call a tool                |
| `tool.call.completed`         | Tool handler returned a result              |
| `tool.call.failed`            | Tool handler raised                         |
| `session.started`             | First event in a new session                |
| `session.ended`               | Session was closed                          |

The canonical list is in the SDK source -- check there before relying on
any event type:

- Python: `kaji/sdk/kaji/infra/events/schemas.py`
- TypeScript: `kaji/ts/src/events/types.ts`

## Reading the log

```python
# Python
events = await runtime.history("session-1")
for e in events:
    print(e.type, getattr(e, "content", ""))
```

```ts
// TypeScript
const events = await runtime.history("session-1");
for (const e of events) {
  console.log(e.type, e.content ?? "");
}
```

`replaySession` projects the log into a `SessionState` for you on every
turn -- see [session state](/docs/concepts/session-state).
````

If your grep in Step 1 showed event types that differ from the table above, update the table to match the source before committing.

- [ ] **Step 3: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/content/concepts/events.mdx
git commit -m "docs: inline event-type table on events page"
```

---

### Task 11: Docs — runtime API reference page

**Files:**
- Create: `apps/docs/content/concepts/runtime.mdx`
- Modify: `apps/docs/content/concepts/meta.json`

**Interfaces:** none.

- [ ] **Step 1: Create the runtime page**

Create `apps/docs/content/concepts/runtime.mdx`:

````mdx
---
title: Runtime
description: AgentBuilder configures the runtime; AgentRuntime.send runs a turn; runtime.history reads back the event log; runtime.subscribe streams events as they happen.
---

`AgentRuntime` is the loop that takes a user message, calls the LLM,
dispatches tool calls scatter-gather, and projects the resulting events
into session state. You build one with `AgentBuilder`.

## AgentBuilder

| Method                       | Description                                                |
| ---------------------------- | ---------------------------------------------------------- |
| `.provider(p)`               | Sets the LLM provider (required)                           |
| `.tool(t)`                   | Adds one tool. Call multiple times for multiple tools.     |
| `.integration(i)`            | Adds an `Integration` that registers a bundle of tools.    |
| `.system_prompt(s)` (Python) | Sets the system prompt. `.systemPrompt(s)` in TypeScript.  |
| `.bus(b)`                    | Overrides the default `InMemoryEventBus`.                  |
| `.store(s)`                  | Overrides the default `InMemoryEventStore`.                |
| `.build()`                   | Returns an `AgentRuntime`.                                 |

## AgentRuntime

| Method                            | Returns                       | Description                                                       |
| --------------------------------- | ----------------------------- | ----------------------------------------------------------------- |
| `send(session_id, text)`          | the final agent message       | Appends a `user.message` and runs one turn (may include tool loops). |
| `history(session_id)`             | `list[KajiEvent]`         | All events appended to this session, in order.                    |
| `subscribe(session_id)`           | async iterator of events      | Live event stream as they hit the bus.                            |
| `replay(session_id)`              | `SessionState`                | Projection of the event log via `replaySession`.                  |

In Python, methods are snake_case (`send`, `history`, `subscribe`,
`replay`) and async. In TypeScript they are camelCase
(`send`, `history`, `subscribe`, `replay`) and return Promises (or
`AsyncIterable` for `subscribe`).

## Example

<Tabs items={["python", "typescript"]}>
  <Tab value="python">
    ```python
    from kaji import AgentBuilder, GetProvider

    runtime = (
        AgentBuilder()
        .provider(GetProvider("openai"))
        .system_prompt("You are a helpful assistant.")
        .build()
    )
    final = await runtime.send("s1", "Hello")
    print(final.content)
    ```

  </Tab>
  <Tab value="typescript">
    ```ts
    import { AgentBuilder, OpenAIProvider } from "@kaji/sdk";

    const runtime = new AgentBuilder()
      .provider(new OpenAIProvider())
      .systemPrompt("You are a helpful assistant.")
      .build();
    const final = await runtime.send("s1", "Hello");
    console.log(final.content);
    ```

  </Tab>
</Tabs>

## Streaming with subscribe

`subscribe` yields events as they hit the bus -- useful for UI updates.

<Tabs items={["python", "typescript"]}>
  <Tab value="python">
    ```python
    async for event in runtime.subscribe("s1"):
        if event.type == "agent.message.delta":
            print(event.delta, end="", flush=True)
    ```

  </Tab>
  <Tab value="typescript">
    ```ts
    for await (const event of runtime.subscribe("s1")) {
      if (event.type === "agent.message.delta") {
        process.stdout.write(event.delta);
      }
    }
    ```

  </Tab>
</Tabs>

See [event bus](/docs/concepts/event-bus) for the underlying mechanism.
````

- [ ] **Step 2: Register in concepts meta**

In `apps/docs/content/concepts/meta.json`, change:

```json
{
  "title": "Concepts",
  "pages": ["events", "session-state", "tool-registry", "event-bus", "providers"]
}
```

to:

```json
{
  "title": "Concepts",
  "pages": ["events", "session-state", "runtime", "tool-registry", "event-bus", "providers"]
}
```

- [ ] **Step 3: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 4: Verify the prose matches the code**

Cross-check the documented methods against the implementation:

```bash
grep -nE "async def (send|history|subscribe|replay)\(" kaji/sdk/kaji/runtime/agents/runtime.py
grep -nE "^  (send|history|subscribe|replay)\(" kaji/ts/src/runtime/runtime.ts
```

If a documented method is missing from either runtime, **remove** it from the table -- do not invent code. The doc must match what ships.

- [ ] **Step 5: Commit**

```bash
git add apps/docs/content/concepts/runtime.mdx apps/docs/content/concepts/meta.json
git commit -m "docs: add concepts/runtime API reference"
```

---

### Task 12: Docs — reference-service runbook

**Files:**
- Modify: `apps/docs/content/reference-service.mdx`

**Interfaces:** none.

- [ ] **Step 1: Inspect the existing serve docker setup**

```bash
ls /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/serve
ls /Users/Enkang.Yuan1/Desktop/Projects/alloy/docker 2>/dev/null || echo "no top-level docker dir"
grep -lE "uvicorn|fastapi" /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/serve/kaji_serve/*.py | head -3
```

You need to discover: which Python script launches each of the three processes (`api`, `bus-worker`, `worker`), and where the docker-compose file lives (project root `docker/` or under `kaji/serve/`).

If you cannot find a runnable command for any one of the three processes, STOP and report it as DONE_WITH_CONCERNS rather than fabricating commands. The doc must reflect the actual runnable contract.

- [ ] **Step 2: Rewrite the reference-service page**

Replace `apps/docs/content/reference-service.mdx` with:

````mdx
---
title: Reference Service
description: kaji-serve wraps the SDK as three Redis-backed processes (api, bus-worker, worker) for multi-process durability and real-time voice. This page shows how to run them.
---

`kaji-serve` (`kaji/serve`) wraps the SDK as three processes
over Redis so heavy tool execution never stalls a real-time exchange.

| Process      | Role                                                      | Port |
| ------------ | --------------------------------------------------------- | ---- |
| `api`        | FastAPI app: REST routes and STT WebSocket                | 8000 |
| `bus-worker` | reasoning loop: LLM calls, event bus, tool dispatch       | -    |
| `worker`     | async tool execution (TaskIQ), results back to bus-worker | -    |

Redis Streams provide durable at-least-once hand-off between processes.
Redis Pub/Sub fans agent responses out to the connected client in real
time.

## Run with docker compose

The fastest path. Provides Redis automatically.

```bash
cd kaji/serve
docker compose up
```

The `api` is reachable at `http://localhost:8000`. Health check:

```bash
curl http://localhost:8000/healthz
```

## Run the processes directly

If you already have a Redis instance, you can start each process by hand
in three separate terminals.

```bash
cd kaji/serve
poetry install
export REDIS_URL=redis://localhost:6379/0

# Terminal 1: api
poetry run uvicorn kaji_serve.api.app:app --host 0.0.0.0 --port 8000

# Terminal 2: bus-worker
poetry run python -m kaji_serve.workers.bus

# Terminal 3: worker
poetry run python -m kaji_serve.workers.tools
```

If any of those module paths differ in your tree, run `kaji doctor`
inside `kaji/serve` and follow the hints, then update the commands
above.

## When to use the reference service

Reach for it when you need:

- multi-process durability (a tool crash should not lose session state),
- real-time voice over a WebSocket,
- horizontal scale: more workers behind one bus.

For everything else -- in-process agents, single-replica deployments,
embedded apps -- embed the SDK directly. See [index](/docs).
````

If your Step 1 inspection showed different module paths or a different docker-compose location, edit the commands accordingly before committing.

- [ ] **Step 3: Build the docs**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/content/reference-service.mdx
git commit -m "docs: add runnable commands to reference-service page"
```

---

### Task 13: ast-grep audit + final review

**Files:** none directly; this is a verification + polish task.

**Interfaces:** none.

- [ ] **Step 1: Em-dash scan**

```bash
grep -rn '—' /Users/Enkang.Yuan1/Desktop/Projects/alloy/apps/docs/content/ /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/sdk/kaji/runtime/tools/payment.py /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/ts/src/tools/payment.ts 2>&1 | grep -v '^Binary' || echo "no em-dashes"
```
Expected: `no em-dashes`. If anything matches, edit to replace `—` with `-`, `--`, or a comma.

- [ ] **Step 2: ast-grep sweep on the new TS code**

Run an ast-grep pattern that flags any direct `import 'openai'` or `import '@anthropic-ai/sdk'` at the top level of `payment.ts` (those would defeat the optional-peer-dep gating).

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy/kaji/ts
bun x ast-grep --pattern 'import $X from "openai"' --lang ts src/tools/payment.ts 2>&1 | head -5
bun x ast-grep --pattern 'import $X from "@anthropic-ai/sdk"' --lang ts src/tools/payment.ts 2>&1 | head -5
```
Expected: both empty. If either matches, `payment.ts` is accidentally importing a provider client; rewrite it to use only `fetch` and the registry types.

If `ast-grep` is not installed, fall back to:

```bash
grep -nE "from \"(openai|@anthropic-ai/sdk)\"" kaji/ts/src/tools/payment.ts
```

- [ ] **Step 3: Re-run all the test suites**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
bun --filter @kaji/sdk test 2>&1 | tail -5
bun --filter @kaji/cli test 2>&1 | tail -5
cd kaji/sdk && poetry run pytest -q --ignore=tests/integration 2>&1 | tail -5
```
Expected: every suite green.

- [ ] **Step 4: Build the docs once more**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter docs build 2>&1 | tail -10
```
Expected: build succeeds; no broken-link warnings in the output.

- [ ] **Step 5: Push branch and open PR**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git log --oneline origin/main..HEAD
git push origin feat/sdk-dx-and-docs

gh pr create --title "feat(sdk, docs): close v0.1.0 DX + docs gaps" --body "$(cat <<'EOF'
## Summary

Closes the engineering-DX and docs gaps surfaced by the post-merge SDK
assessment. Voice modality work is excluded as requested.

### SDK DX
- TS: widen `openai`/`@anthropic-ai/sdk`/`zod` peer-dep ranges so consumers do not hit version warnings on newer SDK majors.
- Py: ship `py.typed` so type-only consumers get the same DX as source readers.
- Py: slim the top-level public lazy map to the 25 names a v0.1.0 user actually composes against. Internal names remain importable from their subpackages, and a regression test pins the surface.
- Py + TS: add `request_payment` / `requestPayment` as opt-in tools that POST to ryo's session endpoint (no Stripe SDK, fetch/httpx only).

### Docs
- Add `install`, `cli`, `troubleshooting` pages.
- Add `concepts/runtime` API reference.
- Inline the event-type enum on `concepts/events`.
- Replace the wrong `cd kaji/sdk && poetry install` instructions in `getting-started` with the published-package commands.
- Add real run commands to `reference-service`.

## Test plan
- [ ] `bun --filter @kaji/sdk test`
- [ ] `bun --filter @kaji/cli test`
- [ ] `cd kaji/sdk && poetry run pytest -q --ignore=tests/integration`
- [ ] `bun --filter docs build`
- [ ] Manual: `pip install -e ./kaji/sdk[openai]` from a fresh venv, then `python -c "from kaji.runtime.tools.payment import RequestPaymentTool; print('ok')"`
EOF
)"
```

Capture the PR URL from `gh pr create`'s output.

- [ ] **Step 6: Final commit if anything else changed during review**

If the ast-grep step or the doc build flagged anything that needed an edit, commit those changes with a concise message before pushing.

---

## Self-Review

**Spec coverage:** the user asked to (1) resolve engineering DX issues from the SDK assessment excluding voice, (2) fix the docs issues, (3) use subagent-driven development, (4) iteratively verify, (5) leverage ast-grep + karpathy-guidelines.

SDK DX items from the assessment (voice-excluded):

| Assessment finding                                                  | Task |
| ------------------------------------------------------------------- | ---- |
| TS peer-dep ranges too narrow                                       | 2    |
| Missing `py.typed`                                                  | 3    |
| Python public surface too wide                                      | 4    |
| `request_payment` missing in TS                                     | 5    |
| `request_payment` missing in Python                                 | 6    |

Docs items from the assessment:

| Assessment finding                                                  | Task |
| ------------------------------------------------------------------- | ---- |
| `cd kaji/sdk && poetry install` install command is wrong        | 7    |
| No install/extras matrix or version policy                          | 7    |
| No CLI page                                                         | 8    |
| No troubleshooting page                                             | 9    |
| `events.mdx` punts on the enum                                      | 10   |
| No API reference                                                    | 11   |
| `reference-service.mdx` lacks run commands                          | 12   |

Items intentionally NOT covered (out of scope per "excluding voice"):
- TS missing voice / STT / TTS / Soniox
- Barge-in / VAD endpoint detection
- TS missing Kimi/Gemini providers (would expand provider surface; user did not ask for new providers)
- TS missing RAG (would need a TS knowledge module port; sizable, would deserve its own plan)
- Multi-agent / swarm handoff (Roadmap 15, untouched)

Items addressed in review tooling (Task 13): ast-grep on `payment.ts` (per the user request), em-dash sweep, full test re-run, docs build re-check.

**Placeholder scan:** every task ships exact code, exact commands, and exact expected output. No "TODO", "implement later", "fill in details". The only conditional-on-discovery step is Task 12 Step 1 (find the actual run commands in `kaji/serve`) -- and the plan explicitly says to escalate as DONE_WITH_CONCERNS rather than fabricate.

**Type consistency:**
- TS: `requestPayment` returns `{ spec: ToolSpec; handler: ToolHandler }`. Both types come from `./registry` and are already exported.
- Python: `RequestPaymentTool` returns `tuple[ToolSpec, PaymentHandler]` where `PaymentHandler = Callable[[Any, dict[str, Any]], Awaitable[Any]]`. `ToolSpec` is the existing dataclass from `kaji.runtime.tools.registry`.
- Surface-pinning test in Task 4 includes `ToolSpec`; Task 6 adds `RequestPaymentTool` to both the lazy map AND the test's `EXPECTED_PUBLIC` set so the regression bar stays accurate.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-21-sdk-dx-and-docs.md`. Two execution options:

**1. Subagent-Driven (recommended)** -- dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** -- execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
