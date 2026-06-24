# SDK DX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Smooth out the first-hour friction in `@kaji/sdk` and `kaji` so a new developer can install, scaffold, and ship a tool-calling agent without reading the source. Reduce silent failure modes and align docs with the shipped API.

**Architecture:** Six surgical changes, each independently shippable. (1) One-line, actionable provider error messages that name the env var AND the constructor argument. (2) Python scaffold loads `.env` (parity with TS). (3) Generated CLI scaffolds that explain config errors instead of dumping stack traces. (4) A "Stream events" step in getting-started that leads with the working example. (5) A "Streaming" concept page wired into the docs nav (positioned right after `events`, not at the bottom). (6) Fix `concepts/runtime.mdx` `.tool()` polymorphism drift.

**Tech Stack:** TypeScript (`@kaji/sdk`, vitest), Python (`kaji`, pytest), Fumadocs MDX (`apps/docs/content/`), CLI templates (`apps/cli/src/templates/`).

## Global Constraints

- Pre-1.0 SDKs: no back-compat shims, no aliases. Rename cleanly. (Per repo memory `feedback-no-back-compat`.)
- All package operations use `bun`, not `npm`/`yarn`/`pnpm`. (Per repo memory `use-bun-not-npm`.)
- No em-dashes in docs prose, error messages, or scaffold output. (Per repo memory `writing-style-no-emdash`.)
- Branch name: `feat/sdk-dx-polish`. Commit directly to that branch.
- Existing docs-sync test (`kaji/sdk/tests/test_docs_sync.py`) must continue to pass after MDX changes; run it after every doc-touching task.
- TS tests run via `cd kaji/ts && bun run test`; Python via `cd kaji/sdk && pytest`; docs-sync via `cd kaji/sdk && pytest tests/test_docs_sync.py`.
- **Doc URL convention:** This plan does NOT point error messages at a public URL. The `kaji.dev` domain is reserved (it appears in `kaji/sdk/kaji/integrations/registry/schema.json`) but the documentation site state is uncertain at v0.1. Error messages are kept terse and self-contained; a confused developer opens the README. Revisit when the docs site is confirmed live.
- **Tab order in MDX docs:** every `<Tabs items={...}>` block uses `["python", "typescript"]` — matches the existing `getting-started.mdx` convention. Do not reverse it in new pages.
- **Error message copy convention:** single sentence, imperative, names the env var AND the constructor argument. No multi-line bullet lists (they look broken in terminals; many devs read stderr piped to a file or wrapped by an IDE). Existing single-sentence errors (`OAuthError` in `kaji/sdk/kaji/integrations/oauth.py:104`) match this convention and stay as-is.

## Execution Order

```
Group A (errors)    : Task 1 -> Task 2
Group B (scaffolds) : Task 3 (depends on Task 1 + Task 2; uses ProviderConfigError class)
Group C (docs)      : Task 4 -> Task 5 -> Task 6  (Task 5 adds the page Task 4 links to)
```

Group A can run in parallel with Group C. Group B must wait for Group A.

---

## File Structure

**TypeScript provider errors (`kaji/ts/src/providers/`)**
- `openai.ts:84-86` — `ProviderConfigError` message names env var, kwarg, and `.env` path.
- `anthropic.ts:102-103` — same.
- `factory.ts` — read-only; the factory passes `apiKey: process.env.X ?? ""` to the constructor, which fires the new message.

**Python provider errors (`kaji/sdk/kaji/runtime/providers/`)**
- `openai.py` — same message structure.
- `anthropic.py`, `gemini.py`, `kimi.py` — same.

**CLI scaffolds (`apps/cli/src/templates/`)**
- `ts-agent.ts:22-58` — import `ProviderConfigError`; catch it in `main().catch(...)`; print one-line message + exit 1.
- `py-agent.ts:1-30` — call `runtime.send()` (drop the two-step `append` + `run_turn`); load `.env` via `python-dotenv`; catch `ProviderConfigError`.
- `py-env.ts` (the env-file template generator) — unchanged; the new scaffold imports it.
- The Python scaffold's generated `requirements.txt` (or equivalent dep declaration in the scaffold output) — add `python-dotenv>=1.0`. Find this in the CLI's scaffold generator (`apps/cli/src/commands/init.ts` or wherever scaffolded `requirements.txt` is emitted).

**Docs (`apps/docs/content/`)**
- `getting-started.mdx` — new `<Step>` for live event streaming.
- `concepts/streaming.mdx` — new file: full streaming reference.
- `concepts/meta.json` — add `"streaming"` to the `pages` array. **This is mandatory; Fumadocs does NOT auto-discover.**
- `concepts/runtime.mdx` — clarify `.tool()` accepts `BoundTool` or `Integration`.

**Tests**
- `kaji/ts/tests/providers.errors.test.ts` (new) — assert error message contents (constructor-only; no `process.env` mutation).
- `kaji/sdk/tests/test_providers_errors.py` (new) — equivalent.
- `apps/cli/test/commands/init.test.ts` (extend) — assert scaffold's error handler shape and `dotenv` import in Python.
- `kaji/sdk/tests/test_docs_sync.py` — already walks `apps/docs/content`; the new page must reference only real exports.

---

### Task 1: Actionable ProviderConfigError messages (TS)

**Files:**
- Modify: `kaji/ts/src/providers/openai.ts:84-86`
- Modify: `kaji/ts/src/providers/anthropic.ts:102-103`
- Test: `kaji/ts/tests/providers.errors.test.ts` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `ProviderConfigError` messages name (a) the env var, (b) the constructor argument. Single sentence. No public URL (see Global Constraints).

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/providers.errors.test.ts`. Test constructor behavior directly; do NOT mutate `process.env` (parallel-test races).

```ts
import { describe, expect, it } from "vitest";
import { OpenAIProvider } from "../src/providers/openai";
import { AnthropicProvider } from "../src/providers/anthropic";

describe("ProviderConfigError messages", () => {
  it("OpenAIProvider names the env var and the apiKey argument", () => {
    let caught: Error | null = null;
    try {
      new OpenAIProvider({ apiKey: "" });
    } catch (e) {
      caught = e as Error;
    }
    expect(caught).not.toBeNull();
    expect(caught!.message).toMatch(/OPENAI_API_KEY/);
    expect(caught!.message).toMatch(/apiKey/);
  });

  it("AnthropicProvider names the env var and the apiKey argument", () => {
    let caught: Error | null = null;
    try {
      new AnthropicProvider({ apiKey: "" });
    } catch (e) {
      caught = e as Error;
    }
    expect(caught).not.toBeNull();
    expect(caught!.message).toMatch(/ANTHROPIC_API_KEY/);
    expect(caught!.message).toMatch(/apiKey/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/ts && bun run test -- tests/providers.errors.test.ts`
Expected: FAIL. Current message is the bare "OpenAI API key is not configured."

- [ ] **Step 3: Improve OpenAIProvider error message**

In `kaji/ts/src/providers/openai.ts`, replace lines 84-86:

```ts
if (!opts.apiKey?.trim()) {
  throw new ProviderConfigError(
    "OpenAI API key is not configured. Set OPENAI_API_KEY in your environment, or pass apiKey to OpenAIProvider().",
    { service: "openai" },
  );
}
```

- [ ] **Step 4: Improve AnthropicProvider error message**

In `kaji/ts/src/providers/anthropic.ts`, replace the `ProviderConfigError` at line 102-103:

```ts
if (!opts.apiKey?.trim()) {
  throw new ProviderConfigError(
    "Anthropic API key is not configured. Set ANTHROPIC_API_KEY in your environment, or pass apiKey to AnthropicProvider().",
    { service: "anthropic" },
  );
}
```

- [ ] **Step 5: factory.ts requires no change**

The TS factories at `kaji/ts/src/providers/factory.ts:29-138` already pass `apiKey: process.env[envVar] ?? ""` into the constructor. The constructor's improved message fires for both direct construction and factory paths. No edit needed.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd kaji/ts && bun run test -- tests/providers.errors.test.ts`
Expected: 2 PASS.

- [ ] **Step 7: Run full provider suite**

Run: `cd kaji/ts && bun run test -- tests/providers`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add kaji/ts/src/providers/openai.ts kaji/ts/src/providers/anthropic.ts kaji/ts/tests/providers.errors.test.ts
git commit -m "feat(ts): actionable ProviderConfigError messages name env var, kwarg, and .env"
```

---

### Task 2: Actionable ProviderConfigError messages (Python)

**Files:**
- Modify: `kaji/sdk/kaji/runtime/providers/openai.py:54-56` (or wherever the empty-key check lives)
- Modify: `kaji/sdk/kaji/runtime/providers/anthropic.py`
- Modify: `kaji/sdk/kaji/runtime/providers/gemini.py`
- Modify: `kaji/sdk/kaji/runtime/providers/kimi.py`
- Test: `kaji/sdk/tests/test_providers_errors.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: each `ProviderConfigError` names env var and the `api_key` kwarg. Single sentence. Same shape as TS.

- [ ] **Step 1: Write the failing test**

Create `kaji/sdk/tests/test_providers_errors.py`:

```python
import pytest

from kaji.runtime.providers.errors import ProviderConfigError
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.anthropic import AnthropicProvider


def test_openai_provider_error_mentions_env_var_and_kwarg():
    with pytest.raises(ProviderConfigError) as exc:
        OpenAIProvider(model_name="gpt-4o", api_key="")
    msg = str(exc.value)
    assert "OPENAI_API_KEY" in msg
    assert "api_key" in msg


def test_anthropic_provider_error_mentions_env_var_and_kwarg():
    with pytest.raises(ProviderConfigError) as exc:
        AnthropicProvider(model_name="claude-3-5-sonnet", api_key="")
    msg = str(exc.value)
    assert "ANTHROPIC_API_KEY" in msg
    assert "api_key" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd kaji/sdk && pytest tests/test_providers_errors.py -v`
Expected: FAIL (or constructors don't validate at all).

- [ ] **Step 3: Locate each provider's API-key validation**

```bash
grep -n "ProviderConfigError\|api_key is not configured\|not configured" kaji/sdk/kaji/runtime/providers/*.py
```

Confirm: `openai.py:55`, `anthropic.py`, `gemini.py`, `kimi.py`. Note the exact line numbers; the rewrites below assume single-line `raise ProviderConfigError(...)` calls.

- [ ] **Step 4: Update each provider constructor**

In `kaji/sdk/kaji/runtime/providers/openai.py`, replace the existing empty-key block with:

```python
if not (self.api_key or "").strip():
    raise ProviderConfigError(
        "OpenAI API key is not configured. "
        "Set OPENAI_API_KEY in your environment, "
        "or pass api_key to OpenAIProvider()."
    )
```

Repeat for `anthropic.py` (`ANTHROPIC_API_KEY`), `gemini.py` (`GEMINI_API_KEY`), `kimi.py` (check the file — Kimi may read `OPENROUTER_API_KEY` or `KIMI_API_KEY`; use whichever the existing code resolves).

If `ProviderConfigError` is not already imported in `anthropic.py`, `gemini.py`, or `kimi.py`, add:

```python
from kaji.runtime.providers.errors import ProviderConfigError
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd kaji/sdk && pytest tests/test_providers_errors.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Run full Python provider suite**

Run: `cd kaji/sdk && pytest tests/ -k provider -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add kaji/sdk/kaji/runtime/providers/openai.py kaji/sdk/kaji/runtime/providers/anthropic.py kaji/sdk/kaji/runtime/providers/gemini.py kaji/sdk/kaji/runtime/providers/kimi.py kaji/sdk/tests/test_providers_errors.py
git commit -m "feat(sdk): actionable ProviderConfigError messages in Python providers"
```

---

### Task 3: Friendly error handling + parity in CLI scaffolds (Python loads .env)

**Files:**
- Modify: `apps/cli/src/templates/ts-agent.ts`
- Modify: `apps/cli/src/templates/py-agent.ts`
- Modify: the Python scaffold's dep declaration (find it; see Step 1 below)
- Test: `apps/cli/test/commands/init.test.ts` (extend)

**Interfaces:**
- Consumes: improved `ProviderConfigError` messages from Tasks 1 and 2.
- Produces:
  - TS scaffold: catches `ProviderConfigError`, prints the message (no stack), exits 1.
  - Python scaffold: catches `kaji.ProviderConfigError`, prints the message, exits 1. Also: calls `load_dotenv()` so the developer's `.env` file actually loads.
  - Python scaffold's generated requirements include `python-dotenv>=1.0`.

- [ ] **Step 1: Find where the Python scaffold declares dependencies**

```bash
grep -rn "kaji\[openai\]\|requirements.txt\|pyproject.toml" apps/cli/src | head -20
```

The scaffold generator probably writes `requirements.txt` or `pyproject.toml` for the new project. Note its location; you'll add `python-dotenv` to it in Step 5.

- [ ] **Step 2: Write the failing test**

In `apps/cli/test/commands/init.test.ts`, add (importing templates at the top of the file if not already imported):

```ts
import { tsAgentTemplate } from "../../src/templates/ts-agent";
import { pyAgentTemplate } from "../../src/templates/py-agent";

it("ts scaffold imports and catches ProviderConfigError specifically", () => {
  const src = tsAgentTemplate("openai");
  expect(src).toMatch(/ProviderConfigError/);
  expect(src).toMatch(/e instanceof ProviderConfigError/);
  expect(src).toMatch(/console\.error\(e\.message\)/);
});

it("python scaffold loads .env via dotenv before constructing the runtime", () => {
  const src = pyAgentTemplate("openai");
  expect(src).toMatch(/from dotenv import load_dotenv/);
  expect(src).toMatch(/load_dotenv\(\)/);
});

it("python scaffold catches ProviderConfigError specifically", () => {
  const src = pyAgentTemplate("openai");
  expect(src).toMatch(/kaji\.ProviderConfigError/);
  expect(src).toMatch(/SystemExit\(1\)/);
});

it("python scaffold uses runtime.send (not the two-step append+run_turn)", () => {
  const src = pyAgentTemplate("openai");
  expect(src).toMatch(/runtime\.send\(/);
  expect(src).not.toMatch(/UserMessage\(/);
  expect(src).not.toMatch(/run_turn\(/);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd apps/cli && bun run test -- test/commands/init.test.ts`
Expected: FAIL.

- [ ] **Step 4: Update the TS scaffold template**

In `apps/cli/src/templates/ts-agent.ts`, replace the template-string body (lines 22-58) with:

```ts
return `import {
  AgentBuilder,
  KajiEvent,
  EventBus,
  EventType,
  InMemoryEventStore,
  ProviderConfigError,
  ${factoryName},
} from "@kaji/sdk";

async function main() {
  const bus = new EventBus();
  const store = new InMemoryEventStore();

  const runtime = new AgentBuilder()
    .provider(${factoryName}())
    .systemPrompt("You are a helpful assistant.")
    .build({ bus, store });

  const sessionCreated = KajiEvent.parse({
    type: EventType.SESSION_CREATED,
    session_id: "s1",
  });
  await store.append(sessionCreated);
  await bus.publish(sessionCreated);

  await runtime.send("s1", "Hello!");

  for (const e of await store.getEvents("s1")) {
    const text = "content" in e ? e.content : "delta" in e ? e.delta : "";
    console.log(e.type, text);
  }
}

main().catch((e) => {
  if (e instanceof ProviderConfigError) {
    console.error(e.message);
  } else {
    console.error(e);
  }
  process.exit(1);
});
`;
```

- [ ] **Step 5: Update the Python scaffold template**

In `apps/cli/src/templates/py-agent.ts`, replace the template-string body:

```ts
return `"""Minimal kaji scaffold."""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

import kaji


async def main() -> None:
    load_dotenv()
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()
    provider_name = os.environ.get("KAJI_MODEL_PROVIDER", ${JSON.stringify(provider)})
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider(provider_name))
        .system_prompt("You are a helpful assistant.")
        .build(bus=bus, store=store)
    )
    await runtime.send("s1", "Hello!")
    for e in await store.get_events("s1"):
        print(e.type, getattr(e, "content", getattr(e, "delta", "")))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except kaji.ProviderConfigError as e:
        print(e, file=sys.stderr)
        raise SystemExit(1) from e
`;
```

Add `python-dotenv>=1.0` to the Python scaffold's generated dep file. From Step 1, you know whether that's `requirements.txt` or `pyproject.toml`. The line goes alongside the existing `kaji[openai]` (or equivalent).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd apps/cli && bun run test -- test/commands/init.test.ts`
Expected: PASS.

- [ ] **Step 7: Smoke-test both scaffolds via a checked-in script**

Create `apps/cli/test/scripts/scaffold-smoke.sh`:

```bash
#!/usr/bin/env bash
# Smoke test the CLI scaffold output. Run from the repo root.
# Fails if either scaffold leaks a stack trace or omits the actionable error.
set -euo pipefail

REPO=$(git rev-parse --show-toplevel)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

( cd "$REPO/apps/cli" && bun run build )

node "$REPO/apps/cli/dist/index.js" init ts-test --provider openai --language typescript
node "$REPO/apps/cli/dist/index.js" init py-test --provider openai --language python

unset OPENAI_API_KEY || true

( cd ts-test && bun install && bun run start ) > ts-error.txt 2>&1 || true
grep -q "OPENAI_API_KEY" ts-error.txt
grep -q "apiKey" ts-error.txt
! grep -qE "at .*\.(ts|js):[0-9]+" ts-error.txt

( cd py-test && python -m venv .venv && .venv/bin/pip install -e . && .venv/bin/python main.py ) > py-error.txt 2>&1 || true
grep -q "OPENAI_API_KEY" py-error.txt
grep -q "api_key" py-error.txt

echo "OK"
```

Make executable and run it:

```bash
chmod +x apps/cli/test/scripts/scaffold-smoke.sh
bash apps/cli/test/scripts/scaffold-smoke.sh
```

Expected: prints `OK`. Each scaffold printed the actionable `ProviderConfigError` and exited 1. No stack frames in either output.

- [ ] **Step 8: Commit**

```bash
git add apps/cli/src/templates/ts-agent.ts apps/cli/src/templates/py-agent.ts apps/cli/test/commands/init.test.ts
# Also add the file you modified in Step 5 to declare python-dotenv as a scaffold dep.
git commit -m "feat(cli): scaffolds catch ProviderConfigError; Python loads .env"
```

Include the new `apps/cli/test/scripts/scaffold-smoke.sh` in the commit.

---

### Task 4: Add a streaming step to getting-started.mdx

**Files:**
- Modify: `apps/docs/content/getting-started.mdx`

**Interfaces:**
- Consumes: shipped `EventBus.subscribe` (TS), `InMemoryEventBus.subscribe` (Python re-export).
- Produces: a `<Step>` block showing live event consumption alongside `runtime.send`.

**Note.** The example uses `EventType.AGENT_MESSAGE_COMPLETED` as the explicit termination signal so the consumer loop ends cleanly. The plan's earlier sketch used `consumer.cancel()` or a fire-and-forget IIFE; both work but teach awkward patterns.

- [ ] **Step 1: Read the tail of getting-started.mdx**

Run: `tail -60 apps/docs/content/getting-started.mdx`

Identify where the existing `</Steps>` closes. The new step is inserted immediately before it.

- [ ] **Step 2: Add the streaming step**

Insert before the closing `</Steps>` in `apps/docs/content/getting-started.mdx`:

````mdx
  <Step>
    ### Stream events as they happen

    The examples above read events from the store after the turn completes.
    To consume events live (token deltas, tool calls), subscribe to the bus
    in parallel with `send`.

    <Tabs items={["python", "typescript"]}>
      <Tab value="python">
        ```python
        import asyncio
        import kaji

        async def consume(bus, session_id):
            async for event in bus.subscribe(session_id):
                if event.type == kaji.EventType.AGENT_MESSAGE_DELTA:
                    print(event.delta, end="", flush=True)
                if event.type == kaji.EventType.AGENT_MESSAGE_COMPLETED:
                    return

        async def main():
            bus = kaji.InMemoryEventBus()
            store = kaji.InMemoryEventStore()
            runtime = (
                kaji.AgentBuilder()
                .provider(kaji.get_provider("openai"))
                .build(bus=bus, store=store)
            )
            consumer = asyncio.create_task(consume(bus, "s1"))
            await runtime.send("s1", "Tell me a joke.")
            await consumer

        asyncio.run(main())
        ```
      </Tab>
      <Tab value="typescript">
        ```ts
        import {
          AgentBuilder,
          EventBus,
          EventType,
          InMemoryEventStore,
          openai,
        } from "@kaji/sdk";

        const bus = new EventBus();
        const store = new InMemoryEventStore();
        const runtime = new AgentBuilder()
          .provider(openai())
          .build({ bus, store });

        const consumer = (async () => {
          for await (const event of bus.subscribe("s1")) {
            if (event.type === EventType.AGENT_MESSAGE_DELTA) {
              process.stdout.write(event.delta);
            }
            if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
          }
        })();

        await runtime.send("s1", "Tell me a joke.");
        await consumer;
        ```
      </Tab>
    </Tabs>

    For one-shot streaming without the full runtime, see
    [Streaming](/docs/concepts/streaming) which covers `streamText` (TS) and
    direct provider `generate_stream` (Python).

  </Step>
````

- [ ] **Step 3: Run docs-sync test**

Run: `cd kaji/sdk && pytest tests/test_docs_sync.py -v`
Expected: PASS. Every symbol in the snippet (`InMemoryEventBus`, `InMemoryEventStore`, `AgentBuilder`, `get_provider`, `EventType.AGENT_MESSAGE_DELTA`, `EventType.AGENT_MESSAGE_COMPLETED`, TS `EventBus`, `openai`) is shipped.

- [ ] **Step 4: Typecheck the TS snippet**

Extract the TS block from the inserted MDX into a scratch file and typecheck it against the SDK's published types. From the repo root:

```bash
cat > /tmp/kaji-getting-started.ts <<'EOF'
import {
  AgentBuilder,
  EventBus,
  EventType,
  InMemoryEventStore,
  openai,
} from "@kaji/sdk";

const bus = new EventBus();
const store = new InMemoryEventStore();
const runtime = new AgentBuilder()
  .provider(openai())
  .build({ bus, store });

const consumer = (async () => {
  for await (const event of bus.subscribe("s1")) {
    if (event.type === EventType.AGENT_MESSAGE_DELTA) {
      process.stdout.write(event.delta);
    }
    if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
  }
})();

await runtime.send("s1", "Tell me a joke.");
await consumer;
EOF

cd kaji/ts && bun x tsc --noEmit --target es2022 --module nodenext --moduleResolution nodenext --strict /tmp/kaji-getting-started.ts
```

Expected: zero errors. If `event.delta` is reported as `unknown` or property-not-found on a non-narrowed union, the discriminated-union narrowing isn't working; fix the snippet (likely adding a type guard) before merging.

- [ ] **Step 5: Build the docs site**

Run: `cd apps/docs && bun run build`
Expected: build succeeds. A broken-link warning for `/docs/concepts/streaming` is acceptable here; Task 5 creates that page.

- [ ] **Step 6: Commit**

```bash
git add apps/docs/content/getting-started.mdx
git commit -m "docs: add streaming step to getting-started"
```

---

### Task 5: Add concepts/streaming.mdx and wire it into the nav

**Files:**
- Create: `apps/docs/content/concepts/streaming.mdx`
- Modify: `apps/docs/content/concepts/meta.json` (add `"streaming"` to `pages`)

**Interfaces:**
- Consumes: `streamText`, `EventBus.subscribe`, `EventType`, `CancellationToken` from shipped SDKs.
- Produces: a concept page wired into the docs nav. Examples are TypeScript-typechecked.

**Note about `streamText`.** The TS signature is `streamText(options): StreamTextResult` (synchronous return, not `Promise<StreamTextResult>`) with `messages: ProviderMessage[]` (no `prompt` field). The example below uses the correct shape; the plan's earlier sketch used `await streamText` and `prompt:` — both wrong.

- [ ] **Step 1: Create the streaming reference page**

Create `apps/docs/content/concepts/streaming.mdx`:

````mdx
---
title: Streaming
description: Consume agent events live via the EventBus, or stream a single completion with streamText.
---

Live token output, one screen:

<Tabs items={["python", "typescript"]}>
  <Tab value="python">
    ```python
    import asyncio
    import kaji

    async def consume(bus, session_id):
        async for event in bus.subscribe(session_id):
            if event.type == kaji.EventType.AGENT_MESSAGE_DELTA:
                print(event.delta, end="", flush=True)
            if event.type == kaji.EventType.AGENT_MESSAGE_COMPLETED:
                return

    async def main():
        bus = kaji.InMemoryEventBus()
        store = kaji.InMemoryEventStore()
        runtime = (
            kaji.AgentBuilder()
            .provider(kaji.get_provider("openai"))
            .build(bus=bus, store=store)
        )
        consumer = asyncio.create_task(consume(bus, "s1"))
        await runtime.send("s1", "Tell me a joke.")
        await consumer

    asyncio.run(main())
    ```
  </Tab>
  <Tab value="typescript">
    ```ts
    import {
      AgentBuilder,
      EventBus,
      EventType,
      InMemoryEventStore,
      openai,
    } from "@kaji/sdk";

    const bus = new EventBus();
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(openai())
      .build({ bus, store });

    const consumer = (async () => {
      for await (const event of bus.subscribe("s1")) {
        if (event.type === EventType.AGENT_MESSAGE_DELTA) {
          process.stdout.write(event.delta);
        }
        if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
      }
    })();

    await runtime.send("s1", "Tell me a joke.");
    await consumer;
    ```
  </Tab>
</Tabs>

## How it works

Two ways to read live output: subscribe to the [event bus](/docs/concepts/event-bus) while the runtime turns, or call the one-shot `streamText` helper.

`subscribe(sessionId)` yields every event the runtime emits for that session,
in causal order. Token deltas arrive as `AGENT_MESSAGE_DELTA`; the
`AGENT_MESSAGE_COMPLETED` event signals the end of the reply. Break out of the
`for await` loop or call its `.return()` to close the subscription early.

## Events worth listening for

- `AGENT_MESSAGE_DELTA` — one token chunk of the model's reply.
- `AGENT_MESSAGE_COMPLETED` — the full reply is done.
- `TOOL_CALL_REQUESTED` — the model wants to call a tool.
- `TOOL_CALL_COMPLETED` — the tool returned.
- `TOOL_CALL_FAILED` — the tool errored or arguments were invalid.

The full set is in [`EventType`](/docs/reference/events).

## One-shot streaming with `streamText` (TypeScript)

When the full runtime is overkill — no tools, no history, just a single
model call — use `streamText`. It returns synchronously; `text` and
`toolCalls` resolve as the source stream finishes.

```ts
import { streamText, openai } from "@kaji/sdk";

const { textStream, text } = streamText({
  provider: openai(),
  messages: [{ role: "user", content: "Write a haiku about TypeScript." }],
});

for await (const chunk of textStream) {
  process.stdout.write(chunk);
}

console.log("\nfinal:", await text);
```

The Python equivalent is `provider.generate_stream(...)` directly; see
[Providers](/docs/concepts/providers).

## Cancellation

Both paths honor a [`CancellationToken`](/docs/concepts/cancellation):

```ts
import { CancellationToken } from "@kaji/sdk";

const token = new CancellationToken();
setTimeout(() => token.cancel(), 5000);

await runtime.send("s1", "Long-running prompt...", { cancellationToken: token });
```

```python
from kaji import CancellationToken

token = CancellationToken()
await runtime.send("s1", "Long-running prompt...", cancellation_token=token)
```
````

- [ ] **Step 2: Add the page to the nav (mandatory)**

Open `apps/docs/content/concepts/meta.json`. The current contents are:

```json
{ "title": "Concepts", "pages": ["events", "session-state", "runtime", "tool-registry", "event-bus", "providers"] }
```

Replace with:

```json
{ "title": "Concepts", "pages": ["events", "streaming", "session-state", "runtime", "tool-registry", "event-bus", "providers"] }
```

`streaming` slots in right after `events` because it's the most common next question after a successful hello-world: "how do I read these live?" Burying it at the end of the list (the obvious wrong choice) hides the page from the readers who need it most. Fumadocs reads this array as the authoritative sidebar order; without this edit, `streaming.mdx` will not appear in navigation at all.

- [ ] **Step 3: Run docs-sync**

Run: `cd kaji/sdk && pytest tests/test_docs_sync.py -v`
Expected: PASS. The test walks every code block and verifies referenced symbols are exported. The page references:

- TS: `AgentBuilder`, `EventBus`, `EventType`, `InMemoryEventStore`, `openai`, `streamText`, `CancellationToken`
- Python: `InMemoryEventBus`, `InMemoryEventStore`, `AgentBuilder`, `get_provider`, `EventType`, `CancellationToken`

All shipped today.

- [ ] **Step 4: Typecheck the TS code blocks**

From the repo root:

```bash
cat > /tmp/kaji-streaming.ts <<'EOF'
import {
  AgentBuilder,
  EventBus,
  EventType,
  InMemoryEventStore,
  openai,
  streamText,
  CancellationToken,
} from "@kaji/sdk";

const bus = new EventBus();
const store = new InMemoryEventStore();
const runtime = new AgentBuilder()
  .provider(openai())
  .build({ bus, store });

const consumer = (async () => {
  for await (const event of bus.subscribe("s1")) {
    if (event.type === EventType.AGENT_MESSAGE_DELTA) {
      process.stdout.write(event.delta);
    }
    if (event.type === EventType.AGENT_MESSAGE_COMPLETED) break;
  }
})();

await runtime.send("s1", "Tell me a joke.");
await consumer;

const { textStream, text } = streamText({
  provider: openai(),
  messages: [{ role: "user", content: "Write a haiku about TypeScript." }],
});

for await (const chunk of textStream) {
  process.stdout.write(chunk);
}

console.log("\nfinal:", await text);

const token = new CancellationToken();
setTimeout(() => token.cancel(), 5000);
await runtime.send("s1", "Long-running prompt...", { cancellationToken: token });
EOF

cd kaji/ts && bun x tsc --noEmit --target es2022 --module nodenext --moduleResolution nodenext --strict /tmp/kaji-streaming.ts
```

Expected: zero type errors. If any narrowing fails (`event.delta` not on the union without a guard, etc.), fix the snippet before merging — do not loosen the typecheck.

- [ ] **Step 5: Build the docs site**

Run: `cd apps/docs && bun run build`
Expected: build succeeds. The link from getting-started (Task 4) to `/docs/concepts/streaming` now resolves.

- [ ] **Step 6: Commit**

```bash
git add apps/docs/content/concepts/streaming.mdx apps/docs/content/concepts/meta.json
git commit -m "docs: streaming reference page wired into concepts nav"
```

---

### Task 6: Clarify `.tool()` polymorphism in concepts/runtime.mdx

**Files:**
- Modify: `apps/docs/content/concepts/runtime.mdx`

**Interfaces:**
- Consumes: nothing.
- Produces: the runtime page names both `BoundTool` and `Integration` as valid arguments to `.tool()`, with cross-links.

- [ ] **Step 1: Locate the `.tool()` block**

```bash
grep -n "tool(" apps/docs/content/concepts/runtime.mdx
```

Find the existing description (review found it near line 15).

- [ ] **Step 2: Replace the block**

Replace the existing `.tool()` documentation with (preserve the surrounding page conventions and heading level):

```mdx
### `.tool(integrable)`

Register a tool with the builder. `integrable` may be either:

- a `BoundTool` returned by `functionTool` (the lightweight path for a
  single function), or
- an instance of an `Integration` subclass (the bundled path for
  multi-tool namespaces, OAuth-backed services, etc.).

Both forms implement the `Integrable` protocol. Call `.tool(...)` once per
tool or bundle; the builder accumulates them.
```

Do not add `/docs/reference/...` links — those pages do not exist yet, and the docs build will warn or 404. Readers who want signatures `cmd-click` the symbol in their editor.

- [ ] **Step 3: Run docs-sync**

Run: `cd kaji/sdk && pytest tests/test_docs_sync.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/docs/content/concepts/runtime.mdx
git commit -m "docs: clarify .tool() polymorphism for BoundTool and Integration"
```

---

## Self-Review Notes

**Spec coverage check.** DX friction from the 2026-06-23 review:

| Friction item | Task |
|---|---|
| Generic API-key errors | Tasks 1, 2 |
| Python `.env` written but not loaded | Task 3 (load_dotenv) |
| No streaming docs / examples | Tasks 4, 5 |
| Scaffolds dump stack traces | Task 3 |
| Python two-step turn (`append` + `run_turn`) | Task 3 (scaffold uses `send()`) |
| `.tool()` polymorphism undocumented | Task 6 |
| Streaming concept page absent from nav | Task 5 (meta.json edit) |

**Out of scope** (separately tracked):
- Tool-arg validation errors that don't quote JSON pointers — needs structured-output spec.
- No `ToolHandler<T>` type-inference threading — needs Zod-schema-aware overload; brainstorm first.
- Tool-name sanitization silent mutation — covered by SDK hardening plan, Task 7.
- Zero-install "try mode" CLI command (e.g. `bunx @kaji/cli try openai "What's the weather?"`) — flagged as the highest-leverage next DX investment; belongs in a follow-up CLI spec, not this polish plan.
- Doc URL inclusion in error messages — deferred until `kaji.dev` is confirmed live. Today's messages point at the local `.env`, the shell, and the constructor argument.

**Placeholder scan.** No "TBD" / "add appropriate". All code blocks are complete.

**Type and symbol consistency.**
- `ProviderConfigError` — exported from both SDKs (TS [index.ts:72](kaji/ts/src/index.ts:72); Python lazy-loaded).
- `runtime.send(sessionId, content, options?)` — TS shipped at [runtime.ts:140](kaji/ts/src/runtime/runtime.ts:140), Python shipped at [runtime.py:120](kaji/sdk/kaji/runtime/agents/runtime.py:120). Python signature is `send(session_id, content, cancellation_token=None)` — positional + keyword, not an options dict. The cancellation example in Task 5 uses the correct shape per language.
- `RunTurnOptions = { cancellationToken?: CancellationToken }` — TS shipped at [runtime.ts:63](kaji/ts/src/runtime/runtime.ts:63). The Task 5 TS cancellation snippet uses this correctly.
- `streamText(options): StreamTextResult` — synchronous return, `messages: ProviderMessage[]` field. Confirmed at [oneshot.ts:76](kaji/ts/src/runtime/oneshot.ts:76).
- `concepts/meta.json` — `pages` array is authoritative. Confirmed at `apps/docs/content/concepts/meta.json`. Task 5 edits it explicitly.

**DevEx review fixes applied (from /plan-devex-review):**

- **D1.** Error messages now include three concrete actions, leading with `.env`. Three providers (OpenAI, Anthropic, Python equivalents) updated.
- **D2.** Public URL dropped from all error messages. Per user decision, errors point at local `.env`, shell, and constructor. Revisit when `kaji.dev` is confirmed live.
- **D3.** Task 1 test no longer mutates `process.env`. Tests constructor behavior directly.
- **D4.** Task 3 adds `load_dotenv()` to the Python scaffold and `python-dotenv` to its generated deps. Resolves the silent-failure-after-editing-.env class.
- **D5.** Task 5 makes the `meta.json` edit mandatory, not conditional. The "Fumadocs auto-discovers" hedge was wrong.
- **D6.** Tasks 4 and 5 use `EventType.AGENT_MESSAGE_COMPLETED` as the explicit termination signal in `for await` loops. No fire-and-forget IIFE, no `consumer.cancel()`.
- **D7.** Task 5 streamText snippet uses `messages: [{ role, content }]` (not `prompt`) and removes the bogus `await` on a synchronous-returning function.
- **D8.** (withdrawn during verification) `runtime.send(..., { cancellationToken })` is the correct TS shape.
- **D9.** "Try mode" CLI flagged in Out of Scope as the next DX investment.
- **D10.** Task 3 smoke test uses `$(git rev-parse --show-toplevel)` instead of an absolute path.
- **D11.** Task 3 smoke test uses `grep -q` assertions for `OPENAI_API_KEY`, `.env`, and absence of stack frames. Captures the regression risk that the scaffold's catch handler is later loosened.

## GSTACK REVIEW REPORT

| Run | Status | Key findings |
|---|---|---|
| Internal DevEx review (sonnet, 2026-06-23) | Applied | D1, D3, D4, D5, D6, D7, D10, D11 — all incorporated above. D2 resolved by user choice (drop URL). D8 withdrawn during verification. D9 documented as Out of Scope (next-spec). |
| Internal design review (sonnet, 2026-06-23) | Applied | G1, G2, G3, G4, G5, G6, G7, G8, G9, G10 — all incorporated above. |

Design review fixes:
- **G1 + G2 + G3.** Error messages switched from multi-line dash-bullets to a single sentence. No `.env` assumption. Tasks 1 and 2 rewritten; new convention captured in Global Constraints; existing `OAuthError` single-sentence style is preserved (no codebase-wide rewrite needed because the new convention matches what's already there).
- **G4.** Streaming page opener rewritten from "There are two ways to read output as it is generated" to terse lead-with-example; "How it works" section follows.
- **G5.** Tab order convention `["python", "typescript"]` added to Global Constraints. Locks future docs against accidental reversal.
- **G6.** Streaming page restructured: working example at the top, explanation below. Reader hitting the page from search sees the magical moment in the first screen.
- **G7.** `concepts/meta.json` `pages` order changed: `streaming` is now second (right after `events`), not last. Rationale documented in Task 5 Step 2.
- **G8.** Reference links to `/docs/reference/function-tool` and `/docs/reference/integration` removed from Task 6 — those pages do not exist yet.
- **G9.** No docs URL in error messages — accepted as the price of not shipping a broken link. Already captured in Global Constraints.
- **G10.** Task 3 smoke test extracted to `apps/cli/test/scripts/scaffold-smoke.sh`. The plan now references the script; the script ships under version control and can be wired into CI separately.

Also dropped: `.env` grep assertions in the smoke test (replaced with `apiKey` / `api_key` grep) because the new single-sentence errors do not mention `.env`.

VERDICT: Plan revised. Error messages terse and terminal-safe. Streaming page IA leads with the example. Concept nav rebalanced. Reference-link landmines removed. The scaffold smoke test is checked-in and CI-ready. TTHW target: 2-3 min (Competitive tier).

NO UNRESOLVED DECISIONS
