# Apps

Deployable frontends and user-facing developer tools for the Alloy monorepo.
Reusable TypeScript code belongs in [`packages/`](../packages); Kaji runtime
implementations and contracts belong in [`kaji/`](../kaji).

## Packages

| path                | name         | what it is                                                                                | stack                                                   |
| ------------------- | ------------ | ----------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| [`apps/web`](web)   | `@ryo/web`   | Studio: merchant dashboard for configuring agents, wallets, payment configs, and webhooks | React 19, Vite, TanStack Router, Tailwind v4, shadcn/ui |
| [`apps/docs`](docs) | `@kaji/docs` | Private deployment package for the public Kaji documentation site                         | Next.js, Fumadocs                                       |
| [`apps/cli`](cli)   | `@kaji/cli`  | Published cross-language `kaji` CLI for scaffolding and code generation                   | Bun, TypeScript                                         |

The standalone `@kaji/cli` is a project-level developer tool. The Python
`kaji` package and TypeScript `@kaji/sdk` also ship package-specific CLIs; the
command surfaces are intentionally distinct and documented in
[`docs/kaji/cli.md`](../docs/kaji/cli.md).

## Workspace

These packages are part of the Bun workspace defined at the repository root.
Install all dependencies from the root:

```bash
bun install
```

Then run any package with `--filter`:

```bash
bun --filter @ryo/web dev
bun --filter @kaji/docs dev
bun --filter @kaji/cli dev -- --help
```

## Checks

```bash
bun --filter @kaji/cli format:check
bun --filter @kaji/cli lint
bun --filter @kaji/cli typecheck
bun --filter @kaji/cli test
bun --filter @kaji/cli smoke

bun --filter @kaji/docs format:check
bun --filter @kaji/docs lint
bun --filter @kaji/docs typecheck
bun --filter @kaji/docs build
```

Run a package directly from its directory when iterating on a package-specific
command.

## Further reading

- [`ryo/README.md`](../ryo/README.md) -- Ryo product overview, API routes, data model
- [`kaji/README.md`](../kaji/README.md) -- Kaji SDK concepts and architecture
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) -- repository conventions and check matrix
