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

