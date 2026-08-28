<!-- Planning + review record for the agentOS interop example in this directory.
     Copied from the /autoplan working plan; kept in-repo as the rationale trail. -->
# agentOS × kaji interop — example first, separate package on demand

> Status: exploration + ast-grep verification + /autoplan review (CEO/Eng/DX, dual voices)
> DONE. Decision **D1 = B** (user, 2026-08-05): do NOT integrate agentOS into the core
> published SDK. Ship a version-pinned interop example OUTSIDE the package now; graduate
> to a separately-versioned `@kaji/agentos` package only on demonstrated demand.
>
> **Deliverable 1: SHIPPED** — PR #99 merged to `main` 2026-08-06 (squash `9ead70c8`).
> Deliverable 2 (`@kaji/agentos`): not started, gated on demonstrated demand.
> All API/seam claims verified against real code (kaji @ current main) and the real
> published agentOS v0.2.15 tarballs (extracted .d.ts in scratchpad).
>
> The full three-phase review (6/6/6 consensus, zero disagreements) is retained below
> under `# /autoplan REVIEW` as the rationale trail. The three original "stacked options"
> were the INPUT to that review; this head section is the OUTPUT.

## Context

`kaji` (TS at `kaji/packages/ts`, npm-published, dual ESM/CJS) is a typed agent SDK:
`Integration` (`src/integrations/base.ts:56`) produces `[ToolSpec, ToolHandler]` pairs,
`ToolRegistry` (`src/tools/registry.ts:306`) holds them, `AgentRuntime`
(`src/runtime/runtime.ts:353`) dispatches model tool-calls to handlers via
`ToolPlanner`. Tools carry `risk` (`read|write|external_effect|destructive|admin`,
`registry.ts:36`), `parallel_safe`, `timeout_ms`. **Verified: kaji has no code-execution
sandbox** — a `ToolHandler` runs in-process on the Node host (only `child_process`
uses are keychain/oauth/CLI plumbing).

`agentOS` (rivet-dev/agentos, Apache-2.0, **PREVIEW/API-unstable**) is the inverse: a
cheap isolated VM (V8 isolate + Wasm + a **native sidecar subprocess**) with per-VM
permissions and built-in ACP agents — but no typed tool-registry/spec layer. The two
stack at the `ToolHandler` boundary.

### Hard constraints from the real agentOS v0.2.15 tarballs (these shape everything)
- **Not pure npm.** Needs `@rivet-dev/agentos-core` → native sidecar (~130 MB) +
  `isolated-vm` + `better-sqlite3`. **darwin + linux-gnu, x64/arm64 ONLY. No Windows,
  no musl/Alpine.**
- **ESM-only, Node ≥ 22.** No CJS `require` condition anywhere in agentos dist.
- **Egress is allow-by-default, NOT deny-by-default.** `AgentOsOptions.permissions`
  doc says "Defaults to allowAll." Safe posture requires explicitly passing
  `permissions: { network: "deny" }` (or a `default:"deny"` ruleset). My earlier
  "egress denied by default" claim was WRONG — the adapter must set it.
- **API is namespaced**; flat `vm.exec`/`vm.readFile`/`vm.prompt` are `@deprecated`.
  Boot: `AgentOs.create(options?): Promise<AgentOs>` (static). Exec:
  `vm.process.exec(command, opts?)`. FS: `vm.filesystem.readFile(path) => Uint8Array`,
  `writeFile(path, string|Uint8Array) => void`. Teardown: `vm.dispose(): Promise<void>`
  (NOT `close()`).
- **Bindings API is real & clean:** `binding({description, inputSchema: ZodType,
  execute:(input)=>Promise<out>, timeout?})` and `bindings({name, description,
  bindings: Record})` → in-VM CLI `agentos-{name}`. Wired via `AgentOsOptions.bindings`.
- **Bring-your-own-agent is NOT a runtime call** — it's a packaged `.aospkg` with an
  `agentos-package.json` carrying `agent.acpEntrypoint` (an ACP-over-stdio binary),
  built with `@rivet-dev/agentos-toolchain`, passed via `software:[...]`, selected by
  `sessions.open({ agent })`. This makes Option 2 the heaviest by far.

### Decisive architecture finding (why the gmail template is WRONG for this)
The gmail "copyable registry integration" template carries a large forensic tail:
cross-SDK ABI parity with a **required Python mirror** (`check_integration_abi.py`
spawns both runtimes), a hardcoded `EXPECTED_PACKED_REGISTRY_FILES`
(`tests/package-contract.test.ts`), the `["echo","github","gmail"]` literal
(`tests/manifest-validate.test.ts:156`, ast-grep confirmed), RELEASE_MATRIX markers,
and — critically — `fixed-origin.ts:37,264` hardcodes `integration: "github" | "gmail"`
with an **https origin URL**. agentOS is a **local VM handle, not an HTTP origin**: it
has no `FixedOriginRequester`, needs no `createXRequester`, and can't be given a Python
mirror (native, ESM-only). Forcing it into `registry/` would mean faking all of that.

**Correct home: a shipped subpath export under `src/integrations/`, modeled on
`src/integrations/github.ts` (the `./integrations/github` subpath), NOT a copyable
`registry/` scaffold.** A shipped subpath needs no Python mirror, no ABI json, no
owner-fixtures, no RELEASE_MATRIX/manifest edits. It needs only: a `feature-tiers-v1.json`
`packageSubpaths` block (verified template at that file's `./integrations/github`), a
`tsup.config.ts` entry, a `package.json` exports block, and `public-declarations.test.ts`
alignment. The one deviation from github: **ESM-only export block** (drop `require`),
because agentos-core is ESM-only.

---

# THE PLAN (decided: D1 = B)

## Deliverable 1 — Interop example + doc, OUTSIDE the published package  ✅ SHIPPED

> **Shipped** in PR #99 (`feat/agentos-interop` → `main`, squash `9ead70c8`, merged
> 2026-08-06). Files landed under `kaji/packages/ts/examples/agentos/`: `agentos-integration.ts`,
> `exec-agent.ts`, `README.md`, `package.json`, `tsconfig.json`, `.gitignore` + a one-line
> `kaji/packages/ts/tsconfig.json` exclude. Core package untouched: `examples/` absent from
> `npm pack`; full core suite 1815 passed.
>
> **Two deviations from the plan-as-written, decided during implementation:**
> 1. **No committed `package-lock.json`.** The lockfile was initially committed to pin the
>    resolved tree, but it dragged agentOS's full 415-package transitive graph into the
>    repo — Sourcery flagged 12 findings against it (a `pi` CVE + LGPL/unknown-license
>    transitive deps). Dropped it and gitignored it; the exact pin lives in `package.json`,
>    which is what matters for an example. This also reinforced D1's isolation goal.
> 2. **Permissions set explicitly per category, not just `network:"deny"`.** Live-sidecar
>    testing showed the documented "allow-all" default is unreliable: setting only
>    `network:"deny"` flipped fs/childProcess to deny and `exec` could not even spawn a
>    shell. The example now sets every category (`network:"deny"`, others `"allow"`), which
>    is both runnable and the honest demonstration of the permission model.
>
> All three review-caught correctness requirements were verified against a **live** VM +
> `agentos-core@0.2.15` types: exec `outcome`-branching (a failing `exit 3` surfaced as
> `{outcome:"failed",exit_code:3,error:{...}}`), reframed missing-dep error, explicit
> egress deny. Known quirk documented in the README: successful `exec` returns empty
> `stdout` on the verified sidecar build (agentOS capture-config detail; `outcome`/
> `exit_code`/`error` are correct).

### Original plan for Deliverable 1 (as approved — for reference)

**What:** a runnable, version-pinned example showing agentOS code execution driven by a
kaji `AgentRuntime`, living under `kaji/packages/ts/examples/agentos/` (NOT in `src/`, NOT an
export, NOT in the packed tarball), plus a short doc page. It proves the interop end to
end without touching kaji's package contract, release cadence, or CI gates.

**Why this shape:** kaji is an "infra-free core" (`package.json:4`); agentOS is a preview,
130MB-native, darwin/linux-only, ESM-only dep whose API is already deprecating methods in
v0.2.15. An example captures ~90% of the value at ~0% of the contract risk and is trivially
reversible when the upstream API moves. (Full rationale: `# /autoplan REVIEW` below.)

**Files (new, none shipped in the npm tarball — confirm they land outside `files[]`):**
- `examples/agentos/package.json` — its OWN package.json, `"type":"module"`, pinning
  `@rivet-dev/agentos-core@0.2.15` EXACTLY (not a range — honest snapshot of a moving
  target) and `kaji` via `file:../..` or the published version.
- `examples/agentos/exec-agent.ts` — the example: `AgentOs.create(...)` → a kaji
  `AgentOsIntegration` (defined locally in the example, ~1 file) wired into an
  `AgentBuilder` → run a prompt that calls `exec` → `vm.dispose()`.
- `examples/agentos/README.md` — states platform support (darwin/linux, x64/arm64,
  Node ≥ 22, ESM-only, ~130MB native) in the FIRST paragraph, so unsupported devs get an
  honest 30-second bounce, not a cryptic `npm install` failure.

**Correctness requirements the example MUST satisfy (from the eng review — these are the
real bugs the review caught; the example is where they get proven, cheaply):**
1. **exec mapping.** `vm.process.exec(command, { timeoutMs })` returns a
   `CodeExecutionResult` discriminated union: optional camelCase `exitCode`/`stdout`/
   `stderr`, mandatory `outcome`, `error` on failure, possible truncation. The example's
   adapter MUST branch on `outcome`, surface failures (not report them as success), and
   translate `exitCode → exit_code` for kaji's snake_case result convention. Pass
   `timeoutMs`, not `timeout`. Any assertion of `{stdout:"hi\n", exit_code:0}` is only
   valid AFTER this normalization.
2. **missing-dep error.** The example's integration factory wraps the agentos import in
   try/catch and rethrows a clean message — mirror `src/providers/anthropic.ts:205` /
   `openai.ts:175` — naming the package + supported OS/libc/arch + Node req + install
   command, keeping the original cause.
3. **safe posture is explicit, not claimed.** agentOS egress is allow-by-default. The
   example MUST pass `permissions: { network: "deny" }` explicitly and a bounded fs mount,
   and the README must state exactly what the posture is (mounts, inherited env, egress,
   secrets) rather than calling it "safe-by-default."

## Deliverable 2 — Separate `@kaji/agentos` package  (ONLY on demonstrated demand)

**Graduation gate (all four, else stay at Deliverable 1):** (a) real user demand, (b)
agentOS reaches a stable, non-preview API, (c) CI-supported platforms cover the audience,
(d) a defensible kaji-specific abstraction exists beyond thin exec/read/write wrappers.

**Shape when it graduates:** a separate npm package `@kaji/agentos`, independently
versioned, pinning a tested `@rivet-dev/agentos-core` range as a normal (not optional)
dependency, ESM-only, platform-gated in its own `engines`/`os`/`cpu`. It depends on
`kaji` as a peer. This isolates all preview/native/ESM churn from kaji's core.

**Start with the bindings direction (old "Option 3"), NOT code-exec-in (old "Option 1").**
The bindings wedge — exposing kaji's typed, permission-gated tools + host-held creds to an
agent running *inside* agentOS — is the stronger strategic surface and does not require
putting a code-exec sandbox inside kaji. Its stated dependency on Option 1 was convenience,
not architecture (CEO Codex #3).

**Hard requirement the review surfaced — the bindings adapter is NOT a raw handler call.**
`binding.execute(input)` must route through a host-owned execution facade that runs the
kaji **planner preflight + ToolPolicy approval + ToolExecutionController** (`planner.ts:710,
726`; `ToolRegistry.execute` at `registry.ts:334` does NOT enforce policy). A per-invocation
synthesized `toolCallId` breaks kaji's idempotency ledger (`execution.ts:313`), so
write/destructive tools (gmail send, github create_issue) can double-execute. The facade
must own stable `(sessionId, toolCallId)` identity and a cancellation signal (agentOS
`binding.execute` provides neither — `bindings.d.ts:7`). Until this facade exists, the
bindings path is a security defect, not a thin adapter.

## What we are explicitly NOT doing (and why)
- **NOT** a `kaji/agentos` core subpath export. Breaks the infra-free/dual-format/
  portable contract; hard-fails Windows/Alpine/CJS/non-x64 at install; couples a preview
  dep to the beta release cadence; and as scoped would break `attw`, tsup externalize,
  `package-contract.test.ts:1192`, and `public-declarations.test.ts:48`.
- **NOT** hosting kaji as an agentOS ACP agent (old "Option 2") — deferred until an actual
  ACP-hosting user exists; it's an ACP server + `.aospkg` packaging effort, a product.
- **NOT** adding `@rivet-dev/agentos-core` to the core package's deps (optional, peer, or
  otherwise). It stays entirely in the example's own package.json.

## Verification (for Deliverable 1)
- **Core package untouched — prove it:** `bun run test` (full suite), `bun run build`,
  `bun run typecheck`, `bun run lint:package` (publint/attw), `bun run package:smoke`, and
  `npm pack --dry-run` to confirm `examples/` is NOT in the tarball. None of these should
  change vs `main` — the example lives outside the package boundary. (This is the whole
  point of D1=B: zero core-contract churn.)
- **Example runs (opt-in, darwin/linux only):** from `examples/agentos/`, `npm ci` then
  `node --import tsx exec-agent.ts` (or the pinned runner), asserting the normalized exec
  result after `outcome` branching, then `vm.dispose()`.
- **Honest failure:** on an unsupported platform / without the dep, the example surfaces
  the reframed install error (Deliverable-1 correctness req #2), not a raw MODULE_NOT_FOUND.

---

# REVIEWED INPUT — the three original "stacked options"

> These were the INPUT to the /autoplan review below, not the final recommendation.
> Retained for traceability. The review (6/6/6 consensus) redirected all three to the
> "THE PLAN" section above. Read them as "what was proposed and why it was changed."

## Option 1 — `kaji/agentos` code-execution Integration  (proposed foundation — REDIRECTED)

**What:** a new shipped subpath `kaji/agentos` exporting an
`AgentOsIntegration extends Integration` whose tools delegate to an agentOS `AgentOs` VM handle.
This gives kaji-driven agents the isolated code execution it lacks today. `@rivet-dev/
agentos-core` is an **optional peerDependency** (never a hard dep — it's non-portable).

**Tools (minimal, all namespaced under `agentos`):**
| tool | risk | parallel_safe | maps to |
|---|---|---|---|
| `exec` | `external_effect` | false | `vm.process.exec(command, {cwd,env,timeout})` → `{stdout,stderr,exit_code}` |
| `read_file` | `read` | true | `vm.filesystem.readFile(path)` → decode Uint8Array → `{content}` |
| `write_file` | `external_effect` | false | `vm.filesystem.writeFile(path, content)` → `{}` |

**Files (new, all in `kaji/packages/ts/`):**
- `src/integrations/agentos.ts` — `AgentOsIntegration` (namespace `"agentos"`, `override
  tools()`, `close()` calling `vm.dispose()`), `createAgentOsIntegration(options)` factory
  (`{ vm: AgentOs, ...}` OR `{ create?: AgentOsOptions }` that calls `AgentOs.create`),
  `inspectIntegration()` (Proxy client that throws, mirrors gmail `index.ts:154-165`),
  and a shared `createAgentOsToolBindings(vm)` returning `[ToolSpec,ToolHandler][]`
  (the seam Option 3 reuses). Snake_case args (`exit_code`, `page`-style) per kaji
  convention.
- The agentos-core import is **lazy/dynamic** (`await import("@rivet-dev/agentos-core")`)
  inside the factory so the subpath loads without the native dep present; the
  `Integration` class + specs are import-safe. `inspectIntegration()` must work with NO
  agentos-core installed (specs are static).
**Safe-by-default:** factory defaults `permissions: { network: "deny" }` and a bounded
  fs scope (e.g. `/workspace`), overridable — because agentOS defaults to allowAll.

**Touch points (verified, bounded):**
- `tsup.config.ts` second block (`:27-44`): add `agentos: "src/integrations/agentos.ts"`.
- `package.json` `exports` (`:45-126`): add `"./agentos"` — **ESM-only** (`import` only,
  no `require`), pointing at `./dist/agentos.{js,d.ts}`.
- `package.json` add `optionalDependencies` (or `peerDependencies` + `peerDependenciesMeta:
  {optional}`) `@rivet-dev/agentos-core`; add to `devDependencies` for tests.
- `contracts/feature-tiers-v1.json` `packageSubpaths.typescript`: add `"./agentos"` block,
  `tier: "experimental"`, listing exactly the exported names. (Gates
  `public-declarations.test.ts`.)
- README + `kaji/packages/ts/CHANGELOG.md`: document as experimental. (docs-contract only asserts
  the copyable-catalog phrase; a subpath export is not in that table — verify no
  docs-contract literal needs the new name.)
- NO Python mirror, NO registry/index.json, NO abi-index, NO manifest, NO owner-fixtures,
  NO fixed-origin change, NO smoke_package change (github-centric), NO
  package-contract `EXPECTED_PACKED_REGISTRY_FILES` change (that list is `registry/**`
  only), NO manifest-validate `:156` change.

**Tests (new):** `tests/agentos-registry.test.ts` mirroring gmail's 8-assertion suite via
a `vi.fn` mock agentOS `AgentOs` handle (namespace, arg-mapping, risk flags on `exec`/`write_file`,
non-object result rejection, close→dispose-once, inspectIntegration). No live sidecar in
unit tests. An **opt-in integration test** (`vitest.integration.config.ts`, gated on
darwin/linux + agentos-core present) that boots a real VM and runs `echo hi`.

---

## Option 2 — Host kaji's `AgentRuntime` as a bring-your-own agentOS agent  (HEAVIEST)

**What:** package kaji's ReAct loop as an agentOS agent so the whole kaji agent runs
*inside* an agentOS VM, tools executing in-VM. Verified this is NOT a runtime call: you
ship an `.aospkg` (built by `@rivet-dev/agentos-toolchain`) with an `agentos-package.json`
`agent.acpEntrypoint` — an **ACP-over-stdio** binary — then `software:[kajiPkg]` +
`sessions.open({ agent: "kaji" })`.

**Work required (this is why it's last):**
- A new **ACP server** wrapping `AgentRuntime`: translate ACP session/prompt messages
  ↔ kaji `turn()/send()` (`runtime.ts:985,1031`) and stream kaji events
  (`AGENT_MESSAGE_DELTA` etc.) ↔ ACP updates. Depends on `@agentclientprotocol/sdk@0.16.1`.
- A build/pack step producing the `.aospkg` (new toolchain dep, new CI job).
- Config plumbing: kaji's `principalId`/`ToolExecutionContext` (`runtime/context.ts:26`)
  must be derived from the ACP session identity.
- Tools inside run via Option 1's integration (so Option 2 **depends on Option 1**).

**Recommendation:** design it, but treat as a separate future track (new package
`@kaji/agentos-agent` or an example under `examples/`), NOT part of the initial ship. It
is a product, not an integration.

---

## Option 3 — Expose kaji Integrations as agentOS bindings  (PRODUCT-ON-TOP)

**What:** an adapter turning any kaji `Integration` (github/gmail/…) into agentOS
`bindings`, so agents running *in* agentOS get kaji's typed, permission-gated tools with
host-held credentials. This is the tightest fit: agentOS bindings already ARE
"typed host fn the in-VM agent calls, creds stay on host" — exactly kaji's
`createSharedXToolBindings` shape.

**Adapter (verified signatures both sides):**
- Input: a kaji `Integration` (or raw `[ToolSpec, ToolHandler][]` from
  `integration.tools()`).
- For each `[spec, handler]`: emit a `binding({ description: spec.description,
  inputSchema: &lt;spec.parameters JSON-Schema → ZodType&gt;, execute: (input) =>
  handler(input, ctx) })`. Collection name = `integration.namespace` → in-VM CLI
  `agentos-{namespace}`.
- **Two real gaps to solve in the plan:**
  1. **Schema bridge.** kaji specs carry JSON-Schema (`spec.parameters`); agentOS
     `binding.inputSchema` wants a `ZodType`. Need JSON-Schema→Zod (a small dep like
     `json-schema-to-zod`, or hand-map the closed subset kaji tools use). Ponytail: try
     the closed subset first.
  2. **Context synthesis.** kaji `ToolHandler` needs a full `ToolExecutionContext`
     (principalId/sessionId/idempotencyKey=`${sessionId}:${toolCallId}`/signal/metadata —
     `context.ts:189` throws if malformed). The binding `execute` has only `input`. The
     adapter must synthesize a valid context per invocation (host-side identity + a
     generated toolCallId + an AbortSignal from `binding.timeout`).
- `risk` mapping: `spec.risk`/`parallel_safe` inform which agentOS `permissions` the host
  grants that binding, and whether the binding is marked long/exclusive.

**Files (new):** `src/agentos/bindings.ts` (or a `kaji/agentos` sub-export)
`toAgentOsBindings(integration, { identity })`. Shares the ESM-only subpath machinery
with Option 1. Depends conceptually on Option 1 existing (same subpath + dep).

**Recommendation:** ship after Option 1. It's ~1 adapter file + the schema bridge; the
context-synthesis correctness is the only sharp edge.

---

## (original sequencing / verification / open-questions — SUPERSEDED)
The original plan sequenced Option 1 → 3 → 2 as core-package work and asked whether the
subpath should be optionalDependency vs peerDependency and ESM-only. The review answered
all of it: none of it belongs in the core package. See "THE PLAN" (above) for the decided
verification and "# /autoplan REVIEW" (below) for why. The dep question is moot — the dep
lives only in the example's own package.json (D1) or the separate package (D2).

---

# /autoplan REVIEW

Scope detected: UI = NO, DX = YES (SDK/package/CLI/API developer-facing).
Pipeline: CEO → Eng → DX. Dual voices (Claude subagent + Codex) per phase.

## Phase 1 — CEO Review

**CEO DUAL VOICES — CONSENSUS TABLE**
| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Premises valid? | NO | NO | CONFIRMED (unsound: preview/native/ESM-only dep in a portable published SDK) |
| 2. Right problem to solve? | NO | NO | CONFIRMED (no demand signal in src/docs; scope-boundary, not a gap) |
| 3. Scope calibration correct? | NO | NO | CONFIRMED (core package is the wrong home) |
| 4. Alternatives explored? | NO | NO | CONFIRMED (interop-doc + separate `@kaji/agentos` skipped) |
| 5. Competitive/market risk? | NO | partial | CONFIRMED (preview, single vendor, unsettled race) |
| 6. 6-month trajectory sound? | NO | NO | CONFIRMED (near-certain regret / release coupling) |

**6/6 CONFIRMED, zero disagreements.** Both models independently verified against the
codebase and reached the same verdict: **do NOT ship `kaji/agentos` as a core subpath.**

Evidence both cited: `kaji/packages/ts/package.json:4` self-describes as **"infra-free core"**;
`kaji/README.md:5` "infra-free (no database... or web server required)"; every export
in `package.json:45-126` is dual ESM/CJS; `optionalDependencies` is empty; no user demand
signal for in-VM code execution anywhere in src/docs.

**Both models' recommended path (consensus):**
1. **Interop doc + one version-pinned example, OUTSIDE the published package** — ~90% of
   the value at ~0% of the risk. No package contract, no release coupling, real-sidecar
   proof, measurable adoption.
2. Only on demonstrated demand: a **separate `@kaji/agentos` package**, versioned
   independently, absorbing all the platform/ESM/preview churn.
3. **Never** a core subpath for a preview/native/ESM-only dependency.

**Codex-specific HIGH findings the plan under-weighted:**
- Option 3 (bindings→agentOS) is the *stronger* strategic wedge (it exports kaji's typed
  tools/permissions/creds outward) and its stated dependency on Option 1 is
  "organizational convenience, not architecture." **If anything becomes `@kaji/agentos`,
  start with Option 3, not Option 1.**
- "Bounded fs scope (e.g. `/workspace`), overridable" (plan:94) is **not a policy
  contract** — with egress allow-by-default + arbitrary `exec` + env injection, calling
  it "safe-by-default" is "a future incident report." Must specify mounts, inherited env,
  subprocess limits, secrets, override semantics before any "safe" claim.

**Classification: USER CHALLENGE** (both models agree the user's stated direction —
"build all 3 on top of agentos, integrated into kaji" — should change). Per autoplan,
NOT auto-decided; surfaced at the final gate. User's original direction is the default.

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | CEO | Do not ship as core `kaji` subpath; prefer interop doc/example, then separate `@kaji/agentos` | USER CHALLENGE | P4 DRY / P6 action | Both models 6/6: preview+native+ESM-only dep corrupts an infra-free dual-format published contract; no demand signal | Core subpath (Options 1/3 as planned) |
| 2 | CEO | If a package is ever built, start with Option 3 (bindings-out), not Option 1 | TASTE | P3 pragmatic | Option 3 is the stronger wedge; its dependency on Option 1 is convenience not architecture (Codex #3) | Option 1 first |
| 3 | CEO | Any "safe-by-default" claim requires a real policy contract (mounts/env/egress/secrets/overrides) | MECHANICAL | P1 completeness | Egress allow-by-default + arbitrary exec + env injection; vague `/workspace` line is an incident risk (Codex #4) | Ship the vague claim |

## Phase 3 — Eng Review

**ENG DUAL VOICES — CONSENSUS TABLE**
| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | NO | NO | CONFIRMED (Opt 3 bindings bypass ToolPlanner/ToolPolicy) |
| 2. Test coverage sufficient? | NO | NO | CONFIRMED (the one "runnable proof" asserts a shape the API never returns) |
| 3. Perf risks addressed? | N/A | N/A | not the fault line |
| 4. Security threats covered? | NO | NO | CONFIRMED (write/destructive double-exec + policy/approval bypass) |
| 5. Error paths handled? | NO | NO | CONFIRMED (outcome/error discriminant dropped → failed exec looks like success) |
| 6. Release/build risk manageable? | NO | NO | CONFIRMED (attw + tsup externalize + 2 contract gates all break) |

**6/6 CONFIRMED. The plan's "all touch points verified, bounded" headline is FALSE.**
Both voices verified against the extracted agentos v0.2.15 `.d.ts` and kaji @ main; Codex
ran an esbuild probe to prove the externalization behavior.

**Confirmed defects (both models, file:line):**
1. **CRITICAL — exec shape wrong.** `vm.process.exec` returns `CodeExecutionResult`
   (`language-execution.d.ts:113`): optional camelCase `exitCode` (NOT `exit_code`),
   optional stdout/stderr, mandatory `outcome` discriminant, `error` on failure, possible
   truncation. Options key is `timeoutMs` not `timeout`. The plan's only runnable proof
   (`{stdout:"hi\n", exit_code:0}`) fails on two counts; a failed/timed-out exec would
   silently look like success or `exit_code: undefined`. Fix: adapter must branch on
   `outcome`, translate `exitCode → exit_code`, pass `timeoutMs`.
2. **HIGH — Option 3 bypasses kaji's policy/approval boundary.** `handler(input, ctx)`
   never reaches `ToolPlanner` (`planner.ts:710,726` = where allow/deny + risk approval
   live); `ToolRegistry.execute` (`registry.ts:334`) only validates, doesn't enforce
   policy. Mapping `spec.risk` → agentOS permissions is NOT equivalent to kaji policy.
   Needs a host-owned execution facade running planner preflight + approval +
   `ToolExecutionController`, not a raw handler. My plan called this "the only sharp
   edge" — it is a security hole.
3. **HIGH — synthesized per-call identity breaks idempotency + cancellation.**
   `snapshotToolExecutionContext` (`context.ts:179`) only checks `idempotencyKey ===
   sessionId:toolCallId`; kaji dedups on the stable `(sessionId, toolCallId)` ledger key
   (`execution.ts:313`). A per-invocation random toolCallId makes retries distinct ledger
   entries → write/destructive tools (gmail send, github create_issue) can DOUBLE-EXECUTE.
   Binding `execute(input)` exposes no signal/invocation-id (`bindings.d.ts:7`; `timeout`
   is a number), so a cancellation-aware signal + stable retry identity are underivable
   from the API.
4. **HIGH — tsup externalization: the two dep choices are NOT build-equivalent.** tsup
   auto-externalizes `dependencies`/`peerDependencies` but NOT `optionalDependencies`.
   `optionalDependencies` + a devDep → tsup bundles the ESM/native graph into both
   formats → build failure. Must be **peerDependency + peerDependenciesMeta.optional +
   explicit `external: ["@rivet-dev/agentos-core"]`** in `tsup.config.ts:27`. (Codex
   proved with an esbuild probe.)
5. **HIGH — attw fails CI.** `attw --pack --profile node16` (`package.json:136`,
   `.github/workflows/ts.test.yml:130`) checks both ESM+CJS resolution; an import-only
   subpath has no CJS resolution and fails. Needs the `esm-only` profile / per-entry
   exclusion, or a lint-policy change. My plan said "confirm that's allowed" — it is NOT,
   as-is.
6. **HIGH — the "unchanged" release-gate claim is false.** `package-contract.test.ts:1192`
   is an exact-equality assertion on the sorted subpath key set → adding `./agentos`
   FAILS it. `public-declarations.test.ts:48` requires BOTH `.d.ts` and `.d.cts` per
   non-CLI subpath → a genuinely ESM-only decl build breaks it. `smoke_package.mts`
   enumerates all export targets and isFile()-checks each. Only `manifest-validate:156`
   and `check:integrations` are genuinely untouched (plan correct there).

**Net:** even setting aside the CEO verdict, Option 1 as written does not compile/pass CI,
and Option 3 as written is a security defect. If the work proceeds (in a separate package),
the adapter needs: outcome-branching exec normalization, a real execution facade through
the planner (not raw handlers), stable invocation identity, optional-peer + explicit
external, esm-only attw profile.

| 4 | Eng | exec adapter must branch on `outcome`, map `exitCode→exit_code`, pass `timeoutMs`; fix the test proof | MECHANICAL | P1 completeness | Real return is `CodeExecutionResult` union, not `{stdout,stderr,exit_code}` | Ship the wrong shape |
| 5 | Eng | Option 3 binding must run through a planner-backed execution facade, not raw `handler(input,ctx)` | MECHANICAL | P1 completeness | Raw handler bypasses ToolPolicy/approval + idempotency ledger → double-exec of write/destructive tools | Raw handler (as planned) |
| 6 | Eng | Dep must be peerDependency(optional) + explicit tsup `external`; NOT plain optionalDependency | MECHANICAL | P5 explicit | tsup only auto-externalizes peer/deps; optionalDep gets bundled (esbuild-proven) | "optionalDep OR optional peer" (not equivalent) |
| 7 | Eng | attw needs the `esm-only` profile for `./agentos`; contract gates (`package-contract:1192`, `public-declarations:48`) MUST be edited | MECHANICAL | P1 completeness | node16 profile requires CJS resolution; subpath-set equality + per-subpath `.d.cts` both trip | "unchanged / confirm allowed" |

## Phase 3.5 — DX Review

**DX DUAL VOICES — CONSENSUS TABLE**
| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Getting started < 5 min? | NO | NO | CONFIRMED (15-25 min supported; ∞ hard-fail for Windows/Alpine-musl/CJS/non-x64) |
| 2. API/CLI naming honest? | NO | NO | CONFIRMED (native/preview surface named as sibling of pure infra-free exports) |
| 3. Error messages actionable? | NO | NO | CONFIRMED (bare `await import()` below `anthropic.ts:205`/`openai.ts:175` catch-and-reframe bar) |
| 4. Hello-world valid as proof? | NO | NO | CONFIRMED (asserts wrong exec shape; Opt 3 demo would show an unsafe contract) |
| 5. Upgrade path safe? | NO | NO | CONFIRMED (preview/API-unstable dep coupled to beta release cadence) |
| 6. Best delivery vehicle? | doc>pkg>subpath | doc>pkg>subpath | CONFIRMED (identical ranking, matches CEO) |

**6/6 CONFIRMED. Best-vehicle ranking identical across both DX voices AND the CEO phase.**

**Confirmed DX findings (both models, file:line):**
- **HIGH — error messages below kaji's own bar.** kaji's provider adapters catch a
  missing optional dep and rethrow a clean `ProviderConfigError` naming the fix
  (`anthropic.ts:205`, `openai.ts:175`, typed at `providers/errors.ts:41`). The plan's
  bare `await import("@rivet-dev/agentos-core")` (plan:90) leaks `ERR_MODULE_NOT_FOUND`/
  native-loader/ABI/platform errors. Fix: one try/catch mirroring the adapters, naming
  package + supported OS/libc/arch + Node req + install command, keeping the cause; add
  an `agentos_core_missing` reason to `src/contracts/integration-recovery.ts` so it flows
  through `formatIntegrationError` like every other integration failure.
- **HIGH — dishonest package-surface naming.** `package.json:4` = "Infra-free core"; every
  export is dual-format incl `./openai`, `./integrations/github` (`package.json:45`).
  "experimental" tier (`feature-tiers-v1.json:17`) signals *API churn*, NOT "130MB native
  sidecar, preview, OS/libc/arch-gated, ESM-only." kaji has no vocabulary to label
  non-portable, so a subpath cannot honestly self-describe. `@kaji/agentos` states the
  boundary honestly.
- **HIGH — upgrade path.** Coupling a preview/API-unstable dep (flat API already
  `@deprecated` in v0.2.15) to kaji's published beta cadence traps devs between two
  release trains. Separate `@kaji/agentos` (own semver, pinned agentos range) or a
  version-pinned example is the correct contract.
- **MEDIUM/CRITICAL — TTHW.** Core subpath saves ZERO steps vs a separate package (native
  peer + VM boot are separate either way — Codex step-count), but hard-fails
  Windows/Alpine/CJS/non-x64 at install and lets a successful kaji install be mistaken
  for agentOS compatibility. Achievable < 5 min (supported) + honest 30s bounce
  (unsupported) via a platform-stating doc+example.

**DX best-vehicle verdict (both voices):** ship a corrected, version-pinned interop
example first; graduate to a separately-versioned `@kaji/agentos` only on demonstrated
demand; never a core subpath.

| 8 | DX | Factory dynamic import must catch+reframe (mirror `anthropic.ts:205`) + add `agentos_core_missing` recovery reason | MECHANICAL | P1 completeness | Bare import leaks cryptic MODULE_NOT_FOUND to exactly the excluded devs | Bare `await import()` |
| 9 | DX | Do not name a native/preview surface as a sibling of infra-free exports | USER CHALLENGE | P5 explicit | "experimental" tier can't encode non-portable; corrupts the honest package contract | `kaji/agentos` core subpath |

---

# FINAL GATE — /autoplan Review Complete

## Plan Summary
Three stacked ways to wire agentOS (a preview VM-isolation runtime) into kaji: (1) a
`kaji/agentos` code-exec Integration subpath, (2) hosting kaji's runtime as an agentOS
agent, (3) exposing kaji integrations as agentOS bindings. The engineering seam analysis
is careful and honest, but the delivery decision (core subpath) is wrong.

## Decisions: 9 logged (5 mechanical, 1 taste, 3 user-challenge-tied)

## Review Scores
- **CEO:** 6/6 dimensions confirmed NEGATIVE. Verdict: do not ship as core subpath.
- **CEO voices:** Codex 5 findings (1 crit/3 high/1 med), Claude 5 (2 crit/3 high). Consensus 6/6.
- **Design:** skipped (no UI scope).
- **Eng:** 6/6 confirmed. Plan's "verified, bounded" headline is false; ≥3 hard CI/build
  breaks + 1 security defect. Codex 6 findings (all high), Claude 8 (1 crit/5 high/2 med).
- **DX:** 6/6 confirmed. Best-vehicle ranking (doc > package > subpath) unanimous. Codex 5
  (1 crit/3 high/1 med), Claude 4 (3 high/1 med).

## Cross-Phase Themes (flagged independently in 2+ phases → high-confidence)
1. **"Safe-by-default" is false** — CEO (Codex #4) + Eng (both, policy/egress) + DX (both,
   naming). The `/workspace`/network posture is not a policy contract given allow-by-default
   egress + arbitrary exec + env injection.
2. **Core subpath is the wrong home** — all three phases, both models, every time. Corrupts
   the infra-free / dual-format / portable contract for zero ergonomic gain.
3. **Preview dep + published cadence = churn trap** — CEO (regret) + Eng (already-deprecated
   API) + DX (upgrade path).
4. **The one runnable proof is wrong** — Eng (exec shape) + DX (hello-world can't onboard).

## THE USER CHALLENGE (never auto-decided — your call)
**You said:** build all three options *on top of agentOS, integrated into kaji*, and
refine until no gaps remain.
**Both models, across all three review phases, recommend:** do NOT integrate into the core
published SDK. Ship an interop doc + one version-pinned example OUTSIDE the package first;
graduate to a **separately-versioned `@kaji/agentos`** only on demonstrated demand; never a
core subpath. If a package is ever built, start with **Option 3 (bindings-out)**, not
Option 1 — it's the stronger wedge and its dependency on Option 1 was convenience, not
architecture.
**Why:** kaji's entire brand is "infra-free core" (`package.json:4`); a preview,
darwin/linux-only, 130MB-native, ESM-only dep behind a first-class export breaks that
contract, hard-fails a large share of the audience at install, and couples a stable
published package to an API that is *already deprecating methods* in v0.2.15. Independently,
Option 1 as written does not pass CI (attw, tsup externalize, two contract gates) and
Option 3 as written is a security defect (double-exec of write/destructive tools + policy
bypass).
**What we might be missing:** you may have a specific customer/demo that needs this in-core
now; you may intend kaji to *become* a heavier runtime (dropping the infra-free promise on
purpose); agentOS may be a strategic bet you've already committed to.
**If we're wrong, the cost is:** you delay a first-class integration by one doc+example
cycle. **If we're right and you ship the subpath anyway, the cost is:** a broken package
contract, confused Windows/Alpine/CJS bug reports against kaji, a preview dep forcing
core releases, and a shipped double-execution security defect.

**Your original direction stands unless you explicitly change it.**

## What I recommend
Reframe the deliverable to what both models endorse and what respects kaji's own machinery:
1. **Now:** an interop doc + one exact-version-pinned (`@rivet-dev/agentos-core@0.2.15`)
   example under `examples/` (or a gist), OUTSIDE the published package. Correct the exec
   mapping (branch on `outcome`, `exitCode`, `timeoutMs`). ~90% of the value, ~0% of the
   risk, zero contract-gate churn.
2. **On demand:** a separate `@kaji/agentos` package — start with **Option 3 (bindings)**
   through a planner-backed execution facade (not raw handlers), with a real permission/
   policy contract. Independently versioned.
3. **Option 2** (ACP-hosted kaji agent): only when an actual ACP-hosting user exists.

## Deferred to TODOS.md
- Revisit in-core integration only if (a) demonstrated demand, (b) agentOS reaches a stable
  (non-preview) API, (c) CI-supported platforms cover the audience, (d) a defensible
  kaji-specific abstraction exists beyond thin exec/read/write wrappers.
