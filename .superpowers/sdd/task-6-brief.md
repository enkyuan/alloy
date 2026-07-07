## Task 6: Sync Docs Across CLI, SDK, TS, And Product Pages

**Purpose:** The docs should describe what the code actually proves, especially for setup and optional live tests.

**Modify:**

- `apps/cli/README.md`
- `apps/docs/content/cli.mdx`
- `apps/docs/content/install.mdx`
- `apps/docs/components/landing/install/mcp-dropdown.tsx`
- `docs/MVP.md`
- `docs/ROADMAP.md`
- Optional if cross-links exist: `kaji/sdk/README.md`
- Optional if cross-links exist: `kaji/ts/README.md`

**Implementation requirements:**

- Document the canonical first successful agent path:
  - `kaji init --lang ts --provider openai --yes`
  - `bun install`
  - set `OPENAI_API_KEY`
  - `bun start`
- Document Python scaffold path:
  - `kaji init --lang python --provider openai --yes`
  - install `requirements.txt`
  - set `OPENAI_API_KEY`
  - `python agent.py`
- State that the default first live OpenAI model is `gpt-5.4-mini`, with env overrides available in SDK-specific tests.
- State that live tests are optional and skip without keys.
- Correct any claim that MCP setup is available through `@kaji/cli` unless Task 3 implements a real server.
- Correct landing-page install commands that show flags unsupported by `apps/cli/src/commands/mcp.ts`.
- Keep provider wording honest:
  - TS Gemini and Kimi are OpenAI-compatible factories.
  - Python provider support should be described only where the SDK actually provides it.
- Update roadmap/MVP claims that say CLI parity is complete if the current implementation still has deferred items.

**Tests and checks:**

- Existing docs sync tests still pass:

```bash
cd kaji/sdk
.venv/bin/python -m pytest tests/test_docs_sync.py tests/test_quickstart.py -q

cd ../ts
node_modules/.bin/vitest run examples/minimal-agent/smoke.test.ts
```

- CLI docs should be grep-clean for dead MCP commands:

```bash
rg -n "mcp-server|npx kaji mcp --|--claude-code|--open-code|--manual" apps/cli apps/docs docs
```

**Checkpoint:** `docs(cli): document real first-run setup`

## Full Verification Matrix

Run these before finalizing the implementation:

```bash
cd apps/cli
bun run test
bun run typecheck
bun run build
node dist/index.js --help
node dist/index.js init --cwd /private/tmp/kaji-cli-final-ts --lang ts --provider openai --yes --force
node dist/index.js init --cwd /private/tmp/kaji-cli-final-py --lang python --provider openai --yes --force
node dist/index.js doctor --cwd /private/tmp/kaji-cli-final-ts --json
```

```bash
cd kaji/sdk
.venv/bin/python -m pytest tests/cli/test_init.py tests/cli/test_gen.py tests/test_docs_sync.py tests/test_quickstart.py -q
.venv/bin/python scripts/typecheck_ty.py --output-format concise
```

```bash
cd kaji/ts
node_modules/.bin/vitest run tests/cli.init.test.ts examples/minimal-agent/smoke.test.ts
node_modules/.bin/tsc --noEmit
```

Optional live proof, only with provider keys:

```bash
cd kaji/sdk
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini .venv/bin/python -m pytest -m integration tests/integration/test_openai_agent_tool_loop.py -q

cd ../ts
OPENAI_API_KEY=... KAJI_LIVE_OPENAI_MODEL=gpt-5.4-mini node_modules/.bin/vitest run --config vitest.integration.config.ts tests/integration/openai.agent-tool-loop.test.ts
```

## Failure Modes Registry

| Codepath | Failure Mode | Required Mitigation | Test |
|---|---|---|---|
| `apps/cli init --lang ts` | Scaffold teaches low-level event API and diverges from SDK quickstart | Generate high-level `AgentBuilder` plus `turn()` scaffold | `apps/cli/test/commands/init.test.ts` |
| `apps/cli init --lang python` | Scaffold uses `store.append` and `run_turn` while Python SDK quickstart uses `turn()` | Replace template with current Python CLI pattern | `apps/cli/test/commands/init.test.ts` |
| `apps/cli init --yes` | Invalid language/provider strings reach templates or generate nonsense | Explicit enum validation and exit code `2` | `apps/cli/test/commands/init.test.ts` |
| `apps/cli gen` | Query params and path-item params are dropped | Port parser parity from Python CLI | `apps/cli/test/commands/gen.test.ts` |
| `apps/cli gen` | GET handlers send bodies or write handlers send path/query keys in body | Split path/query/body args | `apps/cli/test/commands/gen.test.ts` |
| `apps/cli mcp` | Writes config for missing `mcp-server` command | Make MCP command/docs explicit that server setup is deferred | `apps/cli/test/commands/mcp.test.ts` and `rg` |
| `apps/cli doctor` | False diagnosis for Python scaffold | Add language-aware checks | `apps/cli/test/commands/doctor.test.ts` |
| Package scripts | `start` points to `dist/index.mjs` while build emits `dist/index.js` | Fix script and add smoke | `apps/cli/package.json` plus smoke |
| Docs | Landing/docs advertise unsupported MCP flags | Remove or mark as deferred | `rg` docs check |

## Not In Scope

- Full MCP server implementation.
- Provider rewrites.
- Runtime architecture changes.
- Durable event/session stores.
- Voice, RAG, or integration catalog parity.
- Publishing pipeline automation beyond local package smoke checks.
- Making `apps/cli` replace the SDK-local CLIs.

## Review Fold-In

### Plan-Tune Review

No declared developer profile or saved tuning preferences were available. The plan follows the user's explicit signal from this thread: complete edge coverage, low question overhead, and implementation specificity. It avoids asking whether to fix obvious setup drift and instead records product/engineering decisions directly.

Changes applied from this review:

- Added explicit invalid `--lang` and `--provider` behavior.
- Added no-key/live-key separation to verification.
- Added docs grep checks for dead MCP commands.
- Kept task order sequential to reduce cross-file churn.

### CEO Review

The product risk is not lack of more features. It is that a developer's first touch can be fake: a scaffold that teaches old APIs, a doctor that diagnoses the wrong environment, or an MCP command that writes broken config. Trust is the product surface here.

Changes applied from this review:

- MCP is treated as an honesty problem, not a feature opportunity. The plan refuses to ship broken config and defers full server work.
- The first successful agent path is the primary acceptance criterion.
- The docs update happens last so it can describe proven behavior rather than aspirational behavior.

### Engineering Review

The highest-risk implementation areas are the generator parser and the init template/package-file changes. They are both testable without network access. The MCP fix must be deliberately scoped to avoid accidentally inventing a server contract.

Changes applied from this review:

- Task 1 is first because downstream docs and doctor checks depend on the scaffold contract.
- Task 2 includes exact parser semantics and failure behavior.
- Task 5 adds source-level command tests so parity does not silently skip when `dist/` or Poetry is unavailable.
- The verification matrix covers `apps/cli`, `kaji/sdk`, and `kaji/ts`.

## Acceptance Criteria

- `apps/cli init --lang ts --provider openai --yes` generates a runnable high-level TS scaffold with `turn("Say hello.")`.
- `apps/cli init --lang python --provider openai --yes` generates a high-level Python scaffold with `turn("Say hello.")`.
- Generated scaffolds no longer mention manual session creation, `store.append`, `runtime.send`, or `run_turn`.
- `apps/cli gen` supports path params, query params, path-item params, primitive schema types, and write-body filtering.
- `kaji mcp` no longer writes config for a missing `mcp-server` command.
- `doctor` gives language/provider-aware checks and actionable hints.
- `apps/cli` package scripts point at real build artifacts and have local smoke coverage.
- Docs no longer advertise unsupported MCP setup commands or stale first-run flows.
- Full non-live verification passes for `apps/cli`, `kaji/sdk`, and `kaji/ts`.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Status | Findings |
|---|---|---|---|---|
| Plan-tune | User explicitly requested `$plan-tune` | Calibrate specificity and question overhead | Applied | No saved profile; optimize for complete edge coverage and direct implementation path |
| CEO review | User explicitly requested `$plan-ceo-review` | Product trust and scope sanity | Applied | Do not fake MCP readiness; first successful agent is the product moment |
| Engineering review | User explicitly requested `$plan-eng-review` | Architecture and test quality | Applied | Keep package boundaries, add source-level tests, isolate generator parser risk |

**Verdict:** Implement as written. The plan closes the e2e setup gap without re-opening SDK runtime architecture or broad provider parity.

NO UNRESOLVED DECISIONS
