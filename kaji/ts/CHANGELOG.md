# Changelog

All notable changes to the `kaji-sdk` TypeScript SDK are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

---

## [0.2.0-beta.6] - 2026-07-26

- Advanced the npm candidate onto the settled benchmark measurement-floor
  protocol while keeping Python publication deferred.
- Bound release, installed-runtime, evidence, provenance, and registry-byte
  verification to the new beta.6 identity.

## [0.2.0-beta.5] - 2026-07-26

- Signed, unpublished attempt superseded before registry publication because
  its tag predated the settled benchmark measurement-floor protocol.
- The npm registry remained untouched; its tag, artifacts, and evidence are
  incident history rather than release proof.

## [0.2.0-beta.4] - 2026-07-26

- Recovered the npm candidate after the immutable beta.3 tag was rejected
  before artifact build or publication.

## [0.2.0-beta.3] - 2026-07-25

- Advanced the current npm candidate, artifact, release, installed-runtime,
  and evidence identities to beta.3 while leaving the Python candidate deferred.

## [0.2.0-beta.2] - 2026-07-23

- Adopted `FSL-1.1-ALv2`, with Apache-2.0 becoming available for each version
  on the second anniversary of that version's first availability.
- Removed ambient Node.js stream namespace requirements from the public CLI approval declarations.
- Bumped current TypeScript package, release, installed-runtime, and evidence identities to beta.2.

## [0.2.0-beta.1] - unreleased pre-beta build

- Added bounded durable tool arguments, fail-closed installed-package proof,
  and supply-chain gates for shared contract version `1.0.0`.
- Added the cross-SDK no-key `kaji init [path]` grammar, exact installed SDK and
  peer versions, mock/OpenAI/Anthropic modes, atomic safe writes, deterministic
  output, and separate npm/Bun TypeScript 5.7/current-6 scaffold proof.
- Replay now fails closed on corrupt JSONL and emits only a redaction-safe
  structural/error projection in human and JSON modes.
- Classified every public export and added canonical CLI, API-parity, testing,
  migration, troubleshooting, trust, and exact-commit TTHW contracts.
- Promotion remains blocked pending same-commit protected runtime-matrix,
  provider, benchmark, soak, signing, provenance, and publication evidence.

## [Unreleased]

### Added

- **`AgentStrategy.allowToolCalls`** — mirrors Python's `AgentStrategy.allow_tool_calls`.
  When `false`, tools are not advertised to the provider and the turn completes
  without executing requested tool calls. Previously
  only `maxToolIterations` was ported; this closes the remaining behavioral gap
  between `runtime.ts` and `runtime.py`.

- **CLI dispatch table** — `kaji` now exposes a real dispatch surface with
  working `--help`. Available subcommands: `add` (existing), `init` (new,
  scaffolds a starter project), `list-integrations` (new, enumerates the
  registry catalog), and `replay` (renders a stored JSONL session log).
  Per-command help works as `kaji <cmd> --help`. The
  binary entry split out of `index.ts` into a dedicated `bin.ts` so tests
  can drive `runCli(argv, opts)` without firing `process.exit`.
- **`cliApprovalHandler`** — default typed approval handler for dev / REPL use.
  It prints tool name, risk, and arguments, reads `y` / `N` on stdin, and
  returns an `ApprovalDecision`. Optional `label` disambiguates concurrent
  agents in the prompt header.
- **`SessionState` approval projection** — `replaySession` now projects the
  three approval events into observable state:
  - `pendingApprovals` (tool_call_ids requested but not yet resolved)
  - `approvedToolCallIds` (host approved)
  - `rejectedToolCallIds` (host rejected)
  The planner already emitted these events; only the read model was missing.

### Changed

- **`package.json` `bin`** — repointed from `./dist/cli/index.js` to
  `./dist/cli/bin.js` so the importable surface and the binary entry are
  distinct artifacts.

### Fixed

- **`kaji replay`** - fails closed with exit 1 on the first corrupt JSONL line
  and never prints raw prompts, tool payloads, metadata, keys, or causes.
- **`calculateCostUsd`** — now rounds to 10 decimal places like Python's
  `calculate_cost_usd`, so cost output is byte-identical across SDKs instead of
  drifting on floating-point noise.
- **`ToolPlanner.executeBatch`** - routes every call through the
  bounded execution controller. Tools are exclusive by default;
  `parallel_safe: true` opts effect-independent calls into the four-wide pool.
  Request-event failures are reported after the remaining prepared calls are
  processed, preserving already-completed sibling outcomes.

### Removed

- **Dead `ApprovalRequest` type** — exported from three places (`runtime/approval/types.ts`,
  `runtime/approval/index.ts`, `index.ts`) but never used as a parameter or
  variable type anywhere; `TypedApprovalHandler.request()` takes `(call, ctx)`
  as separate arguments, not this wrapper.

### Changed (simplification)

- **`withRetry`/`parseRetryAfterMs`** — deduplicated. `OpenAIProvider` and
  `AnthropicProvider` each carried a near-identical ~35-line retry-with-backoff
  implementation; both now call a single `withRetry()` in `providers/base.ts`.
  `RetryOptions` moved from `providers/openai.ts` to `providers/base.ts` for
  the same reason (`AnthropicProvider` was already importing it cross-file),
  while the `kaji-sdk/openai` subpath continues to re-export the type.

### Documentation

- **README export table** — added rows for exports that shipped with no doc
  pointer: `generateText`/`streamText` (one-shot calls without a full
  `AgentRuntime`), `getProvider`/`registerProvider`, the provider factories
  (`openai`, `anthropic`, `kimi`, `gemini`, `openrouter`), `EnvSecretSource`,
  and the structured approval handlers (`TypedApprovalHandler`,
  `EventApprovalHandler`, `AutoApprovalHandler`).
