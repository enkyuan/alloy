# alloy

this repository contains two related projects:

**agentpay** is a platform for small businesses to deploy ai agents that take
orders, answer questions, and collect payments. a merchant configures an agent
via the studio web app; the agent embeds on their site or phone system and
handles the full customer interaction, including payment.

**agentkit** is the embeddable sdk that powers agentpay's agent runtime: an
event-sourced agent loop, toolgen, pluggable llm providers, and stt/tts
modalities. agentkit can also be used standalone in any python or typescript
project.

## repository layout

| path | project | what it is | stack |
| ---------------------------------- | ---------- | ------------------------------------------------- | ------------------------------- |
| [`apps/api`](apps/api) | agentpay | rest api: agents, wallets, payment configs, sessions | go, postgresql, redis |
| [`apps/web`](apps/web) | agentpay | studio: configure agents, connect payment providers | react, tanstack router, shadcn |
| [`packages/sdk`](packages/sdk) | agentkit | `agentkit`: agent runtime, toolgen, providers | python 3.11 |
| [`packages/serve`](packages/serve) | agentkit | `agentkit-serve`: fastapi server + workers | python 3.11, fastapi, taskiq |
| [`packages/ts`](packages/ts) | agentkit | `@agentkit/sdk`: typescript runtime port | typescript |

each package has its own readme with setup instructions and architecture
details.

## architecture

agentpay is built on agentkit. the go api configures and spawns agents; the
agentkit runtime handles the actual llm loop, tool execution, and voice
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
   │  @agentpay/api  (go)     │   chi router, pgx, jwt auth
   │  agent · wallet ·        │
   │  payment_config ·        │
   │  session crud            │
   └───────────┬──────────────┘
               │  spawns / configures
               ▼
   ┌──────────────────────────┐
   │  agentkit runtime        │   packages/sdk + packages/serve
   │  llm loop · toolgen      │   fastapi, redis, postgres
   │  stt/tts (voice)         │
   └──────────────────────────┘
```

## getting started

**prerequisites:** go 1.25+; [bun](https://bun.sh) ≥ 1.3 and node ≥ 22;
python 3.11+ and [poetry](https://python-poetry.org/); docker (postgres + redis).

```bash
# js/ts workspace (studio + packages/ts)
bun install

# go api
cd apps/api
go mod download
go run ./cmd/migrate/main.go up
go run ./cmd/api/main.go

# studio
bun --filter @agentpay/web dev

# agentkit python sdk
cd packages/sdk && poetry install && poetry run pytest
```

see [`apps/api/readme.md`](apps/api/readme.md) for the full api setup and environment variables.