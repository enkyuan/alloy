# Alloy

Alloy is the monorepo for two related projects:

**Ryo** is a platform for small businesses to deploy AI agents that take
orders, answer questions, and collect payments. A merchant configures an agent
via the studio web app; the agent embeds on their site or phone system and
handles the full customer interaction, including payment.

**Kaji** is the embeddable SDK that powers Ryo's agent runtime: an
event-sourced agent loop, toolgen, pluggable LLM providers, and optional voice
edges through `kaji-serve`. Kaji can also be used standalone in any Python or
TypeScript project.

## Repository layout

| path                                 | project      | what it is                                                  | stack                             |
| ------------------------------------ | ------------ | ----------------------------------------------------------- | --------------------------------- |
| [`ryo/api`](ryo/api)                 | Ryo          | REST API: agents, wallets, payment configs, sessions        | Go, PostgreSQL, Redis             |
| [`ryo/consumer`](ryo/consumer)       | Ryo          | Consumer identity, wallet, transaction history              | Go, PostgreSQL                    |
| [`ryo/auth`](ryo/auth)               | Ryo          | Auth service (Better Auth + JWT)                            | Bun, TypeScript                   |
| [`apps/web`](apps/web)               | Ryo          | Studio: configure agents and payment providers              | React, TanStack Router, shadcn/ui |
| [`kaji`](kaji)                       | Kaji         | `kaji`: agent runtime, toolgen, providers                   | Python 3.11+                      |
| [`kaji/serve`](kaji/serve)           | Kaji         | `kaji-serve`: experimental REST + Soniox STT edge           | Python, FastAPI, Soniox           |
| [`kaji/ts`](kaji/ts)                 | Kaji         | `kaji-sdk`: TypeScript runtime                             | TypeScript                        |
| [`apps/cli`](apps/cli)               | Kaji tooling | `@kaji/cli`: cross-language scaffolding and code generation | Bun, TypeScript                   |
| [`apps/docs`](apps/docs)             | Kaji tooling | `@kaji/docs`: public documentation site                     | Next.js, Fumadocs                 |
| [`packages/ui`](packages/ui)         | Shared       | `@kaji/ui`: shared UI and development helpers               | React, TypeScript                 |
| [`packages/shared`](packages/shared) | Shared       | `@kaji/shared`: workspace TypeScript configurations         | TypeScript                        |

Each top-level area has an index: [`apps/README.md`](apps/README.md),
[`packages/README.md`](packages/README.md), [`ryo/README.md`](ryo/README.md), and
[`kaji/README.md`](kaji/README.md). [`docs/README.md`](docs/README.md)
distinguishes maintained guides from historical plans. Package READMEs contain
local setup; the canonical Kaji operating path starts at
[`docs/kaji/README.md`](docs/kaji/README.md), with current release evidence in
[`kaji/RELEASE_MATRIX.md`](kaji/RELEASE_MATRIX.md).

## Architecture

Ryo is built on Kaji. The Go API configures and spawns agents; the Kaji runtime
handles the LLM loop, tool execution, and voice modalities. Payment collection
is a tool the agent calls.

```
   ┌──────────────────────────┐
   │  studio  (apps/web)      │   react + tanstack router
   │  configure agent,        │   better-auth session
   │  connect payment rail    │
   └───────────┬──────────────┘
               │  rest  /v1/agents  /v1/payments  /v1/wallets
               ▼
   ┌──────────────────────────┐
   │  @ryo/api  (go)          │   chi router, pgx, jwt auth
   │  agent · wallet ·        │
   │  payment_config ·        │
   │  session crud            │
   └───────────┬──────────────┘
               │  spawns / configures
               ▼
   ┌──────────────────────────┐
   │  kaji runtime            │   kaji or kaji-sdk
   │  llm loop · toolgen      │   optional serve edge: fastapi + soniox stt
   └──────────────────────────┘
```

## Getting started

**Prerequisites:** Go 1.25+; [Bun](https://bun.sh) >= 1.3 and Node.js >= 22;
Python 3.11+ and [uv](https://docs.astral.sh/uv/); Docker (PostgreSQL + Redis).

```bash
# JavaScript/TypeScript workspace
bun install

# Go API
cd ryo/api
go mod download
go run ./cmd/migrate/main.go up
go run ./cmd/api/main.go

# Studio
bun --filter @ryo/web dev

# Kaji Python SDK
cd kaji && uv sync && uv run pytest
```

For the Kaji reference service, copy the canonical host-side template and let
the pinned dotenvx runner inject it:

```bash
cp .env.example .env
bun run dev:kaji-serve
```

Run JavaScript/TypeScript checks from the root, or target one workspace:

```bash
bun run build
bun run lint
bun run typecheck
bun run format:check

bun --filter @kaji/cli test
bun --filter @kaji/docs typecheck
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for focused checks and repository
conventions. See [`ryo/README.md`](ryo/README.md) for the full Ryo setup, routes,
and environment variables. See
[`docs/kaji/production-beta.md`](docs/kaji/production-beta.md) for the installed
Kaji quickstart and current support boundary.

## License

Source-available under the
[Functional Source License 1.1, ALv2 Future License](LICENSE). It permits
internal commercial use, modification, and redistribution for permitted
purposes, but excludes competing commercial products and services. Each
version becomes Apache-2.0 after two years. FSL is not an OSI-approved
open-source license.
