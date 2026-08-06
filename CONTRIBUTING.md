# Contributing

Thank you for improving Alloy. Keep changes scoped to one product or shared
contract where possible, and run the checks owned by the directories you
touch.

## Set up the workspace

From the repository root:

```bash
bun install
uv sync
```

Kaji Python is now a `uv` workspace -- run `uv sync` at the repo root, and
select members with `--package kaji-sdk` / `--package kaji-serve`.

Go services manage dependencies through the `go.mod` in each service. Copy an
`.env.example` only for a service you intend to run; ordinary SDK tests do not
need live credentials. The root workspace pins dotenvx for Kaji development
commands and generated TypeScript starters.

## Find the right package

| Area                       | Paths                            | Guide                                        |
| -------------------------- | -------------------------------- | -------------------------------------------- |
| Ryo services and studio    | `ryo/*`, `apps/web`              | [`ryo/README.md`](ryo/README.md)             |
| Kaji SDKs and service      | `kaji/packages/{python,typescript,serve}` | [`kaji/README.md`](kaji/README.md)  |
| Kaji CLI and docs site     | `apps/cli`, `apps/docs`          | [`apps/README.md`](apps/README.md)           |
| Shared TypeScript packages | `packages/ui`, `packages/shared` | [`packages/README.md`](packages/README.md)   |
| Kaji release contracts     | `kaji/contracts`, `docs/kaji`    | [`docs/kaji/README.md`](docs/kaji/README.md) |

## Local checks

Run the narrow package checks during development. Before opening a pull
request, run every row that corresponds to a changed path.

| Changed area                           | Commands                                                                                                                                                                |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/cli`                             | `bun --filter @kaji/cli format:check && bun --filter @kaji/cli lint && bun --filter @kaji/cli typecheck && bun --filter @kaji/cli test && bun --filter @kaji/cli smoke` |
| `apps/docs`                            | `bun --filter @kaji/docs format:check && bun --filter @kaji/docs lint && bun --filter @kaji/docs typecheck && bun --filter @kaji/docs build`                            |
| `kaji/packages/typescript`             | `bun --filter kaji-sdk format:check && bun --filter kaji-sdk lint && bun --filter kaji-sdk typecheck && bun --filter kaji-sdk test`                                     |
| `kaji/packages/python`                 | `uv run --package kaji-sdk ruff format --check . && uv run --package kaji-sdk ruff check src tests && uv run --package kaji-sdk ty check && uv run --package kaji-sdk pytest -m "not integration"` |
| `kaji/packages/serve`                  | `uv run --package kaji-serve ruff format --check . && uv run --package kaji-serve ruff check src tests alembic && uv run --package kaji-serve pytest`                   |
| `packages/ui`                          | `bun --filter @kaji/ui format:check && bun --filter @kaji/ui typecheck`                                                                                                 |
| `packages/shared`                      | `bun --filter @kaji/shared format:check`, then typecheck `apps/web`, `apps/cli`, and `packages/ui`                                                                      |
| `ryo/api` or `ryo/consumer`            | Run `gofmt -l .` (expect no output), then `go vet ./...` and `go test ./... -race -count=1` from that service directory                                                 |
| Other JavaScript/TypeScript workspaces | `bun run format:check && bun run lint && bun run typecheck`                                                                                                             |

For a Kaji contract or release change, also run the clean local checkpoint:

```bash
bun run audit:kaji-beta
```

Do not use live keys in ordinary pull requests. Provider, publication,
signature, provenance, soak, and calibrated benchmark actions belong to the
protected release operator workflow.

## Compatibility boundaries

`kaji/contracts/feature-tiers-v1.json` is the authority for stable,
experimental, and deprecated features and exports. Stable contract changes
need cross-SDK fixtures and both consumers in the same change. Experimental
work must remain explicitly quarantined. Deprecated compatibility paths need a
documented replacement and removal horizon.

Keep prompts, tool arguments/results, metadata, credentials, and raw provider
causes out of fixtures, logs, issues, and review descriptions.

## Repository conventions

- Use the existing `@kaji/*` and `@ryo/*` package scopes. Put deployable apps
  and developer surfaces in `apps/`, reusable TypeScript code in `packages/`,
  and Kaji runtime packages and contracts in `kaji/`.
- Use lowercase kebab-case for maintained topic documentation and
  `<area>.<check>.yml` for workflow filenames. Standard community files such as
  `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `SUPPORT.md` remain
  uppercase. Do not rename point-in-time plans or compatibility redirects just
  to enforce style retroactively.
- Keep protected workflow job IDs stable. Branch protection and release tests
  consume those IDs even when the display name changes.
- Keep tests with the behavior they verify. A shared stable contract change
  must update Python, TypeScript, fixtures, generated contract copies, and
  public documentation together.
- Do not commit generated output or local state such as `dist/`, `.next/`,
  coverage data, Python caches, virtual environments, or `.artifacts/`.

Use conventional commit subjects in the form `type(scope): summary`. Pull
requests should state what changed, why, which compatibility boundary is
affected, and the exact commands used to verify it.
