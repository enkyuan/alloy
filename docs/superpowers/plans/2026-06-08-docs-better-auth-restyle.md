# apps/docs better-auth Restyle + Content Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing `apps/docs` Fumadocs site to the better-auth docs look (fumadocs-ui `black` theme + Geist fonts) and polish all 9 content pages to Title Case headings, sentence-case prose, and rich frontmatter descriptions.

**Architecture:** In-place changes to the existing Next.js + Fumadocs app. Two isolated workstreams: styling (`global.css` + `layout.tsx` + `package.json`) and content (9 MDX files under `content/docs/`). No framework change, no new components, no marketing pages.

**Tech Stack:** Next.js 16, fumadocs-ui 16.9 (`black.css` theme preset), `geist` font package (1.7.2), Bun 1.3, Turbo.

## Testing note (read first)

This is a styling + content change with no application logic. The "tests" are build / typecheck / lint / render gates, not unit tests:
- `next build` passing = CSS imports resolve, fonts wire up, all MDX compiles.
- `/browse` dogfood = the black theme + Geist render and look like better-auth.

Do not write hollow unit tests. After each change, run the relevant gate and commit on green.

## Package-manager rule (read second)

USE BUN for everything. `bun add geist`, `bun install`, `bun --filter @kaji/docs <script>`. Never npm/yarn/pnpm. `bun.lock` is gitignored in this repo by design (do not force-add it).

## Verified facts (no need to re-discover)

- Current `apps/docs/app/global.css` lines 1-3:
  ```
  @import 'tailwindcss';
  @import 'fumadocs-ui/css/neutral.css';
  @import 'fumadocs-ui/css/preset.css';
  ```
  (followed by `html { scrollbar-gutter: stable; }` and a body-scroll-lock rule — keep those).
- `fumadocs-ui/css/black.css` EXISTS in the installed fumadocs-ui (verified). The swap is valid.
- Current `apps/docs/app/layout.tsx` uses `Inter` from `next/font/google`, applied as `className={inter.className}` on `<html>`. Full current content is shown in Task 2.
- `geist` 1.7.2, peerDep `next >=13.2.0` — Next 16 compatible. Exports `geist/font/sans` and `geist/font/mono`, each a font object with `.variable` (a CSS-var class like `__variable_xxx` that sets `--font-geist-sans`) and `.className`.
- Content uses ZERO custom MDX components. Only markdown, tables, fenced code.
- Branch: work on `feat/docs` (already created, spec already committed there).

## File Structure

Modified:
- `apps/docs/package.json` — add `geist` dep (Task 1)
- `apps/docs/app/global.css` — theme preset swap + font-var wiring (Task 3)
- `apps/docs/app/layout.tsx` — Geist fonts replace Inter (Task 3)
- `apps/docs/content/docs/index.mdx` (Task 4)
- `apps/docs/content/docs/getting-started.mdx` (Task 5)
- `apps/docs/content/docs/architecture.mdx` (Task 5)
- `apps/docs/content/docs/reference-service.mdx` (Task 5)
- `apps/docs/content/docs/concepts/{events,session-state,tool-registry,event-bus,providers}.mdx` (Task 6)

Untouched: `meta.json` files (nav order/titles stay), `source.config.ts`, app routes, `lib/`.

---

### Task 1: Add the geist font package

**Files:**
- Modify: `apps/docs/package.json` (via bun)

- [ ] **Step 1: Add geist with bun**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun add geist --filter @kaji/docs
```
If `--filter` with `bun add` is not supported by this bun version, instead run from the workspace dir:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy/apps/docs && bun add geist
```
Expected: `geist@1.7.2` (or newer 1.x) added to `apps/docs/package.json` dependencies. Do NOT use npm.

- [ ] **Step 2: Verify it installed and resolves**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && grep geist apps/docs/package.json
ls apps/docs/node_modules/geist/font/ 2>/dev/null || ls node_modules/geist/font/ 2>/dev/null
```
Expected: `"geist"` appears in dependencies; the `geist/font/` dir contains `sans` and `mono` entries.

- [ ] **Step 3: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/package.json
git commit -m "build(docs): add geist font package

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(Note: `bun.lock` is gitignored; only package.json is staged.)

---

### Task 2: Baseline build (confirm green before changing anything)

**Files:** none (verification only)

- [ ] **Step 1: Build the app as-is**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build
```
Expected: `Exited with code 0`. This is the baseline; if it fails BEFORE any change, stop and report — something is wrong with the environment, not the restyle.

---

### Task 3: Apply the better-auth styling (black theme + Geist fonts)

**Files:**
- Modify: `apps/docs/app/global.css`
- Modify: `apps/docs/app/layout.tsx`

- [ ] **Step 1: Swap the theme preset in global.css**

Edit `apps/docs/app/global.css`. Change the second import line ONLY:
- from: `@import 'fumadocs-ui/css/neutral.css';`
- to:   `@import 'fumadocs-ui/css/black.css';`

Leave `@import 'tailwindcss';`, `@import 'fumadocs-ui/css/preset.css';`, and the existing `html { scrollbar-gutter: stable; }` / body-scroll-lock rules exactly as they are.

- [ ] **Step 2: Replace Inter with Geist in layout.tsx**

Replace the entire contents of `apps/docs/app/layout.tsx` with:

```tsx
import type { Metadata } from "next";
import { RootProvider } from "fumadocs-ui/provider/next";
import "./global.css";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { appName } from "@/lib/shared";

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: {
    template: `%s | ${appName}`,
    default: appName,
  },
  description:
    "Embeddable SDK for building agents: event-sourced runtime, tool registry, pluggable LLM providers, and STT/TTS modalities.",
};

export default function Layout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="flex flex-col min-h-screen font-sans">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
```

Note: `GeistSans.variable` sets `--font-geist-sans`; `GeistMono.variable` sets `--font-geist-mono`. The next step maps those to the `--font-sans` / `--font-mono` names fumadocs-ui and Tailwind expect.

- [ ] **Step 3: Wire the Geist CSS variables to --font-sans / --font-mono**

Edit `apps/docs/app/global.css`. After the existing `@import` lines (and before or after the existing `html` rule, placement does not matter), add:

```css
:root {
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;
}
```

This makes both Tailwind's `font-sans` utility (used on `<body>`) and fumadocs-ui's typography pick up Geist.

- [ ] **Step 4: Build gate**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build
```
Expected: `Exited with code 0`.

**FALLBACK if the build fails on `geist/font/sans` or `geist/font/mono`** (import or types error under Next 16): replace the two geist imports in layout.tsx with the `next/font/google` equivalent, which provides the same fonts:
```tsx
import { Geist, Geist_Mono } from "next/font/google";
const geistSans = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
```
and use `className={`${geistSans.variable} ${geistMono.variable}`}`. The global.css `:root` block stays the same. Rebuild and confirm exit 0. Note in the report which path was used.

- [ ] **Step 5: Typecheck gate**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs typecheck
```
Expected: no type errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/app/global.css apps/docs/app/layout.tsx
git commit -m "style(docs): adopt better-auth look (black theme + Geist fonts)

Swap fumadocs-ui theme preset neutral -> black and replace Inter with
Geist Sans/Mono, matching the better-auth docs site.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Rewrite index.mdx (Title Case + sentence case + rich description)

**Files:**
- Modify: `apps/docs/content/docs/index.mdx`

Casing rules: Title Case the `title:` and headings; sentence-case the prose; rich `description:`. PRESERVE verbatim: `kaji`, `kaji-serve`, `@kaji/sdk`, code identifiers, env vars, anything in code/tables. No em-dashes.

- [ ] **Step 1: Replace the file with the polished version**

Write `apps/docs/content/docs/index.mdx`:

```mdx
---
title: kaji
description: kaji is an embeddable, infra-free SDK for building agents in Python and TypeScript, with an event-sourced runtime, a tool registry, pluggable LLM providers, and STT/TTS voice modalities.
---

kaji is an embeddable SDK for building agents: an event-sourced runtime, a
tool registry, pluggable LLM providers, and STT/TTS modalities. The core is
infra-free. No database or server is required to import and use it. Deploy it
yourself, or run the reference service (`kaji-serve`) when you need a
production-grade multi-process setup.

It powers ryo's agent runtime, and can also be used standalone in any
Python or TypeScript project.

## Packages

| package | path | what it is |
| ---------------- | ---------------- | --------------------------------------------- |
| `kaji` | `kaji/sdk` | Python SDK: the core runtime, embed anywhere |
| `kaji-serve` | `kaji/serve` | Python: FastAPI + workers reference service |
| `@kaji/sdk` | `kaji/ts` | TypeScript port of the core runtime |

The concepts in these docs are stated language-neutrally. Code samples show
Python and TypeScript where both exist. The wire format (event type strings,
field names) is identical across the Python SDK and the TypeScript port, so
events round-trip across both.

## When to Embed vs. Run the Service

Embed `kaji` directly for infra-free usage inside your own app. Run
`kaji-serve` when you need multi-process durability and real-time voice.
See [the reference service](/docs/reference-service).
```

- [ ] **Step 2: Build gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build`
Expected: `Exited with code 0`.

- [ ] **Step 3: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/content/docs/index.mdx
git commit -m "docs(content): Title Case + rich description for index

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Rewrite the three top-level pages

**Files:**
- Modify: `apps/docs/content/docs/getting-started.mdx`
- Modify: `apps/docs/content/docs/architecture.mdx`
- Modify: `apps/docs/content/docs/reference-service.mdx`

Same casing rules as Task 4.

- [ ] **Step 1: getting-started.mdx**

Write `apps/docs/content/docs/getting-started.mdx`:

````mdx
---
title: Getting Started
description: Install the kaji SDK in Python or TypeScript and register your first tool, with the tool spec, handler signature, and ToolContext explained.
---

## Installation

```bash
# TypeScript (from the monorepo JS workspace)
bun install
# the package is @kaji/sdk

# Python
cd kaji/sdk && poetry install
```

## Register a Tool

Tools are a spec (name, description, JSON-schema parameters) plus a handler.
The runtime sends the full tool-spec list to the model. When the model requests
a call, the registry dispatches the handler. Multiple calls from one model turn
run concurrently, and results are collected before the next loop iteration.

```python
# Python
@kaji.register_tool(
    kaji.tool_spec_from_model("get_weather", "Look up weather", GetWeather)
)
async def get_weather(ctx: kaji.ToolContext, args: dict) -> dict:
    return {"tempF": 68}
```

```ts
// TypeScript
registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ tempF: 68 }),
);
```

`ToolContext` carries `userId` / `user_id` and an optional `db` handle (null by
default. Inject one when the tool needs persistence).

## Next

Read [core concepts](/docs/concepts/events) to understand events, session
state, the tool registry, the event bus, and providers.
````

- [ ] **Step 2: architecture.mdx**

Write `apps/docs/content/docs/architecture.mdx`:

````mdx
---
title: Architecture
description: How the modality-agnostic ReAct runtime loop projects session state, calls the LLM provider, and runs tool calls, and where STT/TTS attach at the voice edges.
---

## The Runtime Loop

```
   ┌────────────────────────────────────────────────────┐
   │  your app  (or ryo/api)                       │
   │  session manager   tool registry   model provider  │
   └────────────────────────┬───────────────────────────┘
                            ▼
   ┌───────────────────────────────────────────────────┐
   │  agent runtime  (ReAct loop)                      │
   │  1. project session state from event log          │
   │  2. call LLM provider with history + tool specs   │
   │  3. execute tool calls scatter-gather             │
   │  4. loop until model response is final            │
   └────────┬────────────────────────────┬─────────────┘
            │ events                     │ tool calls
            ▼                            ▼
   ┌──────────────────┐        ┌──────────────────────┐
   │  event store     │        │  tool handlers       │
   │  (in-memory or   │        │  (your functions,    │
   │   persistent)    │        │   run concurrently)  │
   └──────────────────┘        └──────────────────────┘
```

## Modalities Attach at the Edges

The reasoning loop is modality-agnostic. Voice adds STT at the input edge and
TTS at the output edge. Text skips both.

```
   voice:   audio → STT → [runtime loop] → TTS → audio
   text:    text  →       [runtime loop] →       text
```
````

- [ ] **Step 3: reference-service.mdx**

Write `apps/docs/content/docs/reference-service.mdx`:

```mdx
---
title: Reference Service
description: kaji-serve wraps the SDK as three Redis-backed processes (api, bus-worker, worker) for multi-process durability and real-time voice, and when to use it instead of embedding the SDK directly.
---

`kaji-serve` (`kaji/serve`) wraps the SDK as three processes over Redis
so heavy tool execution never stalls a real-time exchange.

| process | role |
| ------------ | --------------------------------------------------------- |
| `api` | FastAPI app: REST routes and STT WebSocket |
| `bus-worker` | reasoning loop: LLM calls, event bus, tool dispatch |
| `worker` | async tool execution (TaskIQ), results back to bus-worker |

Redis Streams provide durable at-least-once hand-off between processes. Redis
Pub/Sub fans out agent responses to the connected client in real time.

Use `kaji-serve` when you need multi-process durability and real-time
voice. Embed `kaji` directly when you want infra-free usage inside your own
app.
```

- [ ] **Step 4: Build gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build`
Expected: `Exited with code 0`.

- [ ] **Step 5: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/content/docs/getting-started.mdx apps/docs/content/docs/architecture.mdx apps/docs/content/docs/reference-service.mdx
git commit -m "docs(content): Title Case + rich descriptions for top-level pages

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Rewrite the five concept pages

**Files:**
- Modify: `apps/docs/content/docs/concepts/events.mdx`
- Modify: `apps/docs/content/docs/concepts/session-state.mdx`
- Modify: `apps/docs/content/docs/concepts/tool-registry.mdx`
- Modify: `apps/docs/content/docs/concepts/event-bus.mdx`
- Modify: `apps/docs/content/docs/concepts/providers.mdx`

Same casing rules. Note: the meta.json titles ("Events", "Session state", etc.) drive the sidebar; do NOT edit meta.json here, but the page `title:` frontmatter should be Title Case (e.g. "Session State").

- [ ] **Step 1: events.mdx**

```mdx
---
title: Events
description: All kaji session state derives from an append-only event log of typed events, with wire-format type strings that are identical across the Python and TypeScript SDKs.
---

All session state is derived from an append-only event log. Events are
discriminated by `type` (e.g. `user.message`, `tool.call.completed`,
`agent.message.completed`). The full list lives in the SDK source:

- `kaji/sdk/kaji/infra/events/schemas.py` (Python)
- `kaji/ts/src/events/schemas.ts` (TypeScript)

The event-type string values are the wire format and are identical across both
SDKs, so an event log written by one can be replayed by the other.
```

- [ ] **Step 2: session-state.mdx**

```mdx
---
title: Session State
description: How replaySession deterministically projects an event log into a SessionState (isActive and the message history) that gets passed to the LLM.
---

`replaySession` (Python: `ReplaySession`) takes the event log for a session and
projects it into a `SessionState`: `isActive` (Python: `is_active`), and
`messages`, the conversation history in `{ role, content }` form that gets
passed to the LLM.

Because state is a pure projection of the log, replay is deterministic: the same
events always yield the same `SessionState`.
```

- [ ] **Step 3: tool-registry.mdx**

````mdx
---
title: Tool Registry
description: Register a tool as a spec plus a handler in Python or TypeScript; the runtime dispatches model-requested calls and runs multiple calls from one turn concurrently.
---

Tools are registered with a spec (name, description, JSON-schema parameters) and
a handler function. The runtime calls the LLM with the full tool-spec list. When
the model requests a tool call, the registry dispatches it. Multiple tool calls
from one LLM turn run concurrently (scatter-gather) and results are collected
before the next loop iteration.

```python
# Python
@kaji.register_tool(
    kaji.tool_spec_from_model("get_weather", "Look up weather", GetWeather)
)
async def get_weather(ctx: kaji.ToolContext, args: dict) -> dict:
    return {"tempF": 68}
```

```ts
// TypeScript
registerTool(
  toolSpecFromSchema("get_weather", "Look up weather", z.object({ city: z.string() })),
  async (ctx, args) => ({ tempF: 68 }),
);
```

`ToolContext` carries `userId` / `user_id` and an optional `db` handle (null by
default. Inject one when the tool needs persistence).
````

- [ ] **Step 4: event-bus.mdx**

```mdx
---
title: Event Bus
description: The event bus fans events out to per-session subscribers, with an in-memory default in both SDKs and a Redis Stream-backed bus in kaji-serve for cross-process durability.
---

The event bus fans out events to subscribers per session. In the Python SDK the
default implementation is in-memory (`InMemoryEventBus`). A Redis Stream-backed
bus is used in `kaji-serve` for cross-process durability. The TypeScript SDK
ships an in-memory bus, which is sufficient for an embedded SDK.
```

- [ ] **Step 5: providers.mdx**

```mdx
---
title: Providers
description: LLM, TTS, and STT providers implement common interfaces selected by configuration; the Python SDK ships kimi, gemini, openai, and mock, with the TypeScript port mirroring the same neutral format.
---

LLM providers implement a common interface. The Python SDK ships `kimi`
(OpenRouter/Kimi, the default), `gemini`, `openai`, and `mock` (for tests),
selected via `KAJI_MODEL_PROVIDER`. Adding a provider means implementing the
`ModelProvider` protocol and registering it.

TTS providers (`gemini`, `openai`, `none`) follow the same pattern via the
`TTSProvider` protocol. STT uses Soniox by default.

The TypeScript port mirrors the same neutral message and tool-spec format, so a
provider translates to its own API only at its own boundary. The runtime never
imports provider-specific types.
```

- [ ] **Step 6: Build gate**

Run: `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs build`
Expected: `Exited with code 0`.

- [ ] **Step 7: Commit**

```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
git add apps/docs/content/docs/concepts/
git commit -m "docs(content): Title Case + rich descriptions for concept pages

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Full verification + browse dogfood

**Files:** none (verification only)

- [ ] **Step 1: Full Turbo gate sweep**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
bun --filter @kaji/docs format
bunx turbo run build typecheck lint format:check --filter=@kaji/docs
```
Expected: all tasks successful. lint 0 warnings/0 errors. (`format` writes; `format:check` then passes.)

- [ ] **Step 2: Clean-clone build**

Run:
```bash
cd /Users/Enkang.Yuan1/Desktop/Projects/alloy
D=$(mktemp -d /tmp/alloy-clean.XXXXXX)
git archive HEAD apps/docs | tar -x -C "$D"
cd "$D/apps/docs" && bun install && bun run build
echo "CLEAN BUILD EXIT: $?"
```
Expected: exit 0, "Compiled successfully". (Proves no styling/content file was left untracked.)

- [ ] **Step 3: Start dev server**

Run (background): `cd /Users/Enkang.Yuan1/Desktop/Projects/alloy && bun --filter @kaji/docs dev`
Note the actual port from output (3000, or next free port).

- [ ] **Step 4: Dogfood with the gstack /browse skill**

Per `CLAUDE.md`, use the `/browse` skill (never the chrome MCP tools directly). Against the running dev URL:
- Load `/docs`, screenshot it, and Read the screenshot. Confirm: black/high-contrast theme is active (not the old neutral light gray), Geist font is rendering (geometric sans, distinct from Inter).
- Confirm headings now read in Title Case ("Getting Started", "Tool Registry", "When to Embed vs. Run the Service").
- Confirm the sidebar nav still lists the pages and the Concepts group expands.
- Open `/docs/concepts/tool-registry`, confirm the Python + TS code blocks still render with syntax highlighting under the new theme.
- Check `console --errors` for JS errors.
- Optionally load the live better-auth docs (`https://www.better-auth.com/docs`) and compare the theme/typography side by side.
- Fix any render issue found, re-run the build gate, reload.

- [ ] **Step 5: Stop dev server.**

- [ ] **Step 6: Report**

Summarize: gate results (actual output), clean-build exit code, what the dogfood confirmed (with the screenshot), the dev URL, and any fixes made. Do NOT run /ship or open a PR unless the user asks.

---

## Self-review

**Spec coverage:**
- Styling: black theme (Task 3 step 1) ✓; Geist fonts via geist package + bun (Tasks 1, 3) ✓; font-var wiring (Task 3 step 3) ✓.
- Content: Title Case + sentence case + rich descriptions across all 9 pages (Tasks 4, 5, 6) ✓; preserve kaji/identifiers/env vars (casing rules repeated per task, and the rewritten text keeps them verbatim) ✓; gemini entry kept (Task 6 step 5) ✓; no em-dashes (checked in drafted text) ✓; meta.json untouched ✓.
- Non-goals respected: no framework change, no marketing/blog, no Typesense, no custom MDX components, no landing animations, no restructure. Nothing in the plan adds them ✓.
- bun-only (Task 1 + package rule) ✓. Branch feat/docs (already on it) ✓. Separate styling/content commits ✓.
- Verification: build/typecheck/lint/format + clean-clone + /browse dogfood (Task 7) ✓.
- geist fallback to next/font/google documented (Task 3 step 4 FALLBACK) ✓.

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every content file is given in full. ✓

**Type/name consistency:** Font import names consistent: `GeistSans`/`GeistMono` from `geist/font/sans`|`geist/font/mono`, `.variable` used in layout, mapped to `--font-sans`/`--font-mono` in global.css `:root`. Theme import path `fumadocs-ui/css/black.css` consistent. Content page titles match their existing meta.json slugs (files unchanged; only frontmatter title cased). ✓

No gaps found.
