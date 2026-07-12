# Changelog

All notable changes to the `@kaji/sdk` TypeScript SDK are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

---

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

- **CLI dispatch table** — `kaji` now exposes a real dispatch surface with
  working `--help`. Available subcommands: `add` (existing), `init` (new,
  scaffolds a starter project), `list-integrations` (new, enumerates the
  registry catalog). Per-command help works as `kaji <cmd> --help`. The
  binary entry split out of `index.ts` into a dedicated `bin.ts` so tests
  can drive `runCli(argv, opts)` without firing `process.exit`.
- **`cliApprovalHandler`** — default approval handler for dev / REPL use.
  Factory returning an `ApprovalHandler` that matches the planner's
  `(name, args, risk)` signature; prints tool name, risk, and arguments,
  then reads `y` / `N` on stdin. Optional `label` field disambiguates
  concurrent agents in the prompt header. Production hosts should still
  implement their own `ApprovalHandler` (web modal, Slack, etc.).
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
