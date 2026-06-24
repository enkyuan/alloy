# apps

frontend and tooling surfaces for the alloy monorepo. these are not standalone products -- they are the ui and developer-tooling layer on top of the two products in [`kaji/`](../kaji) and [`ryo/`](../ryo).

## packages

| path | name | what it is | stack |
| ---- | ---- | ---------- | ----- |
| [`apps/web`](web) | `@ryo/web` | studio: merchant dashboard for configuring agents, wallets, payment configs, and webhooks | react 19, vite, tanstack router, tailwind v4, shadcn/ui |
| [`apps/docs`](docs) | `@kaji/docs` | public documentation site for kaji | next.js, fumadocs |
| [`apps/cli`](cli) | `@kaji/cli` | `kaji` CLI for scaffolding and codegen | bun, typescript |

## workspace

these packages are part of the bun workspace defined at the repo root. install all dependencies from the root:

```bash
bun install
```

then run any package with `--filter`:

```bash
bun --filter @ryo/web dev
bun --filter @kaji/docs dev
```

or `cd` into the package directory and run directly.

## further reading

- [`ryo/README.md`](../ryo/README.md) -- ryo product overview, api routes, data model
- [`kaji/README.md`](../kaji/README.md) -- kaji SDK concepts and architecture
