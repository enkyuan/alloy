# alloy

this repository contains two related projects:

**ryo** is a platform for small businesses to deploy ai agents that take
orders, answer questions, and collect payments. a merchant configures an agent
via the studio web app; the agent embeds on their site or phone system and
handles the full customer interaction, including payment.

**kaji** is the embeddable sdk that powers ryo's agent runtime: an
event-sourced agent loop, toolgen, pluggable llm providers, and optional voice
edges through `kaji-serve`. kaji can also be used standalone in any
python or typescript project.

## repository layout

| path | project | what it is | stack |
| ---------------------------------- | ---------- | ------------------------------------------------- | ------------------------------- |
| [`ryo/api`](ryo/api) | ryo | rest api: agents, wallets, payment configs, sessions | go, postgresql, redis |
| [`ryo/consumer`](ryo/consumer) | ryo | consumer identity, wallet, transaction history | go, postgresql |
| [`ryo/auth`](ryo/auth) | ryo | auth service (better-auth + jwt) | bun, typescript |
| [`apps/web`](apps/web) | ryo | studio: configure agents, connect payment providers | react, tanstack router, shadcn |
| [`kaji/sdk`](kaji/sdk) | kaji | `kaji`: agent runtime, toolgen, providers | python 3.11 |
| [`kaji/serve`](kaji/serve) | kaji | `kaji-serve`: fastapi server + workers | python 3.11, fastapi, taskiq |
| [`kaji/ts`](kaji/ts) | kaji | `@kaji/sdk`: typescript runtime port | typescript |

each package has its own readme with setup instructions and architecture details.
the canonical kaji operating path starts at [`docs/kaji/README.md`](docs/kaji/README.md),
with current release evidence in [`kaji/RELEASE_MATRIX.md`](kaji/RELEASE_MATRIX.md).

## architecture

ryo is built on kaji. the go api configures and spawns agents; the
kaji runtime handles the actual llm loop, tool execution, and voice
modalities. payment collection is a tool the agent calls.

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
   │  kaji runtime            │   kaji/sdk + kaji/serve
   │  llm loop · toolgen      │   serve adds fastapi, redis, postgres, voice
   └──────────────────────────┘
```

## getting started

**prerequisites:** go 1.25+; [bun](https://bun.sh) ≥ 1.3 and node ≥ 22;
python 3.11+ and [uv](https://docs.astral.sh/uv/); docker (postgres + redis).

```bash
# js/ts workspace (studio + kaji/ts)
bun install

# go api
cd ryo/api
go mod download
go run ./cmd/migrate/main.go up
go run ./cmd/api/main.go

# studio
bun --filter @ryo/web dev

# kaji python sdk
cd kaji/sdk && uv sync && uv run pytest
```

see [`ryo/README.md`](ryo/README.md) for the full ryo setup, routes, and environment variables.
see [`kaji/README.md`](kaji/README.md) for kaji concepts, architecture, and package overview.
see [`docs/MVP.md`](docs/MVP.md) for the five-step kaji developer path (install → configure provider → register tools → run agent → inspect events).

## license

source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). the source is public and contributions are welcome, but commercial use and redistribution are not permitted. this is not an OSI-approved open-source license.
