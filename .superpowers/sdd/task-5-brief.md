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

