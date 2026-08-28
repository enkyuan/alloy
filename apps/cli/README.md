# `@kaji/cli`

Cross-language scaffolding, OpenAPI tool generation, and diagnostics for Kaji
projects. The Python and TypeScript SDKs also ship smaller package-local CLIs;
use this standalone package when one command needs to work with either language.

## Availability

`@kaji/cli` is not published yet. From the monorepo, install workspace
dependencies and run the source directly:

```bash
bun install
bun run --cwd apps/cli dev -- --help
```

If this package is published later, invoke it explicitly when `kaji` is
installed too, because both packages expose a binary named `kaji`.

## First run

The no-key mock provider is the default in non-interactive mode:

```bash
bun run --cwd apps/cli dev -- init --cwd "$PWD/my-agent" --lang ts --yes
cd ./my-agent
bun install
bun start
```

Python uses the same output contract:

```bash
bun run --cwd apps/cli dev -- init --cwd "$PWD/my-agent" --lang python --yes
cd ./my-agent
python -m pip install -r requirements.txt
python agent.py
```

Both scaffolds print deterministic `text`, `turn_id`, and `final_sequence`
fields. Select `--provider openai` or `--provider anthropic` for a live model
and copy `.env.example` to `.env` before setting the generated credential. The
TypeScript scaffold's `start` command loads it with its pinned dotenvx
dependency. The beta scaffold intentionally supports `mock`, `openai`, and
`anthropic`; other SDK provider adapters remain outside this first-run contract.

## Commands

- `kaji init` -- scaffold a TypeScript or Python agent.
- `kaji gen --spec <path> --out <dir>` -- generate typed tool stubs from an OpenAPI JSON or YAML document.
- `kaji doctor` -- verify runtimes, SDK packages, required peers, and selected-provider credentials.
- `kaji info` -- report the local environment and installed Kaji packages.
- `kaji secret` -- generate a random 32-byte hexadecimal secret.
- `kaji upgrade` -- upgrade installed `@kaji/*` packages.
- `kaji mcp` -- report MCP availability; it does not write configuration or install a server.

Run any command with `--help` for its exact flags.

## Contributing

Install dependencies from the monorepo root, then run the package checks:

```bash
bun --cwd apps/cli run format:check
bun --cwd apps/cli run lint
bun --cwd apps/cli run typecheck
bun --cwd apps/cli run test
bun --cwd apps/cli run smoke
```

Keep generated scaffolds aligned with the public `kaji` and `kaji`
quickstarts. Add regression coverage whenever a command, provider choice,
generated dependency, or output field changes.
