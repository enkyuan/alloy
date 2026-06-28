# Kaji TS Product v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `@kaji/sdk` as its own TypeScript product. Best-in-class agent SDK for TypeScript engineers building tool-using agents that touch real systems.

## The Paradigm (one sentence)

> **kaji is the TypeScript agent SDK where every tool your agent calls lives as TypeScript in your repo.**

That's the product. Everything else — providers, replay, codegen, MCP — is implementation detail in service of that sentence.

**Honest scope of "every tool":** the *tool definition* (`functionTool` + Zod schema + `execute` body) lives in the user's repo, always. The SDK itself (`@kaji/sdk`), the replay viewer's HTML bundle, the telemetry client, and the MCP transport layer are library code the user imports — they don't live in `src/integrations/`. The paradigm is about **tools**, not about every byte of code touching the agent. The wedge in one sentence:

> kaji is the only TS agent SDK where the tool a model calls and the tool you reviewed in your last PR are the same file.

## Why this paradigm

The June 2026 market split: eve (Vercel) made integrations runtime pointers to MCP/OpenAPI URLs; flue (Astro team) made integrations a single sandboxed code-execution tool. Both bet on **less code in the user's repo**. kaji bets the opposite: **all code in the user's repo, no runtime indirection, no sandbox**.

Why the contrarian bet wins for our target user (TS engineers shipping tool-using agents to production):

1. **Code in the repo is reviewable.** A PR adds a tool, the tool is the diff, the team reviews the diff. eve hides the tool behind a pointer; flue hides it behind a sandbox.
2. **Code in the repo is debuggable.** A tool fails, the dev opens the file, sets a breakpoint, runs the test. With runtime pointers or sandboxes, debugging crosses a process boundary.
3. **Code in the repo is type-safe at compile time.** TypeScript catches schema drift the moment Linear's SDK ships v5. Runtime pointers and code-execution tools only fail at agent runtime.
4. **Code in the repo composes with what's already there.** The dev's existing `src/` patterns (logging, error handling, env-config) apply unchanged to integrations. No new mental model for "where my integrations live."
5. **One paradigm, one mental model.** No `connect` vs `add` vs `override` vs `eject`. Just: integrations are files in your repo.

This is the same bet shadcn made for UI components, applied to tool definitions. The bet has a known failure mode (people might not actually want to edit the source) and is instrumented from day 1.

**Positioning (one sentence, lands in docs above the fold):**

> kaji is the TypeScript agent SDK where every tool your agent calls lives as TypeScript in your repo. Add built-in integrations with `kaji add linear`, or generate one from any OpenAPI spec with `kaji new tool <url>`. Either way, the tool code is yours to read, edit, test, and own.

**What kaji is NOT** (in docs landing copy):
- Not a chat UI framework (use Vercel AI SDK)
- Not a workflow orchestrator (use Temporal / Inngest)
- Not an LLM provider router (use OpenRouter)
- Not a hosted observability product (use LangSmith / Braintrust for SaaS)
- Not a runtime-pointer SDK (use eve)
- Not a sandboxed code-execution framework (use flue)

**Target user:** TS engineers at product companies (e.g., engineers at Ramp building procurement agents) who need agents that take action, not chat UIs, not RAG-over-docs.

**The named bet:** TS engineers want *built-in* tool code in their repo the way they want UI component code in their repo. The shadcn analogy holds for tool wrappers, not just visual components. Sub-Plan 0.5's telemetry measures the answer from day 1: ratio of `integration.added` to `integration.edited.outside_signature_lines` (with formatting-only edits and SDK-version-bump type-fixes filtered out).

**Decision framework (not a hard threshold):**
- **Strong yes (>40% semantic-edit rate):** Lean in. Add Sub-Plan v1.1: org-shared integration templates (`kaji add linear --from-template <org-url>`), patch/overlay model so 5,000 vendored Linear integrations across a company don't drift.
- **Ambiguous (15-40%):** Ship both modes in v1.1. Vendored stays default for users who want it; add `bun add @kaji/integrations/linear` as the importable mode. Repositioning shifts to "vendored when you want it, importable when you don't" — slightly weaker wedge, broader appeal.
- **Weak (<15%):** Honest pivot: the wedge for *built-ins* is dead. Move built-ins to npm packages. **The wedge for generated tools (Sub-Plan 3) survives** because generated code from an unreliable spec has to be vendored — there's no other way. Positioning shifts to "the SDK with the best OpenAPI/MCP codegen" + replay. Recovery: ~2 weeks rebuilding the built-in distribution path; the rest of the product stands.

15% is a heuristic, not a sacred number. Real signal will come from user interviews alongside the data. Don't pivot on numbers alone; pivot when the qualitative + quantitative both say so.

**Upside if the bet wins:** a defensible wedge no other TS agent SDK can copy without burning their existing userbase (their users `import` and would revolt at vendoring).

## Architecture (paradigm consequences)

Two ways to create a tool, **same end state**: TypeScript files in `src/integrations/<name>/`.

```
            ┌─────────────────────────────────────────────────────┐
            │   src/integrations/<name>/                          │
            │     ├── index.ts        (functionTool definitions)  │
            │     ├── manifest.json   (auth, peer deps, version)  │
            │     └── *.test.ts       (your tests, your edits)    │
            └─────────────────────────────────────────────────────┘
                          ▲                        ▲
                          │                        │
              ┌───────────┴────────────┐    ┌──────┴─────────────────┐
              │ kaji add <name>        │    │ kaji new tool <url>    │
              │  (built-in, curated)   │    │  (generated from spec) │
              └────────────────────────┘    └────────────────────────┘
                          │                        │
                          ▼                        ▼
              We hand-author and             Our codegen parses
              maintain a registry            OpenAPI/GraphQL specs
              of common integrations         and emits TypeScript
              (Linear, Postgres, Slack,
              GitHub, Resend, etc.)
```

**The agent never knows the difference.** A hand-written Linear integration and a generated internal-API integration produce identical `functionTool` shapes. The runtime calls them the same way. The replay log shows them the same way. The planner schedules them the same way.

**Distribution = filesystem.** No npm package per integration. No runtime indirection (for the tool *definition*; tool *execution* still calls APIs). The tool source is in the user's repo from the moment `kaji add` or `kaji new tool` completes.

**Opinionated agent layout (new in this revision, addresses eve comparison gap):** kaji ships a recommended directory convention for the agent itself, not just for integrations. `bun create kaji-agent` (Sub-Plan 7) scaffolds:

```
your-app/
├── agent.ts                       # AgentRuntime construction
├── src/
│   ├── integrations/              # tools (vendored, owned by you)
│   │   ├── linear/
│   │   ├── postgres/
│   │   └── your-internal-api/     # generated from your OpenAPI
│   ├── prompts/                   # system prompts, few-shot examples
│   └── evals/                     # golden traces for `kaji eval`
├── .env                           # API keys
└── package.json
```

Convention, not enforcement — users can put files anywhere. But this is the layout the templates use, the docs use, and `kaji eval` defaults to (`--batch ./src/evals/`).

**MCP role inverts.** kaji does NOT consume MCP servers as a tool source (that's eve's model). kaji's `kaji/ts/src/mcp/server.ts` lets users **expose their kaji tools as an MCP server** so other clients (Claude Desktop, Cursor, Zed) can consume them. MCP becomes an output format, not an input format. Users who want to consume external MCP servers wrap them with `kaji new tool` style codegen against the MCP server's tool list — landing source code in their repo, paradigm preserved.

**Tech Stack:** TypeScript 5+, Bun (package manager), Node ≥22, Vitest, Zod 4, tsup; Fumadocs + Next.js 15 for the docs site; integrations use the best TS SDK available per vendor (`@linear/sdk`, `postgres`, `@slack/web-api`, `@notionhq/client`, `resend`, `@octokit/rest`, `better-sqlite3`); replay viewer = single-file HTML + vanilla TS.

## Global Constraints

- **Branch discipline:** All work on named branches (`feat/*`, `fix/*`, `refactor/*`). Never commit directly to main. Squash-merge PRs with `gh pr merge --squash --delete-branch`.
- **Package manager:** TS work uses `bun` exclusively. Never `npm`, `yarn`, `pnpm`. Python work (Sub-Plan 9 only) uses `uv`.
- **No back-compat shims:** Pre-1.0. Rename/remove cleanly. No aliases, deprecation warnings, or legacy keepers unless explicitly requested.
- **No em-dashes in prose/docs.** Terse technical sentences.
- **Verify branch content before push:** `git diff --stat main...HEAD` before opening a PR.
- **Independent versioning:** `@kaji/sdk` (TS) and `kaji` (Python) ship on their own cadences. CHANGELOGs are independent.
- **No source-level schema lockstep with Python.** The wire format (REST/SSE/WS between a TS client and Python serve) is the only contract that must align. In-memory event shapes can diverge per language.
- **TS-native integration shapes.** Integrations are written in idiomatic TypeScript using the best TS SDK available, not ported one-for-one from Python.
- **Type safety:** No `any` casts in critical paths (runtime, tools, sessions, providers, integrations). Error narrowing may use `unknown` + structural checks.
- **Test discipline:** TDD per sub-plan. Failing test before implementation. Vitest. Integration tests with live API access skip without keys.
- **Runtime targets (v1):** Node ≥22, Bun. Edge runtimes tested, not committed.
- **License:** SDK stays MIT/Apache. Integration code that wraps a third-party SDK inherits that SDK's license — documented in `manifest.json` per integration.

## Tool Definition Shape (the first-5-minute promise)

```ts
import { functionTool } from "@kaji/sdk";
import { z } from "zod";

export const getWeather = functionTool({
  name: "get_weather",
  description: "Get the current weather for a city",
  parameters: z.object({
    city: z.string().describe("e.g., Seattle, WA"),
    units: z.enum(["c", "f"]).default("f"),
  }),
  execute: async ({ city, units }) => {
    // city: string, units: "c" | "f" — fully inferred from Zod
    const data = await fetchWeather(city, units);
    return { tempF: data.tempF, conditions: data.conditions };
  },
});
```

**The bar:** Vercel AI SDK's `tool({ parameters, execute })` has full Zod → execute args inference. kaji must match or beat it. Sub-Plan 0 documents the inference path explicitly; the README's first code block shows it.

**Error discrimination:** Tool failures surface as discriminated unions:
```ts
type ToolFailure =
  | { kind: "validation_error"; issues: ZodIssue[] }
  | { kind: "policy_denied"; reason: string }
  | { kind: "approval_rejected"; reason: string }
  | { kind: "execution_error"; cause: unknown };
```
Each replay event carries the kind. The replay viewer color-codes by kind.

## Sub-Plan Index

| # | Sub-Plan | Status | Gates | Why this matters |
|---|----------|--------|-------|------------------|
| 0 | **Positioning + Fumadocs docs site + public roadmap** | Detailed below | none | Positioning + tool-shape docs + "what kaji is NOT" + roadmap. The paradigm lands here. |
| 0.5 | **Telemetry + GTM prep (design partners, launch artifact)** | Scoped below | 0 | Instrument the shadcn-analogy bet from day 1; GTM scaffolding so v1 doesn't ship to crickets |
| 1 | **Approval handler transport + EventStore.subscribe** | Scoped below | none | Production agents need non-CLI approval; event-driven, not polled |
| 1.5 | **Prod table-stakes (token accounting, cancellation, provider rate-limit)** | Scoped below | none | Every prod agent needs these; v1 can't ship without them |
| 2 | **Built-in integrations registry (10 hand-written, vendored on `kaji add`)** | Detailed below | 0 | The shadcn-style built-ins; bet target |
| 3 | **`kaji new tool <url>` — OpenAPI-to-TS codegen** | Scoped below | 0 | Generated integrations from specs, same vendored end-state as built-ins; this is the wedge that survives even if the bet on built-ins fails |
| 4 | **Provider expansion + per-provider entry points** | Scoped below | 0 | Gemini + Kimi; `@kaji/sdk/openai` etc. for tree-shaking |
| 5 | **ToolRetriever only (DocumentRAG deferred to v2)** | Scoped below | 0 | Tool-narrowing is the differentiator; full RAG isn't where kaji wins |
| 5.5 | **`kaji eval` — golden-trace agent regression testing** | Scoped below | 0, 6a | The eval story event-sourced replay unlocks; nobody else can do this |
| 6 | **Replay v1 — CLI pretty-printer + HTML viewer** | Detailed below | 0 | Leg 2 of the wedge; CLI first (debugging surface), HTML second (sharing surface) |
| 7 | **`bun create kaji-agent` template (Bun server, Cloudflare Worker)** | Scoped below | 0, 2, 4, 6 | The 5-minute demo |
| 7.5 | **`kaji doctor` — environment health check** | Scoped below | 2, 4 | First-run friction killer; every mature CLI has one |
| 8 | **Runtime test matrix (Node 22+, Bun) + CI release smoke** | Scoped below | 4 | Credibility on target runtimes; nightly live-integration smoke with real keys |
| 9 | **MCP server export (kaji tools → MCP)** | Scoped below | 2 | Lets other clients consume kaji-defined tools; closes the "no MCP?" objection without inverting the paradigm |
| 10 | **`kaji-serve` hardening (split to separate plan doc)** | Reference | none | Python product on its own track |

**Ordering rationale:** Sub-Plan 0 sets the paradigm + docs site. Sub-Plans 1-9 are the TS product; many can land in parallel after 0. Sub-Plan 10 is excluded from this plan (separate Python-product effort). The v1 ship target is Sub-Plans 0-9 complete.

**The previous MCP-client sub-plan is gone.** Consuming external MCP servers at runtime would invert the paradigm (runtime pointers, not files-in-repo). For users who want to call an external MCP server, the workflow is: `kaji new tool --mcp <command>` introspects the server's tool list at codegen time and emits TypeScript wrappers into the user's repo. Same paradigm. (Documented as a Task inside Sub-Plan 3.)

---

# Sub-Plan 0: Positioning + Fumadocs Docs Site + Public Roadmap

**Goal:** Stand up the docs site under `kaji/ts/docs/` with the paradigm statement above the fold. Every subsequent sub-plan ships content into this site.

**Files:**
- Modify: `kaji/ts/README.md` — rewrite top section with paradigm statement; link to docs site
- Create: `kaji/ts/docs/` — Fumadocs site (Next.js 15 + Fumadocs)
- Create: `kaji/ts/docs/app/(home)/page.tsx` — landing (paradigm headline + 6-line code snippet + integration grid + replay demo)
- Create: `kaji/ts/docs/content/docs/index.mdx` — getting started
- Create: `kaji/ts/docs/content/docs/quickstart.mdx` — `bun add @kaji/sdk` → write an agent → run it → see replay
- Create: `kaji/ts/docs/content/docs/paradigm.mdx` — "Why every tool lives as TypeScript in your repo." Names the comparison with eve, flue, Vercel AI SDK. States the trade explicitly.
- Create: `kaji/ts/docs/content/docs/integrations/index.mdx` — registry browser (auto-generated from `registry/index.json`)
- Create: `kaji/ts/docs/content/docs/codegen.mdx` — `kaji new tool <url>` workflow
- Create: `kaji/ts/docs/content/docs/replay.mdx`
- Create: `kaji/ts/docs/content/docs/providers/{openai,anthropic,gemini,kimi}.mdx`
- Create: `kaji/ts/docs/content/docs/runtimes.mdx`
- Create: `kaji/ts/docs/content/docs/roadmap.mdx` — public roadmap mirroring TODOS.md (v1.1, v2). Signals "this is a real product."
- Modify: `kaji/ts/package.json` — add `docs:dev`, `docs:build` scripts

### Task 0.1: Confirm Fumadocs reuse path
- [ ] **Step 1:** `ls demos/docs 2>/dev/null || ls apps/docs 2>/dev/null`
- [ ] **Step 2:** Read its `next.config.{js,mjs,ts}`, `package.json`, `app/layout.tsx`
- [ ] **Step 3:** Decide: new app under `kaji/ts/docs/` (recommended) vs section in existing docs
- [ ] **Step 4:** No commit — investigation only

### Task 0.2: Scaffold `kaji/ts/docs`
- [ ] **Step 1:** Copy Fumadocs starter pattern from existing docs app (file-by-file: `next.config.mjs`, `package.json`, `source.config.ts`, `app/layout.tsx`, `mdx-components.tsx`, `tsconfig.json`)
- [ ] **Step 2:** Strip content; keep shell
- [ ] **Step 3:** `bun install` from `kaji/ts/docs/`; verify `bun run dev` boots
- [ ] **Step 4:** Add to root `package.json` workspaces if needed
- [ ] **Step 5:** Commit on branch `feat/ts-docs-scaffold`

### Task 0.3: Write the landing page

Above the fold:
1. Paradigm sentence ("every tool your agent calls lives as TypeScript in your repo")
2. 6-line code snippet showing the `functionTool({ name, parameters, execute })` shape with full Zod inference
3. Two-button CTA: "kaji add linear" / "kaji new tool <openapi-url>"
4. Embedded replay viewer (placeholder for v1; Sub-Plan 6 fills in)
5. Integration grid (placeholder; Sub-Plan 2 fills in)
6. "What kaji is NOT" section (includes the eve and flue comparisons explicitly)

- [ ] **Step 1:** Draft `app/(home)/page.tsx`
- [ ] **Step 2:** Pull the snippet from `kaji/ts/examples/minimal-agent/index.ts` — must compile
- [ ] **Step 3:** Commit

### Task 0.4: Quickstart MDX

Write `content/docs/quickstart.mdx` so a developer who's never seen the SDK can:
1. `bun add @kaji/sdk openai`
2. Set `OPENAI_API_KEY` in `.env`
3. Run `kaji add linear` (writes `src/integrations/linear/` into their project)
4. Set `LINEAR_API_KEY`
5. Write `agent.ts` (10 lines)
6. Run it, see streaming output
7. Open the replay file

Test by following the steps in a fresh tmp dir before merging.

### Task 0.5: Paradigm MDX

Write `content/docs/paradigm.mdx`. This is the load-bearing doc — it's how the paradigm spreads. Required structure:
1. The sentence
2. The trade (more files in your repo; in exchange, debuggable, reviewable, type-safe, no runtime indirection)
3. Comparison to eve, flue, Vercel AI SDK, Mastra, LangChain JS — direct, no hedging
4. When NOT to use kaji (you want runtime indirection, you want sandboxed code execution, you want only chat UI)
5. The named bet (shadcn analogy) and the instrumentation that tests it (forward link to telemetry docs)

### Task 0.6: Deploy
- [ ] **Step 1:** Configure Vercel for `kaji/ts/docs`
- [ ] **Step 2:** Deploy to staging URL
- [ ] **Step 3:** Decide domain (unresolved decision; surfaced below)
- [ ] **Step 4:** Commit deploy config; open PR

**Acceptance:**
- Developer landing on the site reads the paradigm and reaches a working quickstart in <60 seconds
- The quickstart works copy-paste against a clean repo
- The site builds in CI on every PR
- Paradigm MDX names the comparison to eve and flue explicitly
- Public roadmap page lists v1.1 and v2 items

---

# Sub-Plan 0.5: Telemetry + GTM Prep

**Goal:** Two deliverables before v1 ships: (a) opt-in anonymous telemetry instrumenting the shadcn-analogy bet, (b) GTM scaffolding so v1 has a place to land traffic.

## 0.5.a Telemetry (opt-in, privacy-first)

**Files:**
- Create: `kaji/ts/src/telemetry/client.ts` — `sendEvent(name, props)` with batching + offline queue; respects `DO_NOT_TRACK=1` and `KAJI_TELEMETRY=off`
- Create: `kaji/ts/src/telemetry/anonymize.ts` — stable anonymous client ID (hash of machine-id + project root)
- Modify: `kaji/ts/src/cli/init.ts` — first-run prompt: "Help kaji improve with anonymous usage stats? (y/n, default n)"
- Modify: `kaji/ts/src/cli/add.ts`, `cli/run.ts` (if added), `cli/replay.ts`, `cli/eval.ts` (when shipped) — emit events
- Create: `kaji/ts/docs/content/docs/privacy.mdx` — what we collect, what we don't, how to opt out, `KAJI_TELEMETRY=debug` to inspect events

**Event shape (frozen for v1):**
- `init.completed { template? }`
- `integration.added { name, source: "built-in" | "codegen" }`
- `integration.edited { name, semantic: boolean }` — fires when `src/integrations/<name>/` content hash differs from manifest hash, sampled on next `kaji <any-command>`. `semantic: true` when >5 lines changed (excludes formatting). **This is the load-bearing event for the shadcn-analogy bet.**
- `integration.edited.feedback { name, why_summary }` — **optional follow-up** prompted on next `kaji <command>` after `integration.edited.semantic=true`: "We see you edited <name>'s integration. One sentence on what you changed and why? (helps us improve — skip with Enter)." User input is sent only on explicit submit; default is skip. Captures the qualitative "why edit" signal the ratio alone can't show.
- `agent.run { provider, integration_count, turn_count, success }` — counts only
- `replay.opened { format }`
- `eval.run { golden_session_count, diff_count }`
- `cli.command { name, args_count, exit_code }`

**Backend:** PostHog Cloud free tier default. Self-hosted alternative documented.

**Honest note on the "your repo, your code" pitch:** the telemetry client phones home to PostHog when opted in. That's a runtime dep the user didn't write. The first-run prompt makes this explicit ("opt in to send anonymous events to PostHog?") rather than burying it. Opt-out is the default. Users running fully air-gapped (no telemetry, no embedder, no MCP server export) get a pure no-network-dep experience. Documented in `privacy.mdx`.

**Acceptance:**
- Telemetry opt-in by default
- `KAJI_TELEMETRY=debug kaji <anything>` shows every event before sending
- Public dashboard at `docs.kaji.dev/stats` shows aggregate numbers — proves we're not hiding what we collect
- Tests cover: opt-out default, env-var disable, debug mode, no PII in payloads

## 0.5.b GTM scaffolding

**Deliverables:**
1. **3 named design partners.** Reach out before v1 ships:
   - One TS-shop engineer at a product company (Ramp-shaped)
   - One indie hacker shipping agents on Bun or Cloudflare
   - One user of a competitor (Vercel AI SDK, Mastra, LangChain JS, eve, flue) willing to A/B
2. **Launch artifact:** HN-shaped post + 2-minute demo video script, committed to `kaji/ts/docs/launch/`
3. **Integration partner co-launches:** outreach to Linear, Resend, Porsager (`postgres`), `@modelcontextprotocol`. One yes is a force multiplier.
4. **Community seed:** GitHub Discussions space (default; Discord deferred — fewer moderation costs), opened at rc.1

**Files:**
- Create: `kaji/ts/docs/launch/hn-post-draft.md`
- Create: `kaji/ts/docs/launch/demo-video.md`
- Create: `kaji/ts/docs/launch/design-partners.md` (gitignored; private log)
- Modify: `kaji/ts/docs/content/docs/index.mdx` — design partners badge section when partners commit

**Acceptance:**
- 3 design partner conversations logged, at least 1 commitment
- HN post draft reviewed
- Demo video script complete, video recorded
- Integration partner outreach has at least 1 yes
- GitHub Discussions space ready to open at rc.1

---

# Sub-Plan 1: Approval Handler Transport

**Goal:** Production tool-using agents need an approval flow that works over HTTP/WebSocket, not just CLI stdin.

**Files (create/modify):**
- `kaji/ts/src/runtime/approval/types.ts` — `ApprovalHandler` interface
- `kaji/ts/src/runtime/approval/event_handler.ts` — `EventApprovalHandler` (event-driven via `EventStore.subscribe`)
- `kaji/ts/src/runtime/approval/auto.ts` — `AutoApprovalHandler` (static allow/deny based on policy)
- Modify: `kaji/ts/src/sessions/store.ts` — extend `EventStore` interface with `subscribe(sessionId, predicate, callback): Unsubscribe`. `InMemoryEventStore` implements via internal listener list firing on `appendEvents`.
- Modify: `kaji/ts/src/tools/planner.ts` — accept the new `ApprovalHandler` interface
- Modify: `kaji/ts/src/tools/policy.ts` — policy denials emit `TOOL_CALL_FAILED` with `reason: "policy_denied"`
- Modify: `kaji/ts/src/index.ts` — export new types

**Interfaces:**
```ts
interface ApprovalHandler {
  request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision>;
}
type ApprovalDecision = { granted: true } | { granted: false; reason: string };
```

`EventApprovalHandler` emits `TOOL_APPROVAL_REQUESTED`, subscribes to the EventStore for matching `TOOL_APPROVAL_GRANTED` or `TOOL_APPROVAL_REJECTED` (correlated by `sessionId + toolCallId`), resolves with the decision. Default timeout 30s.

**Acceptance:**
- Existing `CliApprovalHandler` continues to work (no breaking change)
- `new EventApprovalHandler(store, { timeoutMs: 30000 })` works for HTTP/WS server deployments
- Tests: multi-step flow (request → grant → execute), timeout, denial, concurrent multi-call in one turn, store-unavailable-mid-poll

---

# Sub-Plan 1.5: Production Table-Stakes (Token Accounting + Cancellation + Provider Rate-Limit)

**Goal:** Three things every production agent needs that the prior plan didn't surface explicitly. Adding them now because outside-voice flagged them as gaps and they're cheap with CC.

## 1.5.a Token & cost accounting

**Files:**
- Modify: `kaji/ts/src/events/schemas.ts` — add `tokens` and `cost_usd` optional fields to `AGENT_MESSAGE_COMPLETED` and `TOOL_CALL_COMPLETED` event schemas
- Modify: each provider in `kaji/ts/src/providers/` — read response usage headers (OpenAI `x-usage`, Anthropic `usage` in response body, Gemini `usageMetadata`) and emit on `done` delta
- Create: `kaji/ts/src/providers/_cost_table.ts` — per-model $/1M tokens table (input + output rates), updated quarterly
- Modify: `kaji/ts/src/sessions/replay.ts` — `SessionState` exposes `totalTokens`, `totalCostUsd`
- Modify: replay viewer + CLI pretty-printer — render per-turn and total token/cost

**Acceptance:**
- Every completed turn in the event log carries `tokens.input`, `tokens.output`, `cost_usd`
- `kaji replay session.jsonl --format summary` includes total cost
- Pricing table is a single TS file; CI test asserts every supported model has an entry

## 1.5.b Cancellation via `AbortSignal`

**Files:**
- Modify: `kaji/ts/src/runtime/cancellation.ts` (exists per audit) — make `CancellationToken` wrap a native `AbortSignal`; expose `runtime.runTurn(prompt, { signal })`
- Modify: each provider — accept `signal` in `generate(input, opts?)`, pass to underlying `fetch`
- Modify: each integration's `execute` — handler signature gets `ctx.signal: AbortSignal`; integration template includes a `// Respect ctx.signal in long-running tools` comment

**Acceptance:**
- `const controller = new AbortController(); runtime.send(prompt, { signal: controller.signal }); controller.abort();` — pending provider stream cancels within 100ms, pending tool call receives the abort
- Cancelled turn emits `RUN_CANCELLED` event, no `AGENT_MESSAGE_COMPLETED`
- Tests cover: abort mid-stream, abort mid-tool-call, abort after completion (no-op)

## 1.5.c Provider rate-limit handling

**Files:**
- Modify: each provider in `kaji/ts/src/providers/` — on 429 response, parse `Retry-After` (or `x-ratelimit-reset`) and retry up to N times with exponential backoff. Emit `PROVIDER_RATE_LIMITED { provider, retry_after_ms, attempt }` events so replay shows the wait.
- Config: `new OpenAIProvider({ apiKey, retry: { maxAttempts: 3, baseDelayMs: 1000 } })` — opts on every provider, sane defaults
- Tests: mock 429 response, assert retry happens, assert event log shows the wait, assert eventual success or surfacing `ProviderRateLimitedError` after exhaust

**Acceptance:**
- All four providers (OpenAI, Anthropic, Gemini, Kimi) handle 429 uniformly
- Default retry: 3 attempts, exponential backoff starting at 1s, max 60s total wait
- Replay log shows rate-limit events with timing — visible in HTML viewer and CLI

---

# Sub-Plan 2: Built-in Integrations Registry (10 Hand-Written, Vendored on `kaji add`)

**Goal:** Ship 10 hand-written integrations covering "read internal data," "act on tickets," "reach the outside world." `kaji add <name>` copies the integration source into `src/integrations/<name>/` in the user's project. User owns the code from that moment.

**Per-integration deliverables:**
- `kaji/ts/registry/<name>/` — directory with `index.ts` (tool definitions), `manifest.json` (auth requirements, peer deps, content hash for edit detection), `README.md`
- Update `kaji/ts/registry/index.json` — add entry
- `kaji/ts/registry/<name>/<name>.test.ts` — mock-client tests + at least one live integration test (skipped without credentials)
- Docs page at `kaji/ts/docs/content/docs/integrations/<name>.mdx`

**Minimal `SecretSource` interface (Sub-Plan 2 prerequisite; landed in `kaji/ts/src/auth/secret_source.ts` before integration template):**

Defined before any integration ships. CEO outside-voice round 3 flagged auth shape sprawl across vendored integrations as the ducked concern. v1 doesn't ship every secret backend, but the *interface* exists so the v1 integrations consume secrets through one abstraction:

```ts
interface SecretSource {
  get(key: string): Promise<string | undefined>;
}

// v1 default: env-only
class EnvSecretSource implements SecretSource {
  async get(key: string): Promise<string | undefined> {
    return process.env[key];
  }
}

// Every integration's constructor takes an optional secretSource: SecretSource = new EnvSecretSource()
```

v1.1 ships `VaultSecretSource`, `DopplerSecretSource`, `AWSSecretsSource`. The interface is forward-compatible — users who outgrow env vars swap one constructor arg without rewriting integrations.

**Integration template** (Sub-Plan 2 prerequisite; lands as task 2.0):
- Create `kaji/ts/registry/_template/` with the canonical shape
- Create `scripts/check-integration.ts` — CI lint that fails any registry entry missing required files or sections
- **Each integration's `index.ts` starts with this comment** (CEO outside-voice recommendation, makes customization obvious):

```ts
// This is YOUR <Name> integration. Edit it.
// Common customizations:
//   1. Trim the tools array to just what your agent needs
//   2. Tighten Zod schemas — make fields required if your agent should never miss them
//   3. Map API errors to retry vs surrender for your ToolPlanner policy
//   4. Add helper tools your agent wants but the API doesn't have natively
// Updates: re-run `kaji add <name>` to diff against the latest version we ship.
```

**Tier 1 — ship week 1 (zero friction):**

### 2.1: HTTP-generic
**Installs at:** `src/integrations/http/`. Universal escape hatch. Tools: `http.fetch(url, opts)`, `http.post`, `http.put`, `http.delete`. No auth. Sandbox: allowlist hosts via `policy: { allowedHosts: [...] }` to prevent SSRF.

### 2.2: Filesystem (installs at `src/integrations/fs/`)
Sandboxed to a root passed at construction. Tools: `fs.list(path)`, `fs.read(path)`, `fs.write(path, content)`, `fs.glob(pattern)`. No auth. Refuses paths escaping the sandbox root.

### 2.3: Web fetch (installs at `src/integrations/web/`)
Tools: `web.fetch(url)` (reader-mode HTML via `@mozilla/readability`), `web.fetch_raw(url)`, `web.search(query)` (uses Brave Search API if `BRAVE_API_KEY` set, otherwise throws).

### 2.4: SQLite (installs at `src/integrations/sqlite/`)
Wraps `better-sqlite3`. Tools: `sqlite.query(sql, params)`, `sqlite.exec(sql)`, `sqlite.schema()` (CREATE TABLE statements). Ships with demo DB for quickstart.

**Tier 2 — ship week 2 (one-token, Ramp-shaped):**

### 2.5: Postgres (installs at `src/integrations/postgres/`)
Wraps `postgres`. Tools: `pg.query`, `pg.exec`, `pg.schema`, `pg.tables()`, `pg.describe(table)`. Connection via `DATABASE_URL`.

### 2.6: GitHub (installs at `src/integrations/github/`)
Wraps `@octokit/rest`. Tools: `gh.issues.{list,get,create,comment}`, `gh.prs.{list,get}`, `gh.files.get_content`, `gh.search`. Auth: PAT via `GITHUB_TOKEN`. **Reads the existing github integration first to decide rewrite vs leave-alone.**

### 2.7: Linear (installs at `src/integrations/linear/`)
Wraps `@linear/sdk`. Tools: `linear.issues.{list,get,create,update}`, `linear.comments.create`, `linear.cycles.current`, `linear.teams.list`. Auth: PAT via `LINEAR_API_KEY`.

### 2.8: Resend (installs at `src/integrations/resend/`)
Wraps `resend`. Tools: `resend.send(to, subject, body)`, `resend.send_html(to, subject, html)`. Auth: API key via `RESEND_API_KEY`.

**Tier 3 — choice surfaced as unresolved decision:**

The Tier 3 slot is one of three options. Default 3A (lowest-friction); 3B if a real procurement consumer surfaces; 3C if storage-shaped demos land first.

- **Option 3A (default, consumer-startup shape):** Slack + Notion
- **Option 3B (procurement-agent shape):** PDF reader (`pdf-parse`/`unpdf`) + CSV/Excel parser (`papaparse`/`xlsx`)
- **Option 3C (storage-shaped):** S3-compatible (`@aws-sdk/client-s3`, works with AWS/R2/MinIO) + one of 3A/3B

**Per-integration task pattern:**

- [ ] **Step 1:** Write failing tests against a mock client. Cover: happy-path tool call, missing auth, malformed input, API error, rate-limit (429) retry behavior.
- [ ] **Step 2:** Implement tools using `functionTool` + Zod schemas
- [ ] **Step 3:** Write the live integration test (skipped without creds)
- [ ] **Step 4:** Write the README and docs page
- [ ] **Step 5:** Update `registry/index.json`
- [ ] **Step 6:** Add optional peer deps to root `kaji/ts/package.json`
- [ ] **Step 7:** Commit on `feat/integration-<name>`

**Sub-Plan 2 overall acceptance:**
- All 10 integrations shipped and documented
- `kaji list-integrations` shows all 10
- Docs site landing page renders integration grid from `registry/index.json`
- `scripts/check-integration.ts` runs in CI on every PR

**`kaji add` semantics:**
- Copies registry source into `src/integrations/<name>/` in user's project
- Records content hash in user's `manifest.json` (enables edit-detection telemetry per Sub-Plan 0.5.a). **Hash is frozen at `kaji add` time and only updated when the user explicitly runs `kaji add <name> --upgrade`.** Never auto-updated.
- Adds optional peer deps to user's `package.json` automatically
- Re-running `kaji add <name>` shows a diff against the latest registry version and prompts to overwrite, skip, or 3-way merge via `git merge-file --diff3` (falls back to overwrite-or-skip if `git` is not on PATH)

**`kaji upgrade` — security patching for vendored integrations (new in this revision):**
- `kaji upgrade` scans all vendored integrations in `src/integrations/`
- For each, compares the user's `package.json` peer dep version against the registry's recommended version
- If a registry entry has been re-released as a security update (new `manifest.json` field: `security_release: { advisory_url, severity }`), prompts the user to upgrade that specific integration
- `kaji upgrade --security-only` filters to just security releases (CI-runnable)
- `kaji upgrade --check` exits 1 if any security upgrade is outstanding (CI gate)
- This is how the vendored model handles "Octokit v6 has a CVE" without each user manually patching

**Name collision policy (`kaji add` and `kaji new tool` writing to the same dir):**
- If `src/integrations/<name>/` already exists, the command refuses with a clear error and suggests `--name <override>` or `--force`
- `kaji new tool` derives the dir name from `info.title` slug; collisions with built-in names (e.g., a user-supplied OpenAPI spec titled "linear") require explicit `--name`

---

# Sub-Plan 3: `kaji new tool <url>` — OpenAPI-to-TS Codegen

**Goal:** `kaji new tool https://your-api.com/openapi.json` parses an OpenAPI spec and writes a typed tool file into `src/integrations/<name>/`. Same end state as `kaji add`: TypeScript files the user owns. This is the wedge that survives even if the shadcn-analogy bet on built-ins fails (generated code from an unreliable spec always needs editing).

**Decision: full TS port, not Python wrapper.** Earlier draft proposed shelling to `uvx kaji gen`; eng outside-voice flagged this as dead-on-arrival in JS shops. Port the 358-line Python `gen.py` to TypeScript.

**Files:**
- Create: `kaji/ts/src/cli/gen.ts` — `kaji new tool <url>` and `kaji gen --spec ... --out ...` entries
- Create: `kaji/ts/src/cli/gen/{parse,emit,types,mcp}.ts` — broken into OpenAPI parsing, TS emission, shared types, and MCP-spec parsing
- Modify: `kaji/ts/src/cli/index.ts` — register both commands
- Create: `kaji/ts/tests/cli.gen.test.ts` — snapshot test (OpenAPI fixture → expected output). Cross-language parity test (diffs against Python emitter output when Python is available in CI).
- Create: `kaji/ts/docs/content/docs/codegen.mdx`

**Interfaces:**
- `kaji gen --spec <path-or-url> --out <dir> [--prefix <name>]` — explicit form
- `kaji new tool <url>` — shortcut: auto-detects OpenAPI/GraphQL, picks sensible defaults (output dir = `src/integrations/<api-name>/`, name from `info.title`), prompts interactively only for ambiguities
- `kaji new tool --mcp <command>` — introspects an external MCP server's tool list **at codegen time only (snapshot)** and emits TypeScript wrappers into the user's repo. **This is how kaji consumes external MCP without violating the paradigm** (the code lives in the repo, not behind a runtime pointer).

**Critical clarification on the `--mcp` mode:** the generated `execute` body **spawns the MCP server as a subprocess on each call** (stdio transport) or **calls the configured HTTP endpoint**. The MCP server *is* a runtime dep — but it's a dep the user wired up explicitly in their repo, with the call site visible as TypeScript they can read and modify. The paradigm is preserved at the **boundary**: the tool definition is in the repo; what that tool does at runtime (call an MCP server, call a REST API, query a DB) is the same kind of runtime work any tool does. Documented explicitly in `codegen.mdx`.

**`kaji new tool <url> --upgrade`** re-snapshots the spec/MCP server, diffs against the existing generated file, prompts user to accept/skip/3-way-merge (same as Sub-Plan 2's `kaji add --upgrade`).

**Output shape:**
- `src/integrations/<api-name>/index.ts` — `TOOLS` array + handler functions
- `src/integrations/<api-name>/manifest.json` — spec source URL, version, content hash, auth requirements
- `src/integrations/<api-name>/README.md` — auto-generated setup steps

**Codegen does:**
1. Parse spec (OpenAPI 3.x, GraphQL schema, or MCP `list_tools` response)
2. Filter endpoints: skip `deprecated: true`, OAuth-only, binary upload/download
3. Classify each as `read` (GET) or `write` (POST/PUT/PATCH/DELETE) for `ToolPolicy`
4. Emit one `functionTool({ name, description, parameters, execute })` per endpoint with Zod schemas synthesized from the spec
5. Write the output file with the same "this is YOUR <Name> integration" header comment from Sub-Plan 2's template

**Acceptance:**
- `kaji new tool https://petstore3.swagger.io/api/v3/openapi.json` writes `src/integrations/petstore/index.ts` with ≥4 tools
- **Generated file compiles with `tsc --noEmit --strict`** (not just `tsc --noEmit`). No `any` casts in output. No silent `additionalProperties: true` → `unknown` escapes; if the spec is too loose to generate a useful schema, the codegen emits a clear comment (`// TODO: tighten this schema — spec was ambiguous`) instead of `z.unknown()`
- Output passes the same integration template lint (`scripts/check-integration.ts`) as hand-written integrations
- Generated tools work end-to-end in an agent (one integration test)
- `kaji new tool --mcp 'npx -y @modelcontextprotocol/server-filesystem /tmp'` introspects the filesystem MCP server, writes TypeScript wrappers
- Re-running `kaji new tool <url> --upgrade` diffs against the prior generated version (manifest tracks source spec hash)

**Risk named explicitly (CEO outside-voice round 3):** OpenAPI specs in the wild are inconsistent and under-typed. If the codegen produces "TypeScript no one wants to read," the wedge-fallback (codegen-survives-if-shadcn-fails) collapses. Three mitigations: (1) `--strict` compile check above, (2) generated files have prominent "this is YOUR generated tool — edit it" header same as hand-written integrations, (3) `kaji new tool --report` flag that emits a *spec quality* report showing which endpoints were dropped, which schemas were tightened with placeholders, which auth shapes were detected. User knows what they're getting before they commit to vendoring it.

---

# Sub-Plan 4: Provider Expansion + Per-Provider Entry Points

**Goal:** Ship Gemini and Kimi providers; split SDK exports per-provider for tree-shaking.

**Files:**
- Rename: `kaji/ts/src/providers/_args.ts` → `_translate.ts`
- Create: `kaji/ts/src/providers/_env.ts` — `envApiKey(envVar, providerName)` DRY helper
- Modify: `kaji/ts/src/providers/openai.ts` — expose `readonly model` and `readonly baseURL?` (additive)
- Create: `kaji/ts/src/providers/gemini.ts` — via `@google/genai`; deterministic tool-call IDs via SHA-256 of `name + JSON.stringify(args)` to dedupe duplicate stream chunks
- Create: `kaji/ts/src/providers/kimi.ts` — extends `OpenAIProvider`; defaults `moonshot-v1-32k` + `https://api.moonshot.cn/v1`
- Modify: `factory.ts`, `registry.ts`, `index.ts`
- Modify: `kaji/ts/package.json` — `@google/genai` to optional peerDeps

**Per-provider entry points:**
- Modify `kaji/ts/tsup.config.ts` — emit `dist/openai.js`, `dist/anthropic.js`, `dist/gemini.js`, `dist/kimi.js`
- Modify `kaji/ts/package.json` `exports` map — add `"./openai"`, `"./anthropic"`, `"./gemini"`, `"./kimi"`
- Update docs pages — show per-provider import (`import { OpenAIProvider } from "@kaji/sdk/openai"`)

**Test gaps (carried forward):**
- G1: baseURL flows through to client
- G2: registry resolves `getProvider("gemini")` and `getProvider("kimi")`
- G3: Gemini role mapping (system→user, assistant→model)
- G4: non-string content JSON.stringify'd
- G5: stream init failure → `ProviderAPIError`
- G6: missing env + missing explicit apiKey → `ProviderConfigError`
- Q1: deterministic tool-call ID dedupes duplicate Gemini chunks
- Live integration tests skipped without keys

**Acceptance:**
- `import { OpenAIProvider } from "@kaji/sdk/openai"` tree-shakes others
- Gemini and Kimi stream text + tool calls correctly
- All 7 test gaps covered

---

# Sub-Plan 5: ToolRetriever (DocumentRAG Deferred to v2)

**Goal:** Ship `ToolRetriever` for tool-narrowing. Defer `DocumentRAG` — half-built RAG is signaling weakness, not strength.

**Files (create):**
- `kaji/ts/src/tools/retriever.ts`
- `kaji/ts/src/tools/embedder.ts` — `Embedder` interface + `OpenAIEmbedder` (`text-embedding-3-small`)
- `kaji/ts/src/tools/_inmem_embedding_index.ts` — private cosine index
- Tests with mock embedder
- `kaji/ts/docs/content/docs/tool-retriever.mdx`

**Interfaces:**
```ts
interface Embedder {
  embed(texts: string[]): Promise<number[][]>;
  readonly dim: number;
}

class ToolRetriever {
  constructor(opts: { embedder: Embedder });
  index(tools: ToolSpec[]): Promise<void>;
  retrieve(query: string, k?: number): Promise<ToolSpec[]>;
}
```

**Acceptance:**
- Precomputes tool embeddings once; retrieves top-k by cosine sim
- `AgentBuilder().toolRetriever(r).build(...)` wires into `runTurn`
- Default (no retriever) passes all tools
- Retrieval failure falls back to "all tools"
- Documented as "for narrowing tools when you have 50+ registered"
- **Paradigm-leak note:** `OpenAIEmbedder` calls OpenAI's embeddings API at runtime. Documented as a runtime dep on the embedding service. Users who want the paradigm strictly preserved can ship a `LocalEmbedder` (e.g., `@xenova/transformers` running locally) — interface is open. ToolRetriever is opt-in; default behavior (no retriever) has no network dep.

**RAG for v1 users:** point at MCP RAG servers (filesystem, postgres, brave) — wrapped via `kaji new tool --mcp <command>` so the code lands in their repo, paradigm preserved.

---

# Sub-Plan 5.5: `kaji eval` — Golden-Trace Regression Testing

**Goal:** Turn event-sourced replay from "debugging surface" into "test surface." Capture a known-good agent session as a golden trace; replay against current agent config; diff tool calls + final response; flag regressions in CI. Competitors can't do this — they don't have the event log.

**Files (create):**
- `kaji/ts/src/cli/eval.ts` — `kaji eval <golden.jsonl> [--current <agent.ts>] [--judge exact|llm] [--strict] [--batch <dir>] [--report <path>]`
- `kaji/ts/src/eval/replay_against.ts` — replay golden's user messages against current agent
- `kaji/ts/src/eval/diff.ts` — semantic diff: tool call name/arg diffs, final-response diffs
- `kaji/ts/src/eval/judge.ts` — LLM-as-judge using the configured provider
- `kaji/ts/tests/cli.eval.test.ts` — snapshot tests
- `kaji/ts/docs/content/docs/eval.mdx`

**Interfaces:**
```ts
type EvalResult = {
  goldenSessionId: string;
  diffs: Array<
    | { kind: "tool_call_diff"; turn: number; golden: ToolCall; actual: ToolCall | null }
    | { kind: "response_diff"; goldenText: string; actualText: string; judgeVerdict?: JudgeVerdict }
    | { kind: "missing_event"; turn: number; goldenEvent: Event }
    | { kind: "extra_event"; turn: number; actualEvent: Event }
  >;
  passed: boolean;
};
// Exit code: 0 = passed, 1 = regressions, 2 = config error
```

**Acceptance:**
- `kaji eval golden.jsonl` runs current agent against the golden's user messages, prints summary
- `kaji eval --batch ./goldens/` runs all goldens, aggregates exit codes
- LLM-as-judge uses the agent's own provider (no separate config)
- CI integration: `kaji eval --batch ./goldens/ --strict` is the regression gate
- Tests: identity case (golden passes itself), regression case (modified prompt), missing-tool-call case

---

# Sub-Plan 6: Replay v1 — CLI Pretty-Printer + HTML Viewer

**Goal:** Two surfaces, in order. CLI pretty-printer (terminal-native, 2am debugging) ships first. HTML viewer (drag-drop, share-with-PM) ships second.

**Why split:** eng outside-voice flagged browser HTML as wrong default for engineer-in-terminal target.

**Files (create):**
- `kaji/ts/src/cli/replay.ts` — `kaji replay <session.jsonl>`. Default: pretty-print to stdout (ANSI color, tree format). Flags: `--format tree|summary|json`, `--open` (launch HTML viewer), `--tail`, `--filter <kind>`, `--grep <pattern>`
- `kaji/ts/src/cli/_replay_render.ts` — terminal renderers
- `kaji/ts/replay-viewer/index.html` — single-file HTML + inline CSS + inline TS
- `kaji/ts/replay-viewer/build.ts` — Bun build script with **hard 100KB-gzipped size check** that fails the build if exceeded
- `kaji/ts/tests/cli.replay.test.ts` — snapshot per format
- `kaji/ts/tests/replay-viewer.test.ts` — happy-dom tests for filter, search, collapse/expand, 1000-event render perf (<500ms)
- `kaji/ts/docs/content/docs/replay.mdx`

**HTML viewer design:**
- Header: session ID, start time, duration, turn count, tool call count
- Timeline: vertical list of turns. Each shows user message, merged assistant text deltas, tool calls (collapsed, expand for input/output/duration), retries, errors
- Color-coded by tool failure kind (validation_error / policy_denied / approval_rejected / execution_error)
- Filter bar, search box, export (JSONL or Markdown transcript)
- Incremental render via IntersectionObserver for 1000+ events

**Constraints:**
- Total HTML <100KB gzipped (CI-enforced)
- Works offline once loaded
- No external dependencies (no CDN, system fonts only)
- Chrome, Safari, Firefox latest

**Acceptance:**
- `kaji run agent.ts --json > session.jsonl && kaji replay session.jsonl` opens in terminal
- `kaji replay session.jsonl --open` opens in browser
- Docs landing embeds the viewer with fixture session
- 1000-event log renders in <500ms

### Task 6a: CLI pretty-printer (ships first)
- [ ] Write `kaji replay` CLI accepting JSONL, render tree/summary/json
- [ ] Tests for each format
- [ ] Commit

### Task 6b: HTML viewer (ships second)
- [ ] Write viewer skeleton, parse.ts, render.ts
- [ ] Wire drag-drop + file input
- [ ] Build script with size check
- [ ] DOM tests
- [ ] Wire `--open` flag in CLI
- [ ] Commit

### Task 6c: Embed in docs
- [ ] Create `kaji/ts/docs/public/demo-session.jsonl` (hand-crafted: 3 turns, 4 tool calls, one retry)
- [ ] Embed viewer in landing page via iframe or component port (decision deferred)
- [ ] Verify on deployed docs
- [ ] Commit

---

# Sub-Plan 7: `bun create kaji-agent` Template

**Goal:** `bun create kaji-agent my-app`, pick "Bun server" or "Cloudflare Worker," working tool-using agent in <2 minutes.

**Files (create):**
- `kaji/ts/create-kaji-agent/` — separate npm package
- `kaji/ts/create-kaji-agent/templates/bun-server/` — Bun + Hono + streaming agent + Linear integration (`kaji add linear` run during scaffold) + replay log
- `kaji/ts/create-kaji-agent/templates/cloudflare-worker/` — Workers template (wrangler.toml, KV session store, webhook agent)
- `kaji/ts/create-kaji-agent/src/index.ts` — CLI prompts user, copies files, runs `bun install`, runs `kaji add linear`
- `kaji/ts/create-kaji-agent/package.json` — `"bin": { "create-kaji-agent": "./dist/index.js" }`
- `.github/workflows/publish-create.yml` — npm publish workflow
- `kaji/ts/docs/content/docs/templates.mdx`

**Acceptance:**
- `bun create kaji-agent test-app` from clean dir produces working app in <2 min
- Generated app's `src/integrations/linear/` is vendored at scaffold time (paradigm visible immediately)
- The agent run emits JSONL that `kaji replay` opens
- Smoke test in CI: `bun install && bun start && curl localhost` passes
- Tested on macOS and Linux (Windows: best-effort; surfaced as unresolved)

---

# Sub-Plan 7.5: `kaji doctor` — Environment Health Check

**Goal:** A single command (`kaji doctor`) that diagnoses first-run friction. Every mature CLI has one; the cost is one afternoon and the payoff is "doesn't work, give up" → "here's exactly what's wrong, fix line X."

**Files:**
- Create: `kaji/ts/src/cli/doctor.ts` — `kaji doctor` entry
- Modify: `kaji/ts/src/cli/index.ts` — register command
- Tests: `kaji/ts/tests/cli.doctor.test.ts` — snapshot per scenario (clean, missing peer dep, missing env var, network unreachable)
- `kaji/ts/docs/content/docs/doctor.mdx`

**Checks performed:**
- Node version ≥22 (per global constraint)
- Bun present (`bun --version` succeeds)
- `package.json` lists `@kaji/sdk` as dep
- For each integration in `src/integrations/<name>/`: required peer deps in `package.json`?
- For each integration: required env vars set? (read from each integration's `manifest.json`)
- Provider env var set? (`OPENAI_API_KEY` etc., based on which provider the user constructed in `agent.ts` — best effort via static analysis)
- Network reachable to configured provider? (`curl -I api.openai.com` style probe, optional flag `--no-network`)
- Telemetry endpoint reachable, if opted in
- `kaji eval` golden traces present in `src/evals/`? (warns if 0; not an error)

**Output format:** colored checklist per item, summary line at the end:
```
$ kaji doctor

  ✓ Node 22.10.0
  ✓ Bun 1.1.34
  ✓ @kaji/sdk 1.0.0-rc.1
  ✓ src/integrations/linear/: peer dep @linear/sdk@^4.5.0 found
  ✗ src/integrations/linear/: env var LINEAR_API_KEY not set
    Fix: add LINEAR_API_KEY=lin_... to .env
  ⚠ src/integrations/postgres/: peer dep postgres@^3 not in package.json
    Fix: bun add postgres
  ✓ Provider OPENAI_API_KEY set
  ✓ api.openai.com reachable

Summary: 1 error, 1 warning, 6 ok
```

**Acceptance:**
- Exits 0 if all checks pass, 1 if any error, 2 if check itself failed
- Each check has a clear "Fix:" line for failures
- `--json` flag emits machine-readable output for CI integration

---

# Sub-Plan 8: Runtime Test Matrix (Node 22+, Bun) + CI Release Smoke

**Goal:** Prove SDK works on committed runtimes via CI matrix. Edge runtimes tested but not committed.

**Files:**
- Modify `.github/workflows/ci.yml` — matrix: `runtime: [node-22, node-23, bun]`
- Create `.github/workflows/edge-runtimes.yml` — non-blocking, tests Cloudflare Workers (`wrangler dev --local`) + Vercel Edge (`@vercel/edge-runtime`)
- Create `.github/workflows/release-smoke.yml` — nightly, runs live integration tests with CI-secret API keys for all 10 integrations
- Create `.github/workflows/publish-sdk.yml` — `@kaji/sdk` npm publish workflow. Triggered on tag push `sdk-v*` (Changesets-managed if reused, otherwise manual tag). Requires `NPM_TOKEN` repo secret. Publishes from `kaji/ts/` after the full CI matrix passes. v1.0.0 ships through this workflow — not through `npm publish` from a maintainer's laptop.
- Create `kaji/ts/scripts/runtime-smoke.ts` — minimal smoke per runtime: import SDK, register tool, run turn with mock provider
- Modify `kaji/ts/docs/content/docs/runtimes.mdx` — explicit support matrix

**Acceptance:**
- CI matrix runs full test suite on Node 22, Node 23, Bun
- Edge runtime smoke runs as non-blocking job; failure files an issue automatically
- Nightly release-smoke runs all live integration tests; failure pages on-call
- Runtimes docs page accurately reflects current state
- `@kaji/sdk` publishes to npm via `publish-sdk.yml` on tag — no maintainer-laptop publishes

---

# Sub-Plan 9: MCP Server Export

**Goal:** Let other MCP clients (Claude Desktop, Cursor, Zed) consume kaji-defined tools. This closes the "no MCP?" objection without inverting the paradigm. **kaji exports MCP; it does not consume MCP at runtime.** External MCP consumption flows through `kaji new tool --mcp <command>` (Sub-Plan 3), which produces TypeScript files in the user's repo.

**Files (create):**
- `kaji/ts/src/mcp/server.ts` — `MCPServer` wrapping a `ToolRegistry`, exposing via the MCP protocol over stdio or HTTP
- `kaji/ts/src/mcp/transport.ts` — stdio + HTTP transports
- `kaji/ts/src/mcp/types.ts` — uses `@modelcontextprotocol/sdk` (official Anthropic SDK; optional peer dep)
- `kaji/ts/src/cli/serve_mcp.ts` — `kaji serve-mcp` CLI: stands up an MCP server exposing the current project's integrations
- Tests: spawn a kaji MCP server, connect with the official MCP client, list+call tools
- `kaji/ts/docs/content/docs/mcp.mdx` — "Expose your kaji tools as MCP" workflow

**Interfaces:**
```ts
class MCPServer {
  constructor(opts: { registry: ToolRegistry; transport: "stdio" | { kind: "http"; port: number } });
  start(): Promise<void>;
}
```

**Usage:**
```bash
# In a kaji project with src/integrations/linear/
kaji serve-mcp
# Now Claude Desktop / Cursor / Zed can add this kaji project's tools via MCP config:
# { "command": "kaji", "args": ["serve-mcp"] }
```

**Acceptance:**
- `MCPServer` exposes a `ToolRegistry` via stdio
- Live test: spawn `kaji serve-mcp` against a test project, connect with `@modelcontextprotocol/sdk` client, list and call tools
- Docs page shows Claude Desktop config snippet for consuming a kaji MCP server
- `kaji new tool --mcp <command>` (Sub-Plan 3) is the documented path for the inverse direction
- **HTTP transport requires `KAJI_MCP_TOKEN` env var or refuses to start.** All requests must include `Authorization: Bearer <token>`. Stdio transport stays unauthenticated (process-local; not a network risk).
- Tool-list response cached at server start (not recomputed per `list_tools` call) — tools don't change after registration

**Out of scope for v1:** MCP resource subscriptions, MCP sampling. Just tools.

---

# Sub-Plan 10: kaji-serve Hardening (Separate Plan Doc)

`kaji-serve` is a Python product on its own track. The serve-hardening work lives in a separate plan document.

**Action:** create `docs/superpowers/plans/2026-06-27-kaji-serve-hardening.md` with the previously written content. Cross-reference: the TS docs site links to Python serve docs for users who want a deployable backend.

---

# Required Outputs

## Agent Loop State Machine

```
                     ┌──────────────────────────────────────────┐
                     │   AgentRuntime.runTurn(sessionId)         │
                     └─────────────────┬────────────────────────┘
                                       │
                                       ▼
            ┌──────────────────────────────────────────────────────┐
            │ 1. replaySession(store, id) → SessionState           │
            │    (events.append-only; idempotent projection)       │
            └──────────────────────────────────────────────────────┘
                                       │
                                       ▼
              ┌───────────────────────────────────────────┐
              │ 2. ToolRetriever.retrieve(state)?         │  Sub-Plan 5
              │    narrow tools[] before provider call    │
              └──────────────────────┬────────────────────┘
                                     │
                                     ▼
              ┌─────────────────────────────────────────────┐
              │ 3. provider.generate(messages, tools)       │  Sub-Plan 4
              │    streams: text deltas, tool_call_*, done  │
              └──────────────────────┬──────────────────────┘
                                     │  any tool calls?
                          ┌──────────┴──────────┐
                         no                     yes
                          │                      │
                          ▼                      ▼
              [Return TurnResult]       ┌───────────────────────────────────┐
                                        │ 4a. ApprovalHandler.request(call) │ Sub-Plan 1
                                        │     bus.publish(APPROVAL_REQ)     │
                                        │     subscribe EventStore for      │
                                        │     grant/reject                  │
                                        └──────────┬────────────────────────┘
                                                   │
                                                   ▼
                                        ┌──────────────────────────────────┐
                                        │ 4b. ToolPlanner.executeScatter   │  Tools from Sub-Plan 2 + 3
                                        │     schema + policy + execute    │  (src/integrations/<name>/)
                                        │     emit TOOL_CALL_COMPLETED     │
                                        │       or TOOL_CALL_FAILED        │
                                        └──────────┬───────────────────────┘
                                                   │
                                                   └──→ loop to 1
```

## Interface Contracts

```ts
// Sub-Plan 1
interface ApprovalHandler {
  request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision>;
}
type ApprovalDecision = { granted: true } | { granted: false; reason: string };

// Sub-Plan 5
interface Embedder {
  embed(texts: string[]): Promise<number[][]>;
  readonly dim: number;
}
interface ToolRetriever {
  retrieve(query: string, allTools: ToolSpec[], k?: number): Promise<ToolSpec[]>;
}

// Sub-Plan 2 + 3 produce these; existing
interface ToolSpec {
  name: string;
  description: string;
  parameters: JSONSchema;
}

// Sub-Plan 4
interface ModelProvider {
  readonly name: string;
  generate(input: GenerationInput, opts?: GenerationOptions): AsyncGenerator<ProviderDelta>;
}
```

## NOT in scope (deferred to v1.1 or v2)

- **MCP client (runtime consumption of external MCP servers).** Inverts paradigm. Path for v1 users: `kaji new tool --mcp <command>` (codegen, lands in repo). If a real user needs runtime MCP consumption, revisit in v1.1.
- **React/Vue/Svelte framework adapters** (`useChat`, `useAgent`). v2.
- **Bundle-size budget enforced in CI** (only the 100KB replay viewer is enforced in v1).
- **Tier-3 friction integrations:** Stripe (test mode is free but account setup is friction), Supabase, Cloudflare API, HubSpot, Calendly, Gmail (OAuth tax).
- **Voice/STT/TTS modality.** Multi-month.
- **AgentReasoningNode.** Python keeps it; revisit when `langgraph-js` is real.
- **Vector DB adapters for RAG.** v2.
- **Edge runtime support commitment.** v1 tests, v1.1 promotes if data justifies.
- **GraphQL-generic codegen.** OpenAPI first; specific integrations (Linear) ship via official SDK.
- **First-class agent trace events** (`REASONING_STARTED`, `TOOL_SELECTED`, `RETRY`). Design after replay v1 reveals what's missing.
- **Interactive REPL / watch mode for `kaji run`.** v1 ships one-shot.
- **TS persistent EventStore adapters.** Replay reads JSONL; sufficient for v1.
- **Single-page browser playground** (try kaji without installing). v1.1.
- **DocumentRAG.** v2; pointing at MCP RAG servers via `kaji new tool --mcp` covers v1 RAG need.
- **Discord community channel.** GitHub Discussions covers v1.
- **Structured outputs (response_format / JSON mode).** Real prod need; deferred to v1.1 as orthogonal to the wedge. Track on roadmap.
- **OpenTelemetry bridge.** Replay event log is the v1 observability story. OTEL exporter that bridges replay events to standard span format is v1.1. Track on roadmap.
- **Secret-source abstraction (Vault, Doppler, AWS Secrets Manager).** v1 uses `process.env.<NAME>` directly. v1.1 ships a `SecretSource` interface integrations can opt into.
- **Org-shared integration templates / patch-overlay model.** Surfaces only if the shadcn-analogy bet returns "strong yes" (see Decision framework).
- **`@kaji/integrations/<name>` importable mode.** Surfaces only if the bet returns "ambiguous" or "weak."
- **SSE/WS framing helper for tool-call streams to browser clients.** `bun create` template will demonstrate one pattern in v1; promote to a first-class helper in v1.1 if multiple users land on the same shape.

## What already exists (avoid rebuilding)

- TS core: event bus, in-memory event store, session replay, tool registry, planner, builder, runtime, OpenAI + Anthropic providers
- TS CLI: `init`, `add`, `list-integrations`
- TS registry: 4 integrations (echo, gcal, github, gmail) — Sub-Plan 2 keeps echo + gcal as-is, rewrites github, adds 10 new
- Python `kaji gen` (358 LOC) emits TS — Sub-Plan 3 ports it
- Existing Fumadocs site pattern — Sub-Plan 0 reuses

## TODOS.md updates

- **v1.1 integrations:** Gmail (with OAuth guide), Stripe (test mode), HubSpot, Calendly
- **v2 integrations:** Supabase, Cloudflare API, Vercel API, Discord, Airtable, Anthropic Computer Use
- **React `useChat`/`useAgent` hooks** for v2
- **Bundle-size budget in CI**, measure v1.1, enforce v2
- **Vector DB adapters for RAG**, Pinecone, pgvector, Weaviate
- **Voice modality TS port**, multi-month
- **TS AgentReasoningNode** when `langgraph-js` reaches parity
- **Edge runtime support commitment** after v1 test data
- **Shell exec integration behind `--allow-shell` flag**, safety story design needed
- **TS persistent EventStore adapters** when a TS server consumer exists
- **First-class trace events** after replay v1
- **Interactive replay TUI** (terminal-based)
- **MCP client (runtime consumption)** if a real user needs it in v1.1
- **Browser playground** for v1.1

## Failure modes (for new codepaths)

| Codepath | Failure mode | Test? | Error handling? | User visibility |
|---|---|---|---|---|
| 1 EventApprovalHandler poll timeout | Approver disappears | YES | TOOL_CALL_FAILED reason="approval_timeout" | clear timeout in replay |
| 1 EventApprovalHandler concurrent calls | Two tool calls awaiting approval in one turn | YES | both subscribed independently | replay shows both |
| 2.1 HTTP allowlist bypass | Agent tries non-allowlisted host | YES | ToolExecutionError | clear error in replay |
| 2.2 Filesystem sandbox escape | `../../etc/passwd` | YES | ToolExecutionError | clear error |
| 2.5 Postgres connection lost | Network drop | NO — **critical gap** | reconnect via `postgres` lib (verify behavior) | gap |
| 2.6-2.10 third-party 429 | rate limit | YES per integration | retry with backoff up to N | logged as retry events |
| 3 `kaji new tool` malformed spec | OpenAPI spec parses but is internally inconsistent | YES | partial output + clear warning per skipped endpoint | actionable warning per skip |
| 3 `kaji new tool --mcp` MCP server crashes | Spawned MCP server dies during introspection | YES | clear error + suggestion to check server independently | actionable |
| 4 Gemini stream init failure | Network error | YES (G5) | ProviderAPIError | propagated |
| 4 Gemini duplicate tool-call chunks | Provider duplication | YES (Q1) | dedupe via deterministic ID | none (correct) |
| 5 ToolRetriever embedder timeout | Embedder slow | YES | fallback to all tools | none (degrade) |
| 6 Replay viewer malformed JSONL | User drops broken file | YES | per-line try/catch, inline error | error visible |
| 7 `bun create` template install fails | Network during `bun install` | YES | exit 1 + clear log | actionable |
| 8 Edge runtime smoke fails | Workers/Edge breaking change | YES | non-blocking, files issue | dev sees status page |
| 9 MCP server export tool serialization | A tool's Zod schema doesn't translate to MCP JSON Schema | YES | warn at startup, skip the tool with named reason | clear startup warning |

**Critical gap:** 2.5 Postgres reconnect behavior under transient failure. Sub-Plan 2.5 acceptance must document and test this.

**Additional test gaps surfaced in eng review pass 4 (fold into the corresponding sub-plan acceptance):**

| Gap | Sub-Plan | Required test |
|---|---|---|
| T-G1 | 2 | `kaji add` 3-way merge fallback when `git` is not on PATH (overwrite/skip prompt path) |
| T-G2 | 3 | Malformed/under-typed OpenAPI fixture → codegen emits `// TODO: tighten this schema` placeholders, `--report` flag emits dropped-endpoints + tightened-schemas + auth-shape sections |
| T-G3 | 6 | `kaji replay --tail`, `--filter <kind>`, `--grep <pattern>` each individually tested (snapshot per flag) |
| T-G4 | 5.5 | LLM-judge regression case: judge correctly reports "different" when responses diverge semantically; identity case: judge correctly reports "same" for trivial whitespace diff |
| T-G5 | 7.5 | `kaji doctor` static-analysis fallback: when provider construction is dynamic/conditional/in-config, check ALL provider env vars and warn if none set |
| T-G6 | 2 | `kaji upgrade --security-only` end-to-end: registry entry with `security_release: { advisory_url, severity }` surfaces both fields; `kaji upgrade --check` exits 1 when an outstanding security upgrade exists |
| T-G7 | 1.5.a | Kimi token extraction — Kimi uses OpenAI-compatible API but verify token usage headers actually match (don't assume) |
| T-G8 | 1.5.b | Per-integration `ctx.signal` respect — representative test in the integration template asserts that an aborted long-running tool stops within 100ms |
| T-G9 | 9 | HTTP transport refuses to start without `KAJI_MCP_TOKEN`; Zod-schema-doesn't-translate-to-MCP-JSON-Schema emits clear startup warning naming the offending tool |
| T-G10 | rc.0 | End-to-end smoke for the "10-minute hobbyist run" — `bun add @kaji/sdk + kaji add http + agent.ts runs against OpenAI` in a clean tmp dir, exits 0, produces JSONL replay log |

These gaps are P2 — they extend the planned test surface but do not block sub-plans from starting; each lands inside its sub-plan's acceptance criteria.

## Eng review pass 4 — architecture tightening

Findings from a fourth `/plan-eng-review` pass after the prior three already folded the high-severity issues. These are P2/P3 — sub-plans can start without resolving them, but the corresponding sub-plan acceptance should incorporate the fix.

| # | Sub-Plan | Finding | Fix folded |
|---|---|---|---|
| A1 | 8 | `@kaji/sdk` had no named npm publish workflow. Every other artifact (`create-kaji-agent`, docs deploy) named one. | Added `.github/workflows/publish-sdk.yml` to Sub-Plan 8 files and acceptance. |
| A2 | 0.5.a | `integration.edited` event samples on next `kaji <any-command>`. Users who only `bun add @kaji/sdk` and never put the `kaji` CLI on PATH would never fire the load-bearing signal. | Telemetry section addition: the SDK itself (not just the CLI) emits `integration.edited` on first `import("@kaji/sdk")` per process when run inside an agent (cheap dir-hash, only of `src/integrations/` siblings of the importing file). Documented in 0.5.a. **See clarification below.** |
| A3 | 5.5 | `kaji eval` semantics around `PROVIDER_RATE_LIMITED` events (added in Sub-Plan 1.5.c) undefined. Replaying a golden that recorded a 429 retry would mis-diff. | Sub-Plan 5.5 acceptance clarification: `PROVIDER_RATE_LIMITED` events are **filtered from the diff** — they are infrastructure events, not agent decisions. Same for `RUN_CANCELLED` mid-eval (treated as eval failure, not regression). |
| A4 | 9 | `MCPServer` + `ToolRetriever` interaction: cached tool list means MCP consumers always see all tools regardless of any per-query narrowing the agent does in-process. | Documented as intended behavior in Sub-Plan 9: MCP exposes the full registry. ToolRetriever is an in-process agent concern, not an export-time concern. Worth one sentence in `mcp.mdx`. |
| A5 | 7.5 | `kaji doctor` provider detection via static analysis on `agent.ts` is fragile (dynamic construction, conditional providers, config-driven). | Sub-Plan 7.5 acceptance addition: if static analysis fails to identify the configured provider, fall back to checking ALL provider env vars and warn if none set. Never silently skip. |
| Q2 | 1.5.c | `PROVIDER_RATE_LIMITED` event added but `ToolFailure` discriminated union (lines ~147-153) not extended. | `ToolFailure.kind` enum addition: `"rate_limited"` with `{ provider, retry_after_ms, attempts_exhausted: boolean }`. Land in same Sub-Plan 1.5.c commit. |
| Q3 | 2 | Per-integration live tests share env-var keyspace. Two integration test runs in the same CI invocation could collide on test data (Linear test issue, Postgres test schema, Resend test inbox). | Sub-Plan 2 acceptance addition: per-integration test sandbox names — `linear` uses dedicated test workspace ID; `postgres` uses `kaji_test_$SHA` schema; `resend` uses `+test-$SHA` address suffix. CI test cleanup runs even on failure. |
| Q4 | 6 | 100KB-gzipped HTML viewer cap is aggressive given 1000+ event handling + filter/search/export. | Sub-Plan 6 acceptance softening: 100KB target, 150KB hard cap. CI fails over 150KB; warns 100-150KB. Re-budget only if a feature genuinely cannot fit. |
| P1 | 6 | 10,000-event JSONL might be parse-bound before IntersectionObserver helps. | Sub-Plan 6 acceptance addition: 10,000-event log parses in <2s on a 2024 MacBook. If miss, use streaming JSON-Lines parser + Web Worker. Test added to `replay-viewer.test.ts`. |
| P2 | 0.5.a | `integration.edited` content-hash recompute over 50 vendored integrations on every CLI call could add visible latency. | Cache hashes in `node_modules/.cache/kaji/edit-hashes.json` keyed by directory mtime. Invalidate per-directory when mtime changes. Documented in 0.5.a. |
| P3 | 5.5 | LLM-as-judge in CI with N goldens × multi-provider × judge call is expensive ($ + time). | Sub-Plan 5.5 acceptance addition: judge-verdict cache. Key = SHA-256 of `(golden_hash, current_response, judge_model, judge_prompt_version)`. Cache hits = free. Stored in `node_modules/.cache/kaji/eval-judge.json`. CLI flag `--no-cache` for verification runs. |

**Clarification on A2's telemetry approach:** the `integration.edited` event is emitted by the SDK's runtime on first `import` per process, not by the CLI. This is technically still phoning-home from imported library code — same opt-in default applies, same `KAJI_TELEMETRY=off` honored, same `DO_NOT_TRACK=1` honored. The opt-in prompt fires from `kaji init` (the only realistic install path); users who skip `kaji init` and `bun add @kaji/sdk` directly get the opt-out default and no events fire. Documented in `privacy.mdx`.

**No P1 architecture findings in pass 4.** Pass 4 surfaces tightening, not blocking. Sub-plans can begin in parallel with these fixes folded into their acceptance criteria.

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|---|---|---|
| 0 — docs site + paradigm + roadmap | `kaji/ts/docs/`, `kaji/ts/README.md` | — |
| 0.5 — telemetry + GTM | `kaji/ts/src/telemetry/`, `kaji/ts/docs/launch/`, CLI mods | 0 |
| 1 — approval handler + EventStore.subscribe | `kaji/ts/src/runtime/approval/`, `kaji/ts/src/sessions/store.ts`, `kaji/ts/src/tools/` | — |
| 1.5 — prod table-stakes (tokens, cancel, rate-limit) | `kaji/ts/src/providers/`, `kaji/ts/src/runtime/cancellation.ts`, `kaji/ts/src/events/schemas.ts` | — |
| 2 — integration template + lint | `kaji/ts/registry/_template/`, `scripts/check-integration.ts` | 0 |
| 2.1-2.4 — Tier 1 integrations | `kaji/ts/registry/<http|fs|web|sqlite>/` | 0, 2-template |
| 2.5-2.8 — Tier 2 integrations | `kaji/ts/registry/<postgres|github|linear|resend>/` | 0, 2-template |
| 2.9-2.10 — Tier 3 (3A/3B/3C decision) | `kaji/ts/registry/<3A or 3B or 3C>/` | 0, 2-template |
| 3 — `kaji new tool` codegen (TS port) | `kaji/ts/src/cli/gen.ts`, `kaji/ts/src/cli/gen/*` | 0 |
| 4 — providers | `kaji/ts/src/providers/`, `kaji/ts/package.json`, `kaji/ts/tsup.config.ts` | 0 |
| 5 — ToolRetriever | `kaji/ts/src/tools/retriever.ts`, `embedder.ts` | 0 |
| 5.5 — `kaji eval` | `kaji/ts/src/cli/eval.ts`, `kaji/ts/src/eval/` | 0, 6a |
| 6a — CLI replay pretty-printer | `kaji/ts/src/cli/replay.ts`, `_replay_render.ts` | 0 |
| 6b — HTML replay viewer | `kaji/ts/replay-viewer/` | 0, 6a |
| 7 — `bun create kaji-agent` + npm publish | `kaji/ts/create-kaji-agent/`, `.github/workflows/publish-create.yml` | 0, 2, 4, 6 |
| 7.5 — `kaji doctor` | `kaji/ts/src/cli/doctor.ts` | 2, 4 |
| 8 — runtime matrix + release smoke | `.github/workflows/` | 4 |
| 9 — MCP server export | `kaji/ts/src/mcp/`, `kaji/ts/src/cli/serve_mcp.ts` | 2 |
| 10 — serve hardening | **separate plan doc** | — |

**Parallel lanes after Sub-Plan 0:**
- Lane A: 1, 2.1-2.4, 6a (independent files)
- Lane B: 2.5-2.8 (Tier 2)
- Lane C: 2.9-2.10 (Tier 3)
- Lane D: 3, 4, 5 (CLI codegen, providers, RAG)
- Lane E: 6b, then 7 (waits on 2, 4, 6)
- Lane F: 8 (waits on 4)
- Lane G: 9 (waits on 2)

**Conflict flags:**
- Sub-Plans 4 and 8 both touch `package.json` and `tsup.config.ts`. Land 4 first.
- Sub-Plans 6a and 6b and 9 all touch `kaji/ts/src/cli/index.ts`. Sequence 6a → 6b → 9 → 7.
- Sub-Plans 2.* all touch `kaji/ts/registry/index.json`. Sequence or rebase carefully.

## Versioning + release plan

**Optimize for speed-to-feedback, not credibility-of-v1.0.0.** CEO outside voice flagged that the prior versioning gated first-user feedback behind weeks of polish. Reordered:

- **rc.0 — 1 week, ship to 3 design partners:** Sub-Plan 0 (docs + paradigm) + Sub-Plan 2.1 (HTTP integration) + existing OpenAIProvider. That's it. No telemetry yet (don't measure before there's anything to measure). No approval handler (hobbyist loop doesn't need it). No replay viewer (`console.log` + raw JSONL is enough for 3 friends). Goal: a hobbyist can run a tool-using agent in 10 minutes and tell us what broke.
- **v1.0.0-rc.1 — 3 weeks:** + 0.5 (telemetry + GTM) + 1 (approval) + 1.5 (prod table-stakes) + 2.2-2.4 (3 more zero-friction integrations) + 3 (`kaji new tool` codegen) + 6a (CLI replay). **Note Sub-Plan 3 (codegen) lands in rc.1, not rc.3.** The codegen path is the wedge-that-survives-if-the-shadcn-built-in-bet-fails; shipping it early means both halves of the wedge are testable from day one.
- **v1.0.0-rc.2 — 5 weeks:** + 2.5-2.8 (Tier 2 vendored integrations) + 4 (Gemini/Kimi providers) + 6b (HTML replay viewer)
- **v1.0.0 — 7 weeks:** + 5 (ToolRetriever) + 5.5 (`kaji eval`) + 7 (`bun create kaji-agent`) + 7.5 (`kaji doctor`) + 8 (runtime matrix) + 9 (MCP server export) + 2.9-2.10 (Tier 3)
- Sub-Plan 10 ships under its own version (`kaji-serve 0.x.0`) independently
- CHANGELOG entries per sub-plan in `kaji/ts/CHANGELOG.md`

**Why rc.0 exists:** the shadcn-analogy bet starts producing signal the moment N=1 ships. The current plan's "rc.1" is 6+ weeks of work before *anyone outside* types `bun add @kaji/sdk`. That's optimizing for the wrong thing. rc.0 is hobbyist-grade, shipped to friends-of-the-builder, with the explicit goal of learning what's broken in the paradigm before the marketable v1.0.0 lands.

**Single-builder pace (CEO pass 4, C1).** The 1/3/5/7-week milestones assume **single-builder + CC**, no parallel-team coordination overhead. Bringing on additional engineers adds +30-50% to a milestone for the first 2 weeks of each new contributor's ramp (kaji-paradigm onboarding, integration template internalization, eval/replay mental model). After ramp, neutral. If a future planner reads "v1.0.0 — 7 weeks" and assumes that's team-pace, they will miss by 30-50% per contributor's ramp window. Single-owner is **intentional through v1** (C5); v1.1 onward, codify owner-per-sub-plan in the roadmap doc.

**rc.0 design-partner gate (CEO pass 4, C2).** If 0 design partners commit by end of rc.0 week, **pause rc.1 work** and run a 3-day customer-discovery sprint instead. The named bet (shadcn-analogy) depends on having users to measure; shipping rc.1 features to nobody burns the calendar with no signal. Better to discover that the target user isn't TS-product-company engineers at week 2 than at week 8.

## Mortality risks (CEO pass 4, C3)

The shadcn-analogy bet is the named bet, with a 3-zone fallback. These are the **other** ways v1 dies that the bet's framework does NOT capture. Each has a watch-signal and a fold (what to do if the signal trips).

| # | Mortality risk | Watch signal | Fold |
|---|---|---|---|
| M1 | **Target user isn't TS-product-company engineers.** It's solo indie hackers who want chat UI + tool-use, don't care about PR-reviewable integrations. | 3 design partners surface zero "I want this for my team's audit story" feedback in rc.0 interviews; instead all 3 say "I just want fewer LOC to build my chat agent." | Reposition: chat-agent-shaped templates in Sub-Plan 7 promoted; integration vendoring repositioned as "for when you're ready to share with your team," not lead feature. |
| M2 | **Codegen output quality bar is unmeetable.** Real-world OpenAPI specs are so under-typed that `tsc --strict` rejects >50% without massive `z.unknown()` placeholders, making generated tools low-quality and pushing users back to hand-writing. | `kaji new tool --report` flag shows >50% of endpoints dropped or schema-tightened with placeholders on Stripe/Shopify/AWS specs. | Pivot Sub-Plan 3 to focus on the smaller set of specs that DO emit cleanly (Linear, Postgres, GitHub) and document codegen as "best-effort starter, hand-edit expected" rather than "primary path." |
| M3 | **Per-provider entry points feel like over-engineering** to the 80% of users on one provider; the tree-shake claim doesn't translate to felt user value. | Telemetry shows >85% of `agent.run` events on a single provider (OpenAI); no user mentions tree-shake savings as a benefit in design-partner interviews. | Demote per-provider entry points from "v1 feature" to "v1 capability, default unified import." Single `import { Provider } from "@kaji/sdk"` becomes the lead snippet in docs. |
| M4 | **`kaji eval` is too expensive in $ to be CI-default** when judge mode requires real LLM calls per golden × per provider. | Design partner pricing math comes out at $10+/CI-run with 50 goldens × 2 providers × judge. | Pivot Sub-Plan 5.5 default to `--judge exact` (deterministic diff); LLM-as-judge becomes opt-in `--judge llm` with documented per-run cost estimate before invocation. Already partially designed; this is a default-flip + per-run cost warning. |

These are not P0 today — they are watch-signals to check post-rc.0 and pre-rc.1. The plan does not predict which (if any) will trip; it surfaces them so the post-rc.0 review has explicit criteria to compare against.

## v1.1 narrative (CEO pass 4, C4)

The "NOT in scope" list has 18 items deferred to v1.1 or v2. One sentence on what v1.1 IS, beyond a grab bag:

> **v1.1 deepens the moat where v1 signal validates the bet** — if shadcn-analogy wins (strong yes zone), ship org-shared integration templates + patch-overlay model; if it returns ambiguous, ship `@kaji/integrations/<name>` importable mode alongside vendored. Unconditional v1.1: OTEL bridge, structured outputs, secret-source backends (Vault/Doppler/AWS), framework adapters (React/Vue/Svelte `useAgent`), and 4 friction-tier integrations (Gmail/Stripe/HubSpot/Calendly). v2 is wholly new: voice modality, langgraph-js parity, vector-DB RAG adapters.

This sentence belongs at the top of `roadmap.mdx` (Sub-Plan 0 task 0.7, **add new task**).

### Task 0.7 (new): Public roadmap MDX with v1.1 narrative
- [ ] **Step 1:** Write `kaji/ts/docs/content/docs/roadmap.mdx` opening with the v1.1 narrative sentence above
- [ ] **Step 2:** Section per release: v1.0.0 (what shipped), v1.1 (what's deepening based on signal — both paths), v2 (what's new)
- [ ] **Step 3:** Link from docs landing footer
- [ ] **Step 4:** Commit on `feat/ts-docs-roadmap`

## Completion summary

- **Paradigm settled:** every tool your agent calls lives as TypeScript in your repo. One sentence, one mental model, contrarian against eve (runtime pointers) and flue (code-execution tool).
- Sub-Plan 0: docs + paradigm + roadmap (load-bearing)
- Sub-Plan 0.5: telemetry (instruments the shadcn-analogy bet from day 1) + GTM scaffolding
- Sub-Plan 1: event-driven approval handler
- Sub-Plan 2: 10 hand-written integrations, vendored on `kaji add`
- Sub-Plan 3: `kaji new tool <url>` codegen, full TS port, same vendored end-state. **The wedge that survives even if the bet on built-ins fails.**
- Sub-Plan 4: Gemini + Kimi + per-provider entry points
- Sub-Plan 5: ToolRetriever only; RAG via MCP-wrapped tools
- Sub-Plan 5.5: `kaji eval` — golden-trace regression testing
- Sub-Plan 6: CLI replay pretty-printer (6a) + HTML viewer (6b)
- Sub-Plan 7: `bun create kaji-agent`
- Sub-Plan 8: runtime matrix + nightly release smoke
- Sub-Plan 9: **MCP server export only** — kaji exposes its tools as MCP; kaji does NOT consume MCP at runtime. External MCP consumption flows through `kaji new tool --mcp` (Sub-Plan 3).
- Sub-Plan 10: serve hardening (separate doc)
- NOT in scope: 13 explicit deferrals to v1.1 or v2
- TODOS.md: 14 items captured
- Failure modes: 1 critical gap (Postgres reconnect)
- Parallelization: 7 lanes, 5 parallel after Sub-Plan 0

## Unresolved decisions

- **Tier 3 integration choice (3A / 3B / 3C):** Slack+Notion vs PDF+CSV vs S3+one-of. Depends on whether a real Ramp-shaped consumer is named.
- **Telemetry backend choice:** PostHog Cloud free tier (default) vs self-hosted vs Plausible vs Cloudflare Worker + D1.
- **Docs site domain:** `kaji.dev`, `ts.kaji.dev`, or `kaji-ts.vercel.app` for v1.
- **Replay HTML viewer embed in docs:** iframe vs React component port, decided at Task 6c.
- **`create-kaji-agent` npm name availability:** confirm no collision before Sub-Plan 7.
- **Sub-Plan 0 Fumadocs reuse path:** new app under `kaji/ts/docs/` (recommended) vs section in existing docs, Task 0.1.
- **GitHub integration rewrite vs leave-alone:** Sub-Plan 2.6 reads existing first.
- **MCP SDK choice:** `@modelcontextprotocol/sdk` from Anthropic (recommended) vs hand-roll types, Sub-Plan 9.
- **Windows support for `bun create kaji-agent`:** v1 commitment vs v1.1.
- **The shadcn-analogy bet:** if `integration.edited / integration.added` (semantic, filtering formatting-only) < 15% within 4 weeks of v1.0.0, pivot to publishing the same files as npm packages. Import shape stays identical; only source-of-truth changes.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 4 | clean | Passes 1-3 accepted shadcn wedge, reframed TS-as-product, settled paradigm; pass 3 added `integration.edited.feedback`, `kaji doctor`, rc.0 milestone, `SecretSource` interface, codegen quality gate. Pass 4 (HOLD SCOPE — no re-litigation): 5 findings folded — C1 (single-builder pace named in timeline), C2 (rc.0 design-partner gate: pause rc.1 if 0 commits in week 1), C3 (4 mortality risks beyond shadcn-bet: target-user-mismatch, codegen-spec-quality, per-provider over-engineering, eval-cost-too-high), C4 (v1.1 narrative sentence + new Task 0.7 for roadmap.mdx), C5 (single-owner-intentional-through-v1 declared). **No P1 findings in pass 4.** |
| Eng Review | `/plan-eng-review` | Architecture & tests | 4 | clean | Passes 1-3: 5 arch + 5 quality + 3 perf + 7 test gaps folded; outside voices added 14, 12 folded, 2 deferred to v1.1. Pass 4: 5 arch (A1-A5) + 2 quality (Q2-Q4) + 3 perf (P1-P3) + 10 test gaps (T-G1 through T-G10) folded as "eng review pass 4 — architecture tightening" section + per-sub-plan acceptance additions; named `@kaji/sdk` publish workflow; clarified `kaji eval` semantics for infra events; documented `MCPServer` + `ToolRetriever` interaction; tightened `kaji doctor` provider fallback; extended `ToolFailure.kind` with `rate_limited`; per-integration test sandboxes; HTML viewer 150KB hard-cap softening; 10K-event parse perf target; hash cache for edit-detection; judge-verdict cache for `kaji eval`. **No P1 in pass 4 — plan is tightening, not blocking.** |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | recommended post-Sub-Plan 0 | docs site is UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | recommended post-Sub-Plan 7 | `bun create` + `kaji doctor` is DX scope |

**CROSS-MODEL (cumulative across all passes):** 4 outside-voice rounds (2 eng + 2 CEO) on prior passes. Pass 4 ran without an additional outside-voice (saturated). Convergence on three architectural truths: (1) the shadcn analogy is the load-bearing bet, must be instrumented from day 1, has a defined fallback; (2) MCP is table stakes (consumed via codegen-snapshot, exported at runtime); (3) production agents need table-stakes plumbing (token accounting, cancellation, rate-limit, security upgrades, auth abstraction) before v1 — all folded into Sub-Plans 1.5 and Sub-Plan 2's `SecretSource` interface. Pass 4 surfaced only tightening (publish workflow, sampling reliability, eval semantics around infra events, test sandbox isolation, perf budgets) — no new architectural truths. The plan has reached the convergence point: more review passes will not find P1s.

**VERDICT:** CEO + ENG CLEARED (4 passes each). The plan is at master-plan depth. No remaining P1s. CEO pass 4 added 4 mortality risks (M1-M4) and an rc.0 design-partner gate — both make the plan more honest, not more scoped. Ready to begin Sub-Plan 0 (docs + paradigm) and Sub-Plan 2.1 (HTTP integration) toward rc.0 in week 1. **Per the writing-plans skill, expand Sub-Plan 0 task-by-task with TDD steps when execution begins** (the current Sub-Plan 0 tasks are scoped but lack failing-test-first code blocks); same incremental expansion applies to each sub-plan as its lane starts. Do not pre-expand all 13 — they will drift. **rc.0 design-partner gate:** if 0 partners commit by end of week 1, pause rc.1, run a 3-day customer-discovery sprint.

**UNRESOLVED DECISIONS:**
- Tier 3 integration choice 3A/3B/3C (Sub-Plan 2.9-2.10)
- Telemetry backend (Sub-Plan 0.5.a)
- Docs site domain (Sub-Plan 0)
- Replay HTML viewer embed shape (Task 6c)
- `create-kaji-agent` npm name availability (Sub-Plan 7)
- Sub-Plan 0 Fumadocs reuse path (Task 0.1)
- GitHub integration rewrite vs leave-alone (Sub-Plan 2.6)
- MCP SDK choice (Sub-Plan 9)
- Windows support commitment for `bun create kaji-agent` (Sub-Plan 7)
- The shadcn-analogy bet — 3-zone decision framework (strong/ambiguous/weak), evaluated 4 weeks post-v1.0.0 with qualitative + quantitative signal, not a fixed threshold
