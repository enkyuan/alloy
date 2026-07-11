# Kaji CLI And SDK E2E Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this task-by-task. Keep the work sequential unless a task explicitly says it can be split.

**Goal:** Make `apps/cli`, `kaji/sdk`, and `kaji/ts` tell one coherent first-run story: a developer can install a CLI or SDK, scaffold a minimal agent, run the current high-level `turn()` API, generate useful tools from OpenAPI, and understand exactly which setup paths are real versus deferred.

**Architecture:** Keep the existing package boundaries. `apps/cli` remains the cross-language Node CLI. `kaji/sdk` remains the Python SDK plus Python CLI. `kaji/ts` remains the TypeScript SDK plus package-local CLI. Do not merge CLIs, rewrite runtimes, rewrite providers, or add a full MCP server in this plan. Treat `kaji/sdk/src/cli/templates.py` and `kaji/ts/src/cli/init.ts` as the current reference first-run flows, then align `apps/cli` to them.

**Tech Stack:** TypeScript, Commander, Clack, Vitest, tsdown, Node 22+, Bun; Python, pytest, Kaji SDK; OpenAPI JSON/YAML parsing; docs MDX and repo markdown.

**Plan Path:** `docs/superpowers/plans/2026-07-06-kaji-cli-sdk-e2e-trust.md`

## Current Audit Summary

The SDK hardening work has moved `kaji/sdk` and `kaji/ts` toward the right readiness signal: current defaults, high-level `turn()` examples, static checks, and live OpenAI tool-loop proof. The remaining e2e trust gap is the outer setup layer. `apps/cli` still scaffolds stale low-level runtime/event-store examples, its generated OpenAPI tools lag the Python generator, `doctor` is not language/provider aware, and `kaji mcp` writes configuration for a `mcp-server` command that does not exist.

Observed local checks:

```bash
cd apps/cli
bun run test
bun run typecheck
bun run build
node dist/index.js --help
node dist/index.js doctor --json
node dist/index.js init --cwd /private/tmp/kaji-cli-audit-ts-20260706 --lang ts --provider openai --yes --force
node dist/index.js init --cwd /private/tmp/kaji-cli-audit-py-20260706 --lang python --provider openai --yes --force
```

Results:

- `apps/cli` tests passed: 8 files, 18 tests, 1 skipped.
- `apps/cli` typecheck passed.
- `apps/cli` build passed, but emitted a tsdown warning about invalid `define` input.
- `dist/index.js --help` works and lists `init`, `gen`, `info`, `secret`, `upgrade`, `doctor`, and `mcp`.
- `doctor --json` fails when no provider key is present, which is expected, but its checks are TS/Node-centric even when the CLI scaffolds Python.
- Generated TS scaffold uses `EventBus`, `InMemoryEventStore`, manual `SESSION_CREATED`, and `runtime.send("s1", "Hello!")`.
- Generated Python scaffold uses `InMemoryEventBus`, `InMemoryEventStore`, `store.append(UserMessage(...))`, and `runtime.run_turn("s1")`.
- Current Python and TS SDK references use `agent.turn("Say hello.")` or `runtime.turn("Say hello.")`.
- `kaji mcp` currently points MCP configs to `npx -y @kaji/cli mcp-server`, but no `mcp-server` command is registered.

## E2E Design Target

```text
Developer
  |
  v
Install SDK or CLI
  |
  v
kaji init --lang ts|python --provider openai
  |
  v
Generated files
  |-- TypeScript: package.json, tsconfig.json, agent.ts, .env.example
  |-- Python: agent.py, requirements.txt or pyproject guidance, .env.example
  |
  v
AgentBuilder -> provider factory -> build() -> turn("Say hello.")
  |
  v
Optional live proof
  |-- OPENAI_API_KEY set
  |-- KAJI_LIVE_OPENAI_MODEL defaults to gpt-5.4-mini
  v
Real model tool loop readiness tests
```

OpenAPI generation target:

```text
OpenAPI JSON/YAML
  |
  v
Parse path item params + operation params + request body shape
  |
  v
Generated ToolSpec/TOOLS schema
  |
  v
Generated handlers
  |-- path params interpolated
  |-- query params appended
  |-- body excludes path/query params
  |-- HTTP errors surfaced
  v
Compile or syntax smoke
```

Critical invariant: the first scaffolded agent must use the same public SDK surface documented by `kaji/sdk` and `kaji/ts`. The CLI should not teach low-level event-store mechanics as the default getting-started path.

## Global Constraints

- Do not rewrite providers, the agent runtime, service runtime, voice, RAG, integration catalog, or event stores.
- Do not merge `apps/cli`, `kaji/sdk` CLI, and `kaji/ts` CLI into one package.
- Do not implement a full MCP server in this plan unless an existing server implementation is found and can be wired without new architecture.
- Use `gpt-5.4-mini` as the documented first OpenAI live model unless an env override is present.
- Live tests must skip cleanly without provider keys.
- Keep generated scaffolds small and runnable.
- Avoid network-required tests in CI paths.
- Prefer source-level tests over brittle built-dist tests when possible.
- Use GitButler for version-control write operations if available. If `but` is unavailable, do not fall back to git write operations without explicit user approval.

## Strict Work Order

1. Fix `apps/cli init` first because it defines the user-facing setup contract.
2. Port generator parity next because generated tools are the next step after scaffolding.
3. Make MCP setup honest before docs are updated.
4. Tighten `doctor` after init and MCP behavior are settled.
5. Add package/build smoke checks.
6. Update docs and roadmap last so they reflect real behavior.

## Task 1: Align `apps/cli init` With Current SDK First-Run APIs

**Purpose:** The cross-language CLI must scaffold the same beginner-facing API as `kaji/sdk` and `kaji/ts`: `AgentBuilder().provider(...).build()` followed by `turn("Say hello.")`.

**Modify:**

- `apps/cli/src/templates/ts-agent.ts`
- `apps/cli/src/templates/py-agent.ts`
- `apps/cli/src/commands/init.ts`
- `apps/cli/test/commands/init.test.ts`

**Reference but do not rewrite:**

- `kaji/sdk/src/cli/templates.py`
- `kaji/sdk/tests/cli/test_init.py`
- `kaji/ts/src/cli/init.ts`
- `kaji/ts/tests/cli.init.test.ts`

**Implementation requirements:**

- Replace the TS scaffold's low-level event store path with the high-level API.
- Replace the Python scaffold's `store.append(...)` and `run_turn(...)` path with `turn(...)`.
- Keep provider selection for `openai`, `anthropic`, `kimi`, and `gemini`.
- Validate `--lang` and `--provider` explicitly in non-interactive mode. Invalid strings should exit with code `2` and a clear message.
- Generate TS project files that match `kaji/ts/src/cli/init.ts`: `package.json`, `tsconfig.json`, `agent.ts`, `.env.example`.
- Generate Python files that are not a dead end: `agent.py`, `.env.example`, and either `requirements.txt` or a clear next-step line. Prefer `requirements.txt` because it makes the scaffold inspectable without assuming Poetry or uv.
- Keep overwrite behavior unchanged: existing files are not overwritten unless `--force` is passed.
- Print next steps in non-interactive mode after listing written files.

**TS template target:**

```ts
const TS_FACTORIES = {
  openai: "openai",
  anthropic: "anthropic",
  kimi: "kimi",
  gemini: "gemini",
} as const;

const TS_PROVIDER_DEPS = {
  openai: { openai: "^6.42.0" },
  anthropic: { "@anthropic-ai/sdk": "^0.104.1" },
  kimi: { openai: "^6.42.0" },
  gemini: { openai: "^6.42.0" },
} as const;

export function tsAgentTemplate(provider: string): string {
  const factoryName = resolveFactory(provider);
  return `import { AgentBuilder, ${factoryName} } from "@kaji/sdk";

const agent = new AgentBuilder()
  .provider(${factoryName}())
  .systemPrompt("You are a helpful assistant.")
  .build();

const result = await agent.turn("Say hello.");
console.log(result.text);
`;
}
```

**TS package template target:**

```ts
export function tsPackageTemplate(provider: string): string {
  const providerDeps = resolveProviderDeps(provider);
  return JSON.stringify(
    {
      name: "my-kaji-agent",
      version: "0.1.0",
      private: true,
      type: "module",
      scripts: { start: "tsx agent.ts" },
      dependencies: { "@kaji/sdk": "^0.1.0", ...providerDeps },
      devDependencies: { tsx: "^4.0.0", typescript: "^5.4.0" },
    },
    null,
    2,
  ) + "\n";
}
```

**Python template target:**

```ts
export function pyAgentTemplate(provider: string): string {
  return `"""Minimal kaji scaffold."""

from __future__ import annotations

import asyncio
import os

import kaji


async def main() -> None:
    provider_name = os.environ.get("KAJI_MODEL_PROVIDER", ${JSON.stringify(provider)})
    runtime = (
        kaji.AgentBuilder()
        .provider(kaji.get_provider(provider_name))
        .system_prompt("You are a helpful assistant.")
        .build()
    )
    result = await runtime.turn("Say hello.")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
`;
}
```

**Python requirements target:**

```ts
const PYTHON_EXTRAS = {
  openai: "kaji[openai]",
  anthropic: "kaji[anthropic]",
  gemini: "kaji[gemini]",
  kimi: "kaji",
} as const;

export function pyRequirementsTemplate(provider: string): string {
  return `${resolvePythonRequirement(provider)}>=0.1.0\n`;
}
```

**Tests:**

- TS scaffold writes `package.json`, `tsconfig.json`, `agent.ts`, `.env.example`.
- TS `agent.ts` imports the selected factory and contains `.turn("Say hello.")`.
- TS `agent.ts` does not contain `EventBus`, `InMemoryEventStore`, `KajiEvent`, `SESSION_CREATED`, or `runtime.send`.
- TS `package.json` includes the right optional provider package:
  - OpenAI, Kimi, Gemini: `openai`
  - Anthropic: `@anthropic-ai/sdk`
- Python scaffold writes `agent.py`, `.env.example`, and `requirements.txt`.
- Python `agent.py` contains `.turn("Say hello.")`.
- Python `agent.py` does not contain `InMemoryEventBus`, `InMemoryEventStore`, `store.append`, or `run_turn`.
- Invalid `--lang` and invalid `--provider` fail with exit code `2`.
- Existing no-overwrite behavior still passes.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/init.test.ts
bun run typecheck
```

**Checkpoint:** `fix(cli): align init scaffolds with sdk turn api`

## Task 2: Port OpenAPI Generator Parity Into `apps/cli gen`

**Purpose:** `apps/cli gen` is currently path-param-only, while the Python generator already handles query params, operation/path-item params, primitive types, and body filtering. This makes generated tools incomplete for real integrations.

**Modify:**

- `apps/cli/src/commands/gen.ts`
- `apps/cli/test/commands/gen.test.ts`

**Reference:**

- `kaji/sdk/src/cli/gen.py`
- `kaji/sdk/tests/cli/test_gen.py`

**Implementation requirements:**

- Parse path-item-level parameters and operation-level parameters.
- Operation-level params override path-item-level params by `(in, name)`.
- Preserve fallback extraction for `{path}` template params when OpenAPI metadata omits them.
- Support `path` and `query` params in both TS and Python generated handlers.
- Include primitive schema types in generated parameter schemas when available:
  - `string`
  - `integer`
  - `number`
  - `boolean`
- Include descriptions from OpenAPI parameter descriptions when present.
- Required arrays should include required path/query params only.
- For GET/HEAD/OPTIONS, do not emit a request body.
- For write methods, generate body JSON from args excluding path/query params.
- Surface HTTP failures:
  - TS: check `r.ok` and throw an error containing status and response text.
  - Python: call `r.raise_for_status()`.

**Parser shape:**

```ts
interface OpenApiParameter {
  name: string;
  in: "path" | "query" | string;
  required?: boolean;
  description?: string;
  schema?: { type?: string };
}

interface ParamInfo {
  name: string;
  location: "path" | "query";
  required: boolean;
  type: "string" | "integer" | "number" | "boolean";
  description: string;
}

function parseParameters(
  path: string,
  pathItemParams: OpenApiParameter[] | undefined,
  operationParams: OpenApiParameter[] | undefined,
): ParamInfo[] {
  const byKey = new Map<string, ParamInfo>();
  for (const p of [...(pathItemParams ?? []), ...(operationParams ?? [])]) {
    if (p.in !== "path" && p.in !== "query") continue;
    const location = p.in;
    const type = normalizePrimitiveType(p.schema?.type);
    byKey.set(`${location}:${p.name}`, {
      name: p.name,
      location,
      required: location === "path" || p.required === true,
      type,
      description: p.description ?? `${p.name} ${location} parameter`,
    });
  }
  for (const name of extractPathParams(path)) {
    const key = `path:${name}`;
    if (!byKey.has(key)) {
      byKey.set(key, {
        name,
        location: "path",
        required: true,
        type: "string",
        description: `${name} path parameter`,
      });
    }
  }
  return [...byKey.values()];
}
```

**Generated TS handler target:**

```ts
export async function get_pet(args: Record<string, unknown>): Promise<unknown> {
  const url = new URL(`${BASE_URL}/pets/${args.id}`);
  if (args.includeDetails !== undefined) {
    url.searchParams.set("includeDetails", String(args.includeDetails));
  }
  const r = await fetch(url.toString(), {
    method: "GET",
    headers: { Authorization: `Bearer ${API_KEY}` },
  });
  if (!r.ok) {
    throw new Error(`GET ${url.pathname} failed: ${r.status} ${await r.text()}`);
  }
  return r.json();
}
```

**Generated Python handler target:**

```py
async def get_pet(args: dict) -> dict:
    url = f"{BASE_URL}/pets/{args['id']}"
    params = {}
    if args.get("includeDetails") is not None:
        params["includeDetails"] = args["includeDetails"]
    async with httpx.AsyncClient() as c:
        r = await c.request("GET", url, params=params, headers={"Authorization": f"Bearer {API_KEY}"})
        r.raise_for_status()
        return r.json()
```

**Tests:**

- GET path param remains required.
- GET query param is included in ToolSpec/TOOLS schema and emitted through `url.searchParams.set` or Python `params`.
- Path-item-level params merge into operations.
- Operation-level params override path-item params.
- GET output does not contain `body: JSON.stringify`.
- POST output excludes path/query params from body JSON.
- TS generated code includes `if (!r.ok)`.
- Python generated code includes `r.raise_for_status()`.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/gen.test.ts
bun run typecheck
```

**Checkpoint:** `fix(cli): generate complete openapi tool params`

## Task 3: Make MCP Setup Honest

**Purpose:** `kaji mcp` currently writes config for a non-existent `mcp-server` subcommand. That is worse than an unimplemented feature because it creates a broken setup path in user tools.

**Modify:**

- `apps/cli/src/commands/mcp.ts`
- `apps/cli/test/commands/mcp.test.ts`
- `apps/cli/README.md`
- `apps/docs/content/cli.mdx`
- `apps/docs/components/landing/install/mcp-dropdown.tsx`

**Decision:** Do not implement a full MCP server in this plan. Make the command and docs honest. If a server is later built, it should get its own implementation plan and tests.

**Implementation requirements:**

- Remove or gate `MCP_ARGS = ["-y", "@kaji/cli", "mcp-server"]`.
- `kaji mcp` must not write MCP config that points to `mcp-server`.
- The command should exit with a clear unsupported message:

```text
Kaji MCP setup is not shipped in @kaji/cli yet.
Use `kaji gen` to generate tools today. MCP server support is planned separately.
```

- Keep any helper functions only if tests use them or if they will be reused by a future real MCP server.
- Docs should not instruct users to run `npx kaji mcp --cursor`, `--claude-code`, `--open-code`, or `--manual` because those flags do not exist in the current CLI.
- Landing-page install dropdown should either remove MCP entries or label them as "coming soon" without executable commands.

**Tests:**

- `mcp` action does not write any config file.
- Output contains "not shipped" or equivalent clear unsupported phrasing.
- No test fixture or source file under `apps/cli` still contains `mcp-server` except in a negative assertion or migration note.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/mcp.test.ts
rg -n "mcp-server|npx kaji mcp --|--claude-code|--open-code|--manual" apps/cli apps/docs
```

Expected `rg` result after implementation: no executable setup instructions for the unsupported MCP path. If a docs note remains, it must say MCP server support is deferred.

**Checkpoint:** `fix(cli): stop advertising broken mcp setup`

## Task 4: Make `doctor` Language And Provider Aware

**Purpose:** `doctor` should diagnose the scaffold the user actually has, not only a generic TS/Node environment.

**Modify:**

- `apps/cli/src/commands/doctor.ts`
- `apps/cli/test/commands/doctor.test.ts`

**Implementation requirements:**

- Add `--lang <auto|ts|python>` with default `auto`.
- Detect TS projects via `package.json`, `agent.ts`, or `tsconfig.json`.
- Detect Python projects via `agent.py`, `requirements.txt`, or `pyproject.toml`.
- Keep Node >=22 as a hard check for TS or auto-with-TS.
- Add Python version check only when `--lang python` or Python scaffold files are detected. Use `python3 --version` through an injectable runner in tests.
- Check for the selected provider key based on `KAJI_MODEL_PROVIDER` or scaffold default:
  - OpenAI: `OPENAI_API_KEY`
  - Anthropic: `ANTHROPIC_API_KEY`
  - Gemini: `GEMINI_API_KEY`
  - Kimi: `KIMI_API_KEY`
- For TS, check provider package presence:
  - OpenAI, Kimi, Gemini: `openai`
  - Anthropic: `@anthropic-ai/sdk`
- For Python, check `kaji` in `requirements.txt` or `pyproject.toml` when present. Do not require an installed import in tests.
- Distinguish hard and soft checks:
  - Hard: runtime version, SDK dependency, provider key for live run.
  - Soft: `.env.example` presence, optional provider package hints when no package file exists.
- JSON output should include actionable hints while preserving `{ checks, failed }`.

**Type shape:**

```ts
interface Check {
  name: string;
  ok: boolean;
  detail?: string;
  hint?: string;
  severity: "hard" | "soft";
}

interface RunOptions {
  cwd: string;
  env: Record<string, string | undefined>;
  nodeVersion: string;
  lang?: "auto" | "ts" | "python";
  runCommand?: (cmd: string, args: string[]) => { ok: boolean; stdout: string; stderr: string };
}
```

**Tests:**

- Existing TS happy path still passes with `@kaji/sdk` and `OPENAI_API_KEY`.
- Missing provider key fails with a hint naming the expected env var.
- TS Anthropic scaffold without `@anthropic-ai/sdk` reports a provider package check.
- Python scaffold checks `python3 --version` through injected runner.
- Python scaffold does not require `@kaji/*` in `package.json`.
- `.env.example` remains soft.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/doctor.test.ts
bun run typecheck
```

**Checkpoint:** `fix(cli): make doctor diagnose scaffold language`

## Task 5: Add Package And CLI Smoke Checks

**Purpose:** A CLI that builds but has stale package scripts or broken bin output still erodes trust.

**Modify:**

- `apps/cli/package.json`
- `apps/cli/test/parity.test.ts`
- `apps/cli/src/index.ts`
- Optional create: `apps/cli/scripts/smoke.mts`
- Optional create: `apps/cli/test/commands/help.test.ts`

**Implementation requirements:**

- Fix `start` to point at the built file that actually exists: `node ./dist/index.js`.
- Add `prepack`: `bun run build`.
- Add a local smoke script that:
  - builds the package,
  - runs `node dist/index.js --help`,
  - runs `node dist/index.js init --cwd <tmp> --lang ts --provider openai --yes`,
  - confirms the generated TS scaffold contains `turn("Say hello.")`.
- Investigate the tsdown warning about invalid `define` input. Remove local config causing it if present. If it is external/noisy, document it in the task result and keep the build passing.
- Export a source-level program builder or command list from `apps/cli/src/index.ts` so parity tests do not depend on `dist/` existing.

**Index refactor target:**

```ts
export function buildProgram(): Command {
  return new Command()
    .name("kaji")
    .description("The CLI for kaji")
    .version(version)
    .addCommand(init)
    .addCommand(gen)
    .addCommand(info)
    .addCommand(secret)
    .addCommand(upgrade)
    .addCommand(doctor)
    .addCommand(mcp);
}

async function main() {
  await buildProgram().parseAsync(process.argv);
}

if (isDirectRun(import.meta.url, process.argv[1])) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
```

**Tests:**

- Source-level command list includes expected supported commands.
- Parity test no longer silently skips only because `dist/index.js` is missing.
- If Python CLI parity is still checked through Poetry, keep it as optional, but add a non-skipped source-level check for the `apps/cli` command registry.
- Smoke script passes locally.

**Verify:**

```bash
cd apps/cli
bun run test
bun run typecheck
bun run build
node dist/index.js --help
node dist/index.js init --cwd /private/tmp/kaji-cli-smoke --lang ts --provider openai --yes --force
```

**Checkpoint:** `test(cli): add package smoke coverage`

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
.venv/bin/python scripts/check_types.py --output-format concise
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
