# Alloy contributor guidance

Read [`AGENTS.md`](../AGENTS.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md)
before changing code. A nearer `AGENTS.md` takes precedence for its subtree.
Use package READMEs for setup and public API details; do not infer architecture
from historical plans.

## Monorepo map

| Area               | Paths                                 | Responsibility                                                   |
| ------------------ | ------------------------------------- | ---------------------------------------------------------------- |
| Ryo services       | `ryo/api`, `ryo/consumer`, `ryo/auth` | Go APIs and the TypeScript authentication service                |
| Ryo studio         | `apps/web`                            | React/TanStack web application                                   |
| Python SDK         | `kaji`                                | Infra-free `kaji` runtime and public Python package              |
| TypeScript SDK     | `kaji/ts`                             | `kaji-sdk`, kept in contract parity with Python                 |
| Kaji service       | `kaji/serve`                          | Experimental FastAPI REST and Soniox STT edge                    |
| Developer surfaces | `apps/cli`, `apps/docs`               | Standalone CLI/scaffolds and the public documentation site       |
| Shared packages    | `packages/ui`, `packages/shared`      | Reusable UI code and TypeScript configuration                    |
| Shared contracts   | `kaji/contracts`, `docs/kaji`         | Cross-SDK schemas, feature tiers, fixtures, and operating guides |

Start at [`README.md`](../README.md) for the system overview,
[`kaji/README.md`](../kaji/README.md) for runtime concepts, and
[`docs/kaji/README.md`](../docs/kaji/README.md) for the maintained Kaji guide.

## Architecture and compatibility boundaries

- `kaji` and `kaji/ts` are embedded runtimes. Server, worker, database, and
  transport concerns belong in `kaji/serve` unless a shared protocol requires
  an SDK interface.
- `kaji/contracts/feature-tiers-v1.json` defines stable, experimental, and
  deprecated public surfaces. Stable changes require matching Python and
  TypeScript behavior, parity fixtures, packaged contract copies, CLI/docs
  updates, and tests in the same change.
- Integration manifests, schemas, registry entries, generated copies, and tool
  ABIs must remain synchronized. Experimental integrations must stay explicitly
  gated and must not be presented as stable or provider-verified.
- The agent loop is modality-agnostic. Voice is an optional edge; do not make
  the generic runtime or tool system voice-specific.
- Event ordering is defined by persisted sequence, not timestamps. Preserve
  bounded concurrency, deadlines, cancellation, idempotency, and
  commit-before-publish behavior when touching runtime execution.
- `packages/shared` changes affect every direct consumer: `apps/cli`,
  `apps/web`, and `packages/ui`. Verify all three.

## Change discipline

- Keep changes scoped and preserve existing behavior unless the task explicitly
  changes a public contract.
- Reuse the canonical implementation instead of introducing parallel routers,
  error hierarchies, schemas, registries, or compatibility paths.
- Do not invent provider APIs, model names, environment variables, integration
  capabilities, or release evidence. Consult the package source and official
  provider documentation.
- Keep tests beside the behavior they verify. Update public docs and scaffolds
  whenever users would otherwise copy stale code.
- Do not commit generated output or local state such as `dist/`, `.next/`,
  coverage files, Python caches, virtual environments, logs, or `.artifacts/`.

## Tooling and validation

- JavaScript/TypeScript: Bun `1.3.11`, Node.js `22+`; use the package scripts.
- Python: Python `3.11+` with `uv`; use Ruff, `ty`, and pytest.
- Go: Go `1.25+`; use `gofmt`, `go vet`, and `go test -race`.
- Run every row in [`CONTRIBUTING.md`](../CONTRIBUTING.md) that corresponds to a
  changed path. Contract or release changes also require `bun run audit:kaji-beta`.
- CI workflow files use `<area>.<check>.yml`. Keep external actions SHA-pinned,
  token permissions least-privilege, routine jobs bounded and cancellable, and
  path filters symmetric between push and pull request triggers.
- Keep protected Kaji release job IDs, evidence boundaries, permission
  escalation, exact-runtime pins, and fail-closed behavior intact. Repetition in
  protected workflows may be deliberate evidence isolation, not cleanup debt.

## Security

Never put credentials, prompts, tool arguments or results, arbitrary metadata,
raw provider bodies, or private user data in logs, fixtures, issues, or pull
requests. Follow [`SECURITY.md`](../SECURITY.md) for private vulnerability
reports. Ordinary pull requests must not require live provider or publication
credentials.
