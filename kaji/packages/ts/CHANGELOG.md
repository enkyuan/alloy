# Changelog

All notable changes to the `kaji` TypeScript SDK are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

---

## [0.2.0-beta.11] - 2026-08-01

- First candidate carrying the experimental `gmail` registry integration
  (read/list/send, mailbox-scoped) alongside the existing `echo` and `github`
  catalog entries. Cross-SDK ABI and API conformance for `gmail` are asserted
  by the same fixture-driven gates as `github`.
- Cleared the oxlint `src` warnings without behavior change and wired
  `publint` + `attw` into the TypeScript package-lint gate.
- Added a repository-only agentOS interop example under
  `kaji/ts/examples/agentos/`. It is deliberately excluded from the published
  package (`examples/` is not in `files[]`); the shipped tarball contents are
  unchanged by it. agentOS integration is not part of the SDK surface.
- Advanced the npm candidate, installed-runtime, evidence, provenance,
  registry-byte, documentation, and protected-release identities to beta.11.
  Python `0.2.0b1` remains evidence-only and PyPI publication remains deferred.

## [0.2.0-beta.10] - 2026-08-01

- Recovered from immutable beta.9 publish run `30726249929`, which failed
  closed before `npm publish` because npm 11.16 reported setup-node's
  deprecated `always-auth=false` user setting on stderr.
- Removed that single deprecated setup-node entry before the first
  credentialed action while preserving the closed `npm whoami` stdout,
  stderr, identity, timeout, and receipt checks.
- Advanced the npm candidate, installed-runtime, evidence, provenance,
  registry-byte, documentation, and protected-release identities to beta.10.
  Python `0.2.0b1` remains evidence-only and PyPI publication remains deferred.

## [0.2.0-beta.9] - 2026-07-27

- Signed tag `kaji-v0.2.0-beta.9` triggered protected run `30726249929` at
  `9215c8c28b359c94ae8d85f0786fe4b4e7407123`; offline, compatibility,
  performance, onboarding, provider, supply-chain, and registry-preflight
  evidence passed.
- The publisher failed closed with `npm_whoami_output_invalid` before its
  carrier, tag, registry, or `npm publish` steps. npm and PyPI remained absent;
  the tag, artifacts, and receipts are immutable incident history and cannot
  be reused for beta.10.
- Replaced the retired five-participant onboarding policy with deterministic,
  exact-artifact npm and Bun install, scaffold, no-key, Echo lifecycle, cold,
  and warm proof on GitHub-hosted Linux/x64: Node 22 on `ubuntu-22.04` and
  Node 24 on `ubuntu-24.04`.
- Kept the claim scoped to those automated cells; it does not assert
  five-human, macOS/arm64, Windows, or fully offline dependency-installation
  onboarding.
- Kept the `1.20` threshold, five paired samples, three-replica unanimity,
  Python `toolBatch100` measurement floor, separate GitHub-hosted macOS/arm64
  performance and soak receipts, keyed provider proof, artifact binding, and
  every protected approval gate unchanged.
- Bound release, installed-runtime, evidence, provenance, and registry-byte
  verification to the beta.9 identity. Publication remained npm-only;
  Python `0.2.0b1` is evidence-only and PyPI publication remains deferred.

## [0.2.0-beta.8] - 2026-07-27

- Signed tag `kaji-v0.2.0-beta.8` triggered protected run `30296132900` at
  `4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e` passed exact tag and artifact
  verification, compatibility, all three paired replicas and their aggregate,
  and the 30-minute soak.
- It failed closed because `KAJI_TTHW_EVIDENCE_JSON` was empty when the
  protected environment was approved, so five-user TTHW validation did not
  start.
- Provider proof, registry and publisher preflight, and npm publication were
  skipped. npm and PyPI remained absent; the tag, artifacts, and receipts are
  immutable incident history and cannot be reused for beta.9.
- Obsolete same-commit rehearsal `30291287818` is terminal cancelled and
  cannot be reused as beta.9 evidence.

## [0.2.0-beta.7] - 2026-07-26

- Signed protected run `30265105639` at
  `45bde8630154c61a97986f220a0df08d5ba6240b` passed all three raw paired
  replicas and the 30-minute soak.
- It failed closed when Python `toolBatch100` produced replica duration ratios
  `0.9805314383`, `0.9756823917`, and `1.2290586651`; the mixed aggregate was
  inconclusive.
- TTHW, provider proof, publisher preflight, and npm publication were skipped.
  npm and PyPI remained absent; the tag, artifacts, and receipts are immutable
  incident history and cannot be reused for beta.8.

## [0.2.0-beta.6] - 2026-07-26

- Advanced the npm candidate onto the settled benchmark measurement-floor
  protocol while keeping Python publication deferred.
- Protected run `30230234051` failed closed when TypeScript
  `crossSessionCommit100` produced one above-threshold and two passing replica
  medians. The mixed result was inconclusive, not release evidence.
- The npm registry remained untouched; the tag, artifacts, and receipts are
  immutable incident history and cannot be reused for beta.7.

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

- Experimental `gmail` registry integration with three tools: `list_messages`,
  `get_message` (base64url MIME decode, bounded), and `send_message` (an
  external-effect write guarded by the `gmail_mutation_unknown` recovery path).
  Copy it into your project with `kaji add gmail --allow-experimental`; scopes
  are `gmail.readonly` and `gmail.send`.
- `list_messages` pagination: pass `page_token` from a prior result's
  `next_page_token` to page through a mailbox.
- A shared `gmail-api-conformance-v1.json` fixture drives both the TypeScript
  and Python Gmail clients, enforcing identical normalization across the two
  SDKs (the same mechanism that guards `github`).
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

- Gmail Python normalizers now classify a malformed provider-returned message id
  as a transient read (retryable), matching the TypeScript client, instead of a
  non-retryable policy rejection.
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
  while the `kaji/openai` subpath continues to re-export the type.

### Documentation

- **README export table** — added rows for exports that shipped with no doc
  pointer: `generateText`/`streamText` (one-shot calls without a full
  `AgentRuntime`), `getProvider`/`registerProvider`, the provider factories
  (`openai`, `anthropic`, `kimi`, `gemini`, `openrouter`), `EnvSecretSource`,
  and the structured approval handlers (`TypedApprovalHandler`,
  `EventApprovalHandler`, `AutoApprovalHandler`).
