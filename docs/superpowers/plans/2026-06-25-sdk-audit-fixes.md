# SDK Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four highest-leverage gaps surfaced by the 2026-06-25 audit of `kaji/sdk` (Python) and `kaji/ts` (TypeScript): (1) export the implemented-but-hidden Python types, (2) add live integration tests for Gemini + Kimi, (3) bring the TS CLI to rough parity with Python (`list-integrations`, `init`, working dispatch), (4) wire the approval flow end-to-end in TS with a CLI fallback handler. STT/TTS modalities for TS are explicitly out of scope.

**Architecture:** Each fix is a thin slice that ships independently. (1) is a pure surface change to `kaji/__init__.py`'s lazy map. (2) follows the existing opt-in `pytest -m live` convention from `tests/integration/test_anthropic_provider.py`. (3) extends `kaji/ts/src/cli/index.ts` with a dispatch table plus two new commands that read the same `registry/` directory the existing `add` command uses. (4) plumbs three already-defined approval events through the existing `EventBus` and `replaySession`, then ships a `cliApprovalHandler` that prompts on stdin.

**Tech Stack:** Python 3.11+, pytest with asyncio_mode=auto and a `live` marker; TypeScript with vitest, tsup, bun; existing `EventBus` / `ToolPlanner` / `replaySession` primitives.

## Global Constraints

- No new runtime dependencies in either SDK. CLI prompts use Node `readline` from the standard library; tests use existing pytest + vitest.
- Live provider tests must be skipped by default and only run when the matching env var is set (`KAJI_LIVE_GEMINI=1`, `KAJI_LIVE_KIMI=1`) and the API key is present, mirroring the existing pattern at `kaji/sdk/tests/integration/test_anthropic_provider.py`.
- Python additions must preserve the lazy-import contract of `kaji/sdk/kaji/__init__.py`: no eager imports, every new entry goes into `_LAZY`.
- TypeScript additions must not introduce `any`, `@ts-ignore`, or `as unknown as` casts. The audit found zero of each; keep it that way.
- TS CLI commands must be tested through their handler functions, not by shelling out — match the existing `cli/add.ts` test pattern.
- All commits go to a feature branch `feat/sdk-audit-fixes`, never directly to `main`. Use `bun`, never `npm`/`yarn`/`pnpm`, for any TS package operations.
- Writing style: terse, no em-dashes, no slop.

---

## File Structure

**Python (`kaji/sdk/`)**
- Modify: `kaji/sdk/kaji/__init__.py` — extend `_LAZY` with knowledge, session/history stores, retriever protocols, payload translators.
- Modify: `kaji/sdk/kaji/runtime/sessions/__init__.py` — re-export `SessionStore`, `InMemorySessionStore`, `SessionRecord`, `HistoryStore`, `InMemoryHistoryStore`.
- Modify: `kaji/sdk/kaji/runtime/agents/__init__.py` — re-export `HistoryStore`, `InMemoryHistoryStore` so the lazy map has a stable module to target.
- Modify: `kaji/sdk/kaji/runtime/tools/__init__.py` — re-export `Embedder`, `EmbeddingCache`, `ToolRetriever`, `build_tools_payload`, `spec_to_neutral`, `to_openai`, `to_anthropic`, `to_gemini`.
- Create: `kaji/sdk/tests/test_public_api.py` — asserts every roadmap-claimed public name is reachable via `from kaji import X`.
- Create: `kaji/sdk/tests/integration/test_gemini_provider.py` — live `pytest -m live` smoke test for `generate` and `generate_stream` with a tool call.
- Create: `kaji/sdk/tests/integration/test_kimi_provider.py` — live `pytest -m live` smoke test for `generate` and `generate_stream` with a tool call.

**TypeScript (`kaji/ts/`)**
- Modify: `kaji/ts/src/cli/index.ts` — replace inline branch with a dispatch map; add `--help` for all commands.
- Create: `kaji/ts/src/cli/list_integrations.ts` — reads `registry/` and prints `name  description`.
- Create: `kaji/ts/src/cli/init.ts` — scaffolds a minimal TS starter (`package.json`, `tsconfig.json`, `agent.ts`, `.env.example`) into a target directory.
- Modify: `kaji/ts/src/events/types.ts` and `kaji/ts/src/events/schemas.ts` — confirm `TOOL_APPROVAL_REQUESTED / APPROVED / REJECTED` are already typed; no schema change.
- Modify: `kaji/ts/src/sessions/replay.ts` — project the three approval events into a new `pendingApprovals` / `approvedToolIds` / `rejectedToolIds` block of `SessionState`.
- Modify: `kaji/ts/src/tools/planner.ts` — when `ApprovalHandler` exists, emit `TOOL_APPROVAL_REQUESTED` on the bus before awaiting, emit `APPROVED` or `REJECTED` after.
- Create: `kaji/ts/src/tools/cli_approval_handler.ts` — default stdin/readline handler that prints the tool name + args and reads `y`/`n`.
- Modify: `kaji/ts/src/index.ts` — export `cliApprovalHandler` and the approval event types.
- Create: `kaji/ts/tests/cli/list_integrations.test.ts` and `kaji/ts/tests/cli/init.test.ts`.
- Create: `kaji/ts/tests/tools/cli_approval_handler.test.ts`.
- Create: `kaji/ts/tests/tools/approval_flow.test.ts` — planner emits the three events in order; replay projects them.

---

## Task 1: Re-export Python building blocks from their owning subpackages

**Files:**
- Modify: `kaji/sdk/kaji/runtime/sessions/__init__.py`
- Modify: `kaji/sdk/kaji/runtime/agents/__init__.py`
- Modify: `kaji/sdk/kaji/runtime/tools/__init__.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: stable import paths used by Task 2's lazy map: `from kaji.runtime.sessions import SessionStore, InMemorySessionStore, SessionRecord`; `from kaji.runtime.agents import HistoryStore, InMemoryHistoryStore`; `from kaji.runtime.tools import Embedder, EmbeddingCache, ToolRetriever, build_tools_payload, spec_to_neutral, to_openai, to_anthropic, to_gemini`.

- [ ] **Step 1: Read the three subpackage `__init__.py` files to confirm current exports**

Run:
```
cat kaji/sdk/kaji/runtime/sessions/__init__.py kaji/sdk/kaji/runtime/agents/__init__.py kaji/sdk/kaji/runtime/tools/__init__.py
```
Expected: see what's currently exported so the new entries are merged, not overwritten.

- [ ] **Step 2: Add the new re-exports to `kaji/sdk/kaji/runtime/sessions/__init__.py`**

Append to the existing `__all__` and add the imports:
```python
from kaji.runtime.sessions.store import (
    InMemorySessionStore,
    SessionRecord,
    SessionStore,
)
from kaji.runtime.agents.history import HistoryStore, InMemoryHistoryStore
```
Add `"InMemorySessionStore", "SessionRecord", "SessionStore", "HistoryStore", "InMemoryHistoryStore"` to `__all__`.

- [ ] **Step 3: Add the new re-exports to `kaji/sdk/kaji/runtime/agents/__init__.py`**

```python
from kaji.runtime.agents.history import HistoryStore, InMemoryHistoryStore
```
Add `"HistoryStore", "InMemoryHistoryStore"` to `__all__`.

- [ ] **Step 4: Add the new re-exports to `kaji/sdk/kaji/runtime/tools/__init__.py`**

```python
from kaji.runtime.tools.retriever import Embedder, EmbeddingCache, ToolRetriever
from kaji.runtime.tools.payload import (
    build_tools_payload,
    spec_to_neutral,
    to_anthropic,
    to_gemini,
    to_openai,
)
```
Add each name to `__all__`.

- [ ] **Step 5: Run existing tests to confirm no regression**

Run: `cd kaji/sdk && poetry run pytest -x -q`
Expected: PASS (existing test count unchanged).

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/runtime/sessions/__init__.py kaji/sdk/kaji/runtime/agents/__init__.py kaji/sdk/kaji/runtime/tools/__init__.py
git commit -m "feat(sdk): re-export hidden building blocks from their subpackages"
```

---

## Task 2: Extend `kaji/__init__.py` lazy map with the new public names + assertion test

**Files:**
- Modify: `kaji/sdk/kaji/__init__.py`
- Create: `kaji/sdk/tests/test_public_api.py`

**Interfaces:**
- Consumes: subpackage re-exports from Task 1.
- Produces: `from kaji import Chunk, Document, DocumentRAG, VectorStore, InMemoryVectorStore, SessionStore, InMemorySessionStore, SessionRecord, HistoryStore, InMemoryHistoryStore, Embedder, EmbeddingCache, ToolRetriever, build_tools_payload, spec_to_neutral, to_openai, to_anthropic, to_gemini`.

- [ ] **Step 1: Write the failing test first**

Create `kaji/sdk/tests/test_public_api.py`:
```python
"""Every name the roadmap promises is importable from `kaji` top-level."""
import importlib
import pytest

PUBLIC_NAMES = [
    # Knowledge / RAG (P3.14 — roadmap claimed DONE, was missing)
    "Chunk", "Document", "DocumentRAG", "VectorStore", "InMemoryVectorStore",
    # Session + history stores (pluggable infra)
    "SessionStore", "InMemorySessionStore", "SessionRecord",
    "HistoryStore", "InMemoryHistoryStore",
    # Tool retriever + embedder protocols
    "Embedder", "EmbeddingCache", "ToolRetriever",
    # Neutral tool payload translators (P1.7)
    "build_tools_payload", "spec_to_neutral",
    "to_openai", "to_anthropic", "to_gemini",
]

@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_public_name_importable(name: str) -> None:
    kaji = importlib.import_module("kaji")
    assert hasattr(kaji, name), f"kaji.{name} is not exposed via kaji.__init__._LAZY"

def test_no_eager_infra_import() -> None:
    """`import kaji` must not eagerly import knowledge, providers, or infra."""
    import sys
    for mod in list(sys.modules):
        if mod.startswith(("kaji.knowledge", "kaji.runtime.providers.openai",
                           "kaji.runtime.providers.anthropic", "kaji.infra.realtime")):
            sys.modules.pop(mod, None)
    sys.modules.pop("kaji", None)
    importlib.import_module("kaji")
    assert "kaji.knowledge.rag" not in sys.modules
    assert "kaji.runtime.providers.openai" not in sys.modules
    assert "kaji.infra.realtime.redis" not in sys.modules
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd kaji/sdk && poetry run pytest tests/test_public_api.py -v`
Expected: FAIL (most parametrized names AttributeError).

- [ ] **Step 3: Extend `_LAZY` in `kaji/sdk/kaji/__init__.py`**

Add these entries (keep the existing alphabetical grouping):
```python
    # Knowledge / RAG
    "Chunk": "kaji.knowledge",
    "Document": "kaji.knowledge",
    "DocumentRAG": "kaji.knowledge",
    "Embedder": "kaji.runtime.tools",
    "EmbeddingCache": "kaji.runtime.tools",
    "HistoryStore": "kaji.runtime.agents",
    "InMemoryHistoryStore": "kaji.runtime.agents",
    "InMemorySessionStore": "kaji.runtime.sessions",
    "InMemoryVectorStore": "kaji.knowledge",
    "SessionRecord": "kaji.runtime.sessions",
    "SessionStore": "kaji.runtime.sessions",
    "ToolRetriever": "kaji.runtime.tools",
    "VectorStore": "kaji.knowledge",
    "build_tools_payload": "kaji.runtime.tools",
    "spec_to_neutral": "kaji.runtime.tools",
    "to_anthropic": "kaji.runtime.tools",
    "to_gemini": "kaji.runtime.tools",
    "to_openai": "kaji.runtime.tools",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd kaji/sdk && poetry run pytest tests/test_public_api.py -v`
Expected: PASS (all parametrized names + the no-eager-import guard).

- [ ] **Step 5: Run the full Python suite**

Run: `cd kaji/sdk && poetry run pytest -x -q`
Expected: PASS, total test count = previous + 19 (18 parametrized + 1 guard).

- [ ] **Step 6: Commit**

```bash
git add kaji/sdk/kaji/__init__.py kaji/sdk/tests/test_public_api.py
git commit -m "feat(sdk): expose knowledge, session/history stores, retriever, payload translators in public API"
```

---

## Task 3: Live integration test for Gemini provider

**Files:**
- Create: `kaji/sdk/tests/integration/test_gemini_provider.py`

**Interfaces:**
- Consumes: `from kaji import get_provider, ToolSpec, UserMessage`; reads `GEMINI_API_KEY` from env; gated on `KAJI_LIVE_GEMINI=1`.
- Produces: nothing for downstream tasks; pure verification.

- [ ] **Step 1: Confirm the existing Anthropic live test pattern**

Run: `cat kaji/sdk/tests/integration/test_anthropic_provider.py`
Expected: see the env-gating decorator, the `@pytest.mark.live`, and the minimal-loop shape to copy.

- [ ] **Step 2: Write the live test**

Create `kaji/sdk/tests/integration/test_gemini_provider.py`:
```python
"""Live smoke test for the Gemini provider.

Opt-in: set KAJI_LIVE_GEMINI=1 and GEMINI_API_KEY=... then run
    pytest -m live tests/integration/test_gemini_provider.py
"""
from __future__ import annotations

import os
import pytest

from kaji import UserMessage, get_provider
from kaji.runtime.tools.registry import ToolSpec

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("KAJI_LIVE_GEMINI") != "1"
        or not os.environ.get("GEMINI_API_KEY"),
        reason="set KAJI_LIVE_GEMINI=1 and GEMINI_API_KEY to run",
    ),
]


def _echo_tool() -> ToolSpec:
    return ToolSpec(
        name="echo",
        description="Echoes the provided text back to the caller.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


@pytest.mark.asyncio
async def test_gemini_generate_returns_text() -> None:
    provider = get_provider("gemini")
    result = await provider.generate(
        messages=[UserMessage(content="Reply with the single word: pong.")],
        tools=[],
    )
    assert isinstance(result.text, str) and result.text.strip()


@pytest.mark.asyncio
async def test_gemini_generate_stream_emits_chunks() -> None:
    provider = get_provider("gemini")
    chunks: list[str] = []
    async for delta in provider.generate_stream(
        messages=[UserMessage(content="Count from 1 to 3.")],
        tools=[],
    ):
        if delta.text:
            chunks.append(delta.text)
    assert chunks, "expected at least one streamed text chunk"


@pytest.mark.asyncio
async def test_gemini_tool_call_round_trip() -> None:
    provider = get_provider("gemini")
    result = await provider.generate(
        messages=[UserMessage(content="Use the echo tool with text='hi'.")],
        tools=[_echo_tool()],
    )
    assert result.tool_calls, "expected Gemini to emit a tool call"
    assert result.tool_calls[0].name == "echo"
```

- [ ] **Step 3: Verify the test skips cleanly without env vars set**

Run: `cd kaji/sdk && poetry run pytest tests/integration/test_gemini_provider.py -v`
Expected: 3 SKIPPED with the documented reason. No failures.

- [ ] **Step 4: (Manual, optional) Verify against the live API**

If you have a key, run:
```
KAJI_LIVE_GEMINI=1 GEMINI_API_KEY=... \
  poetry run pytest -m live tests/integration/test_gemini_provider.py -v
```
Expected: 3 PASS. If they fail, file a follow-up; do not block the commit on it. The unit tests at `kaji/sdk/tests/test_providers_gemini_stream.py` remain the gating signal in CI.

- [ ] **Step 5: Commit**

```bash
git add kaji/sdk/tests/integration/test_gemini_provider.py
git commit -m "test(sdk): add opt-in live integration test for Gemini provider"
```

---

## Task 4: Live integration test for Kimi provider

**Files:**
- Create: `kaji/sdk/tests/integration/test_kimi_provider.py`

**Interfaces:**
- Consumes: `from kaji import get_provider, ToolSpec, UserMessage`; reads `OPENROUTER_API_KEY` (or `KIMI_API_KEY` depending on configured endpoint) from env; gated on `KAJI_LIVE_KIMI=1`.
- Produces: nothing for downstream tasks.

- [ ] **Step 1: Confirm which env vars the Kimi provider actually reads**

Run: `grep -nE "os\.environ|getenv|Settings|api_key" kaji/sdk/kaji/runtime/providers/kimi.py`
Expected: identify the auth env var so the skipif matches reality. The provider supports OpenRouter and Cloudflare endpoints; pick `OPENROUTER_API_KEY` as the default gate.

- [ ] **Step 2: Write the live test**

Create `kaji/sdk/tests/integration/test_kimi_provider.py`:
```python
"""Live smoke test for the Kimi provider (OpenRouter endpoint).

Opt-in: set KAJI_LIVE_KIMI=1 and OPENROUTER_API_KEY=... then run
    pytest -m live tests/integration/test_kimi_provider.py
"""
from __future__ import annotations

import os
import pytest

from kaji import UserMessage, get_provider
from kaji.runtime.tools.registry import ToolSpec

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("KAJI_LIVE_KIMI") != "1"
        or not os.environ.get("OPENROUTER_API_KEY"),
        reason="set KAJI_LIVE_KIMI=1 and OPENROUTER_API_KEY to run",
    ),
]


def _echo_tool() -> ToolSpec:
    return ToolSpec(
        name="echo",
        description="Echoes the provided text back to the caller.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


@pytest.mark.asyncio
async def test_kimi_generate_returns_text() -> None:
    provider = get_provider("kimi")
    result = await provider.generate(
        messages=[UserMessage(content="Reply with the single word: pong.")],
        tools=[],
    )
    assert isinstance(result.text, str) and result.text.strip()


@pytest.mark.asyncio
async def test_kimi_generate_stream_emits_chunks() -> None:
    provider = get_provider("kimi")
    chunks: list[str] = []
    async for delta in provider.generate_stream(
        messages=[UserMessage(content="Count from 1 to 3.")],
        tools=[],
    ):
        if delta.text:
            chunks.append(delta.text)
    assert chunks, "expected at least one streamed text chunk"


@pytest.mark.asyncio
async def test_kimi_tool_call_round_trip() -> None:
    provider = get_provider("kimi")
    result = await provider.generate(
        messages=[UserMessage(content="Use the echo tool with text='hi'.")],
        tools=[_echo_tool()],
    )
    assert result.tool_calls, "expected Kimi to emit a tool call"
    assert result.tool_calls[0].name == "echo"
```

- [ ] **Step 3: Verify the test skips cleanly without env vars set**

Run: `cd kaji/sdk && poetry run pytest tests/integration/test_kimi_provider.py -v`
Expected: 3 SKIPPED.

- [ ] **Step 4: Commit**

```bash
git add kaji/sdk/tests/integration/test_kimi_provider.py
git commit -m "test(sdk): add opt-in live integration test for Kimi provider"
```

---

## Task 5: TS CLI dispatch table + working `--help`

**Files:**
- Modify: `kaji/ts/src/cli/index.ts`

**Interfaces:**
- Consumes: existing `add` handler in `kaji/ts/src/cli/add.ts`.
- Produces: a `Command` type and a `COMMANDS` dispatch map consumed by Tasks 6 and 7: `interface Command { run(rest: string[], opts: { registryRoot: string }): Promise<number>; help: string; }`.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/cli/dispatch.test.ts`:
```typescript
import { describe, expect, it } from "vitest";
import { runCli } from "../../src/cli/index";

describe("kaji cli dispatch", () => {
  it("prints help and exits 0 on --help", async () => {
    const lines: string[] = [];
    const code = await runCli(["--help"], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/usage: kaji/);
    expect(lines.join("\n")).toMatch(/add/);
  });

  it("exits 1 with usage when no command given", async () => {
    const lines: string[] = [];
    const code = await runCli([], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
    });
    expect(code).toBe(1);
  });

  it("exits 1 on unknown command", async () => {
    const lines: string[] = [];
    const code = await runCli(["frobnicate"], {
      registryRoot: "/tmp",
      log: (m) => lines.push(m),
      err: (m) => lines.push(m),
    });
    expect(code).toBe(1);
    expect(lines.join("\n")).toMatch(/Unknown command/);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd kaji/ts && bun run test tests/cli/dispatch.test.ts`
Expected: FAIL — `runCli` not exported.

- [ ] **Step 3: Refactor `kaji/ts/src/cli/index.ts` to expose `runCli` and a dispatch table**

Replace the file contents with:
```typescript
/**
 * CLI entry for `kaji`. Resolves the registry shipped inside the npm package
 * and dispatches subcommands.
 *
 * Built by tsup with a `#!/usr/bin/env node` banner so it works as a bin.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { add } from "./add";

export interface RunOptions {
  registryRoot: string;
  log?: (msg: string) => void;
  err?: (msg: string) => void;
}

export interface Command {
  describe: string;
  usage: string;
  run(rest: string[], opts: RunOptions): Promise<number>;
}

export const COMMANDS: Record<string, Command> = {
  add: {
    describe: "Copy an integration's TypeScript source into your project.",
    usage: "kaji add <name> [--out <dir>] [--force]",
    run: (rest, opts) => Promise.resolve(add(rest, { registryRoot: opts.registryRoot })),
  },
};

function printHelp(log: (m: string) => void): void {
  log("usage: kaji <command> [args]");
  log("");
  log("commands:");
  for (const [name, cmd] of Object.entries(COMMANDS)) {
    log(`  ${name.padEnd(20)} ${cmd.describe}`);
  }
}

export async function runCli(argv: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  const [cmd, ...rest] = argv;
  if (cmd === undefined) {
    printHelp(log);
    return 1;
  }
  if (cmd === "-h" || cmd === "--help") {
    printHelp(log);
    return 0;
  }
  const handler = COMMANDS[cmd];
  if (!handler) {
    err(`Unknown command: ${cmd}`);
    printHelp(err);
    return 1;
  }
  if (rest[0] === "-h" || rest[0] === "--help") {
    log(`usage: ${handler.usage}`);
    return 0;
  }
  return handler.run(rest, opts);
}

async function main(): Promise<number> {
  const here = dirname(fileURLToPath(import.meta.url));
  const registryRoot = join(here, "..", "..", "registry");
  return runCli(process.argv.slice(2), { registryRoot });
}

// Only execute when invoked as a script, not when imported by tests.
if (import.meta.url === `file://${process.argv[1]}`) {
  main().then((code) => process.exit(code));
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd kaji/ts && bun run test tests/cli/dispatch.test.ts`
Expected: 3 PASS.

- [ ] **Step 5: Run the existing CLI tests to confirm no regression**

Run: `cd kaji/ts && bun run test tests/cli/`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/cli/index.ts kaji/ts/tests/cli/dispatch.test.ts
git commit -m "feat(ts): cli dispatch table with working --help and unknown-command handling"
```

---

## Task 6: `kaji list-integrations` TS command

**Files:**
- Create: `kaji/ts/src/cli/list_integrations.ts`
- Modify: `kaji/ts/src/cli/index.ts` (register the command in `COMMANDS`)
- Create: `kaji/ts/tests/cli/list_integrations.test.ts`

**Interfaces:**
- Consumes: `RunOptions` from Task 5.
- Produces: nothing for downstream tasks.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/cli/list_integrations.test.ts`:
```typescript
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { listIntegrations } from "../../src/cli/list_integrations";

function buildFixture(): string {
  const root = mkdtempSync(join(tmpdir(), "kaji-registry-"));
  mkdirSync(join(root, "echo"));
  writeFileSync(
    join(root, "echo", "manifest.json"),
    JSON.stringify({ name: "echo", description: "Echo a string back." }),
  );
  mkdirSync(join(root, "weather"));
  writeFileSync(
    join(root, "weather", "manifest.json"),
    JSON.stringify({ name: "weather", description: "Look up the weather." }),
  );
  return root;
}

describe("kaji list-integrations", () => {
  it("prints every integration with its description", async () => {
    const registryRoot = buildFixture();
    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    const out = lines.join("\n");
    expect(out).toMatch(/echo\s+Echo a string back\./);
    expect(out).toMatch(/weather\s+Look up the weather\./);
  });

  it("returns 0 and a friendly note for an empty registry", async () => {
    const registryRoot = mkdtempSync(join(tmpdir(), "kaji-registry-empty-"));
    const lines: string[] = [];
    const code = await listIntegrations([], { registryRoot, log: (m) => lines.push(m) });
    expect(code).toBe(0);
    expect(lines.join("\n")).toMatch(/No integrations found/);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd kaji/ts && bun run test tests/cli/list_integrations.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the command**

Create `kaji/ts/src/cli/list_integrations.ts`:
```typescript
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import type { RunOptions } from "./index";

interface Manifest {
  name: string;
  description?: string;
}

export async function listIntegrations(_rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  let entries: string[];
  try {
    entries = readdirSync(opts.registryRoot).filter((name) => {
      const full = join(opts.registryRoot, name);
      return statSync(full).isDirectory();
    });
  } catch {
    log("No integrations found.");
    return 0;
  }
  const rows: Array<[string, string]> = [];
  for (const name of entries.sort()) {
    const manifestPath = join(opts.registryRoot, name, "manifest.json");
    let manifest: Manifest = { name };
    try {
      manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest;
    } catch {
      // Treat missing/unreadable manifest as a still-listable integration.
    }
    rows.push([manifest.name, manifest.description ?? ""]);
  }
  if (rows.length === 0) {
    log("No integrations found.");
    return 0;
  }
  const width = Math.max(...rows.map(([n]) => n.length));
  for (const [name, desc] of rows) {
    log(`${name.padEnd(width)}  ${desc}`);
  }
  return 0;
}
```

- [ ] **Step 4: Register the command in `kaji/ts/src/cli/index.ts`**

In the `COMMANDS` object, add:
```typescript
  "list-integrations": {
    describe: "List integrations available via `kaji add`.",
    usage: "kaji list-integrations",
    run: (rest, opts) => listIntegrations(rest, opts),
  },
```
And add `import { listIntegrations } from "./list_integrations";` at the top.

- [ ] **Step 5: Run the tests**

Run: `cd kaji/ts && bun run test tests/cli/`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/cli/list_integrations.ts kaji/ts/src/cli/index.ts kaji/ts/tests/cli/list_integrations.test.ts
git commit -m "feat(ts): list-integrations cli command"
```

---

## Task 7: `kaji init` TS command (project scaffold)

**Files:**
- Create: `kaji/ts/src/cli/init.ts`
- Modify: `kaji/ts/src/cli/index.ts` (register in `COMMANDS`)
- Create: `kaji/ts/tests/cli/init.test.ts`

**Interfaces:**
- Consumes: `RunOptions` from Task 5.
- Produces: nothing for downstream tasks.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/cli/init.test.ts`:
```typescript
import { existsSync, mkdtempSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { init } from "../../src/cli/init";

describe("kaji init", () => {
  it("scaffolds package.json, tsconfig.json, agent.ts, .env.example", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-"));
    const lines: string[] = [];
    const code = await init(["--out", out], { registryRoot: "", log: (m) => lines.push(m) });
    expect(code).toBe(0);
    for (const f of ["package.json", "tsconfig.json", "agent.ts", ".env.example"]) {
      expect(existsSync(join(out, f))).toBe(true);
    }
    const pkg = JSON.parse(readFileSync(join(out, "package.json"), "utf8"));
    expect(pkg.dependencies).toHaveProperty("@agentkit/sdk");
  });

  it("refuses to overwrite an existing file without --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-conflict-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const lines: string[] = [];
    const code = await init(["--out", out], { registryRoot: "", log: (m) => lines.push(m), err: (m) => lines.push(m) });
    expect(code).toBe(1);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).toBe("// existing");
  });

  it("overwrites with --force", async () => {
    const out = mkdtempSync(join(tmpdir(), "kaji-init-force-"));
    writeFileSync(join(out, "agent.ts"), "// existing");
    const lines: string[] = [];
    const code = await init(["--out", out, "--force"], { registryRoot: "", log: (m) => lines.push(m) });
    expect(code).toBe(0);
    expect(readFileSync(join(out, "agent.ts"), "utf8")).not.toBe("// existing");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd kaji/ts && bun run test tests/cli/init.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the command**

Create `kaji/ts/src/cli/init.ts`:
```typescript
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { RunOptions } from "./index";

interface Args {
  out: string;
  force: boolean;
}

function parseArgs(rest: string[]): Args {
  let out = ".";
  let force = false;
  for (let i = 0; i < rest.length; i++) {
    if (rest[i] === "--out") {
      out = rest[++i] ?? ".";
    } else if (rest[i] === "--force") {
      force = true;
    }
  }
  return { out: resolve(out), force };
}

const FILES: Record<string, string> = {
  "package.json": JSON.stringify(
    {
      name: "my-kaji-agent",
      version: "0.1.0",
      private: true,
      type: "module",
      scripts: { start: "tsx agent.ts" },
      dependencies: { "@agentkit/sdk": "^0.1.0" },
      devDependencies: { tsx: "^4.0.0", typescript: "^5.4.0" },
    },
    null,
    2,
  ),
  "tsconfig.json": JSON.stringify(
    {
      compilerOptions: {
        target: "ES2022",
        module: "ESNext",
        moduleResolution: "Bundler",
        strict: true,
        esModuleInterop: true,
        skipLibCheck: true,
      },
      include: ["*.ts"],
    },
    null,
    2,
  ),
  "agent.ts": `import { AgentBuilder, getProvider } from "@agentkit/sdk";

const agent = new AgentBuilder()
  .provider(getProvider("openai"))
  .build();

const result = await agent.turn({ content: "Say hello." });
console.log(result.text);
`,
  ".env.example": "OPENAI_API_KEY=sk-...\n",
};

export async function init(rest: string[], opts: RunOptions): Promise<number> {
  const log = opts.log ?? ((m: string) => console.log(m));
  const err = opts.err ?? ((m: string) => console.error(m));
  const args = parseArgs(rest);
  if (!existsSync(args.out)) mkdirSync(args.out, { recursive: true });
  const conflicts: string[] = [];
  for (const name of Object.keys(FILES)) {
    if (existsSync(join(args.out, name)) && !args.force) conflicts.push(name);
  }
  if (conflicts.length > 0) {
    err(`refusing to overwrite without --force: ${conflicts.join(", ")}`);
    return 1;
  }
  for (const [name, body] of Object.entries(FILES)) {
    writeFileSync(join(args.out, name), body);
    log(`wrote ${join(args.out, name)}`);
  }
  return 0;
}
```

- [ ] **Step 4: Register the command in `kaji/ts/src/cli/index.ts`**

```typescript
import { init } from "./init";
// inside COMMANDS:
  init: {
    describe: "Scaffold a new TypeScript Kaji project.",
    usage: "kaji init [--out <dir>] [--force]",
    run: (rest, opts) => init(rest, opts),
  },
```

- [ ] **Step 5: Run the tests**

Run: `cd kaji/ts && bun run test tests/cli/`
Expected: PASS (dispatch + list-integrations + init).

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/cli/init.ts kaji/ts/src/cli/index.ts kaji/ts/tests/cli/init.test.ts
git commit -m "feat(ts): init cli command scaffolds a TypeScript agent project"
```

---

## Task 8: Wire approval events through the bus + project them in replay

**Files:**
- Modify: `kaji/ts/src/tools/planner.ts`
- Modify: `kaji/ts/src/sessions/replay.ts`
- Create: `kaji/ts/tests/tools/approval_flow.test.ts`

**Interfaces:**
- Consumes: existing `EventBus`, `ApprovalHandler`, `KajiEvent` schemas for `TOOL_APPROVAL_REQUESTED / APPROVED / REJECTED`.
- Produces:
  - `ToolPlanner` now publishes the three approval events around each handler call when the policy demands approval.
  - `SessionState` gains `pendingApprovals: Set<string>`, `approvedToolIds: Set<string>`, `rejectedToolIds: Set<string>` (keyed by tool-call id).

- [ ] **Step 1: Read the current planner + replay shape**

Run:
```
sed -n '1,200p' kaji/ts/src/tools/planner.ts
sed -n '1,150p' kaji/ts/src/sessions/replay.ts
grep -n "TOOL_APPROVAL" kaji/ts/src/events/schemas.ts kaji/ts/src/events/types.ts
```
Expected: identify (a) where `ApprovalHandler` is invoked in `planner.ts`, (b) the `SessionState` shape in `replay.ts`, (c) the existing event schemas. Adjust the steps below if names differ.

- [ ] **Step 2: Write the failing test**

Create `kaji/ts/tests/tools/approval_flow.test.ts`:
```typescript
import { describe, expect, it } from "vitest";
import { EventBus } from "../../src/events/bus";
import { EventType } from "../../src/events/types";
import { ToolPlanner } from "../../src/tools/planner";
import { ToolRegistry } from "../../src/tools/registry";
import { replaySession } from "../../src/sessions/replay";
import { InMemoryEventStore } from "../../src/events/store";

describe("approval flow", () => {
  it("emits TOOL_APPROVAL_REQUESTED then APPROVED, then runs the tool", async () => {
    const bus = new EventBus();
    const store = new InMemoryEventStore();
    bus.subscribe((e) => store.append("s1", e));

    const registry = new ToolRegistry();
    let ran = false;
    registry.register({
      name: "ship_it",
      description: "Risky action.",
      parameters: { type: "object", properties: {} },
      handler: async () => {
        ran = true;
        return { ok: true };
      },
      requiresApproval: true,
    });

    const planner = new ToolPlanner({
      registry,
      bus,
      sessionId: "s1",
      approvalHandler: async () => true,
    });

    await planner.plan([{ id: "c1", name: "ship_it", arguments: {} }]);

    const types = store.list("s1").map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REQUESTED);
    expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(ran).toBe(true);

    const state = replaySession(store.list("s1"));
    expect(state.approvedToolIds.has("c1")).toBe(true);
    expect(state.pendingApprovals.has("c1")).toBe(false);
  });

  it("emits TOOL_APPROVAL_REJECTED and skips execution when handler returns false", async () => {
    const bus = new EventBus();
    const store = new InMemoryEventStore();
    bus.subscribe((e) => store.append("s2", e));

    const registry = new ToolRegistry();
    let ran = false;
    registry.register({
      name: "ship_it",
      description: "Risky action.",
      parameters: { type: "object", properties: {} },
      handler: async () => {
        ran = true;
        return {};
      },
      requiresApproval: true,
    });

    const planner = new ToolPlanner({
      registry,
      bus,
      sessionId: "s2",
      approvalHandler: async () => false,
    });

    await planner.plan([{ id: "c2", name: "ship_it", arguments: {} }]);

    const types = store.list("s2").map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_REJECTED);
    expect(ran).toBe(false);

    const state = replaySession(store.list("s2"));
    expect(state.rejectedToolIds.has("c2")).toBe(true);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd kaji/ts && bun run test tests/tools/approval_flow.test.ts`
Expected: FAIL — either the events aren't emitted, or `SessionState` lacks the new sets.

- [ ] **Step 4: Update `kaji/ts/src/tools/planner.ts`**

In the place where the planner calls `approvalHandler` (referenced by the audit at `planner.ts:78`):

```typescript
// Before awaiting the handler:
this.bus.publish({
  type: EventType.TOOL_APPROVAL_REQUESTED,
  sessionId: this.sessionId,
  toolCallId: call.id,
  toolName: call.name,
  arguments: call.arguments,
  timestamp: new Date().toISOString(),
});

const approved = await this.approvalHandler({
  toolName: call.name,
  arguments: call.arguments,
});

this.bus.publish({
  type: approved
    ? EventType.TOOL_APPROVAL_APPROVED
    : EventType.TOOL_APPROVAL_REJECTED,
  sessionId: this.sessionId,
  toolCallId: call.id,
  toolName: call.name,
  timestamp: new Date().toISOString(),
});

if (!approved) {
  // emit a synthetic ToolResult event marked as rejected, then skip
  continue;
}
```

If `ToolPlanner` does not currently accept a `bus` or `sessionId` in its constructor, add them — and update existing call sites to pass them (likely `kaji/ts/src/runtime/builder.ts`).

- [ ] **Step 5: Update `kaji/ts/src/sessions/replay.ts`**

Extend `SessionState` and the reducer:

```typescript
export interface SessionState {
  // ... existing fields
  pendingApprovals: Set<string>;
  approvedToolIds: Set<string>;
  rejectedToolIds: Set<string>;
}

// In the initial state:
pendingApprovals: new Set<string>(),
approvedToolIds: new Set<string>(),
rejectedToolIds: new Set<string>(),

// In the switch over event.type:
case EventType.TOOL_APPROVAL_REQUESTED:
  state.pendingApprovals.add(event.toolCallId);
  break;
case EventType.TOOL_APPROVAL_APPROVED:
  state.pendingApprovals.delete(event.toolCallId);
  state.approvedToolIds.add(event.toolCallId);
  break;
case EventType.TOOL_APPROVAL_REJECTED:
  state.pendingApprovals.delete(event.toolCallId);
  state.rejectedToolIds.add(event.toolCallId);
  break;
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd kaji/ts && bun run test tests/tools/approval_flow.test.ts`
Expected: 2 PASS.

- [ ] **Step 7: Run the full TS suite**

Run: `cd kaji/ts && bun run test`
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add kaji/ts/src/tools/planner.ts kaji/ts/src/sessions/replay.ts kaji/ts/tests/tools/approval_flow.test.ts
git commit -m "feat(ts): emit approval events through bus + project them in replay"
```

---

## Task 9: Default `cliApprovalHandler` for dev use

**Files:**
- Create: `kaji/ts/src/tools/cli_approval_handler.ts`
- Create: `kaji/ts/tests/tools/cli_approval_handler.test.ts`
- Modify: `kaji/ts/src/index.ts` (export the new handler)

**Interfaces:**
- Consumes: `ApprovalHandler` type from `planner.ts`.
- Produces: `cliApprovalHandler(opts?: { input?: NodeJS.ReadableStream; output?: NodeJS.WritableStream }): ApprovalHandler`.

- [ ] **Step 1: Write the failing test**

Create `kaji/ts/tests/tools/cli_approval_handler.test.ts`:
```typescript
import { Readable, Writable } from "node:stream";
import { describe, expect, it } from "vitest";
import { cliApprovalHandler } from "../../src/tools/cli_approval_handler";

function streamFromString(s: string): NodeJS.ReadableStream {
  return Readable.from([s]);
}

function captureWritable(): { stream: NodeJS.WritableStream; chunks: string[] } {
  const chunks: string[] = [];
  const stream = new Writable({
    write(chunk, _enc, cb) {
      chunks.push(chunk.toString());
      cb();
    },
  });
  return { stream, chunks };
}

describe("cliApprovalHandler", () => {
  it("returns true for 'y'", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("y\n"), output: out.stream });
    const result = await handler({ toolName: "ship_it", arguments: { force: true } });
    expect(result).toBe(true);
    expect(out.chunks.join("")).toMatch(/ship_it/);
  });

  it("returns false for 'n'", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("n\n"), output: out.stream });
    const result = await handler({ toolName: "ship_it", arguments: {} });
    expect(result).toBe(false);
  });

  it("returns false for any other input", async () => {
    const out = captureWritable();
    const handler = cliApprovalHandler({ input: streamFromString("maybe\n"), output: out.stream });
    const result = await handler({ toolName: "ship_it", arguments: {} });
    expect(result).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd kaji/ts && bun run test tests/tools/cli_approval_handler.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the handler**

Create `kaji/ts/src/tools/cli_approval_handler.ts`:
```typescript
import { createInterface } from "node:readline";
import type { ApprovalHandler } from "./planner";

export interface CliApprovalOptions {
  input?: NodeJS.ReadableStream;
  output?: NodeJS.WritableStream;
}

export function cliApprovalHandler(opts: CliApprovalOptions = {}): ApprovalHandler {
  return async ({ toolName, arguments: args }) => {
    const input = opts.input ?? process.stdin;
    const output = opts.output ?? process.stdout;
    const rl = createInterface({ input, output });
    try {
      output.write(`\nApproval requested: ${toolName}\n`);
      output.write(`  arguments: ${JSON.stringify(args)}\n`);
      const answer = await new Promise<string>((resolve) => {
        rl.question("  approve? [y/N]: ", (a) => resolve(a));
      });
      return answer.trim().toLowerCase() === "y";
    } finally {
      rl.close();
    }
  };
}
```

- [ ] **Step 4: Export from `kaji/ts/src/index.ts`**

Add:
```typescript
export { cliApprovalHandler, type CliApprovalOptions } from "./tools/cli_approval_handler";
```

- [ ] **Step 5: Run the tests**

Run: `cd kaji/ts && bun run test tests/tools/cli_approval_handler.test.ts && bun run test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add kaji/ts/src/tools/cli_approval_handler.ts kaji/ts/src/index.ts kaji/ts/tests/tools/cli_approval_handler.test.ts
git commit -m "feat(ts): default cli approval handler for dev/repl use"
```

---

## Task 10: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/sdk-audit-fixes
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "sdk audit fixes: export hidden types, live tests, ts cli + approval flow" --body "$(cat <<'EOF'
## Summary
- Export Python knowledge / SessionStore / HistoryStore / ToolRetriever / payload translators from `kaji.__init__` lazy map. Roadmap claimed DONE; was MISSING.
- Add opt-in live integration tests for Gemini and Kimi providers (gated on `KAJI_LIVE_*=1` + api key).
- TypeScript CLI: dispatch table, working `--help`, plus `list-integrations` and `init` commands for rough Python-CLI parity.
- TypeScript approval flow: planner emits `TOOL_APPROVAL_REQUESTED/APPROVED/REJECTED` through the bus, `replaySession` projects them, default `cliApprovalHandler` for dev/REPL.

Closes the four highest-leverage gaps surfaced by the 2026-06-25 SDK audit.

## Test plan
- [ ] `cd kaji/sdk && poetry run pytest -x -q` passes (Python unit + new public-API test).
- [ ] `cd kaji/sdk && poetry run pytest tests/integration/ -v` shows new Gemini and Kimi tests SKIPPED without env vars.
- [ ] `cd kaji/ts && bun run test` passes (dispatch, list-integrations, init, approval flow, cli handler).
- [ ] `cd kaji/ts && bun run build && node kaji/ts/dist/cli/index.js --help` lists `add`, `list-integrations`, `init`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Self-Review Notes

- **Spec coverage:** all four issues in the user request are covered. Python exports → Tasks 1-2. Live Gemini/Kimi tests → Tasks 3-4. TS CLI parity → Tasks 5-7. Approval flow + UI clarification → Tasks 8-9. STT/TTS modalities for TS explicitly skipped per user instruction.
- **Placeholder scan:** every code step has runnable code. Two known unknowns are flagged inline (Task 4 Step 1 confirms the Kimi env var name; Task 8 Step 1 confirms current planner/replay shape) and are framed as targeted reads, not "TODO."
- **Type consistency:** `RunOptions` defined in Task 5 and consumed unchanged in Tasks 6-7. `pendingApprovals`/`approvedToolIds`/`rejectedToolIds` defined in Task 8 and asserted in Task 8's test (no later task references them, so no drift risk).
- **Out of scope (deliberate):** native TS Gemini/Kimi providers, `gen`/`info`/`doctor` TS commands, web/Slack approval UIs, STT/TTS modalities, ryo work.
