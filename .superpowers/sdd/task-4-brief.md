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

