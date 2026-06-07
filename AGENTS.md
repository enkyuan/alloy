## Learned User Preferences

- During cleanup and refactors, do not intentionally change product behavior, add features, docs, or examples, implement swarm, or rewrite runtime logic unless explicitly asked.
- Consolidate redundant or overlapping modules (e.g. routers vs api, duplicate error helpers) instead of keeping parallel implementations.
- Use CamelCase for public voice-modality adapter types and constants; remove legacy Hermes-style naming when touching that code.
- Prefer deleting or quarantining legacy Milo-era and node-graph agent artifacts over leaving stale structure in the main tree.
- Align tests with current domain naming (`test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`) rather than old `routers_*` patterns.

## Learned Workspace Facts

- Monorepo layout: agentpay services under `agentpay/` (`api`, `consumer`, `auth`); agentkit SDK packages under `agentkit/` (`agentkit/sdk/` — the `agentkit` SDK, `agentkit/serve/` — FastAPI + workers, path-depends on `../sdk`, `agentkit/ts/` — `@agentkit/sdk` TypeScript); web studio under `apps/web/`. Compose infra under `docker/`. Repo-wide JS workspace config (`package.json`, `turbo.json`, `bun.lock`) at the root.
- SDK layout under `agentkit/sdk/agentkit/`: `core/` (infra: redis, db, config, auth, broker, crypto, errors), `types/`, `infra/` (`events/`, `realtime/` redis stream/pub-sub helpers, `observability/`), `modalities/` (`text/`, `voice/` with `voice/tts/` Gemini+OpenAI), `runtime/` (`agents/{messaging,nodes}`, `providers/`, `tools/`, `sessions/`, `workflows/`). The FastAPI `server/` and TaskIQ `workers/` live in `agentkit/serve/` (the `agentkit_serve` package), NOT in the SDK.
- Voice is a modality (STT, TTS, turn detection, interruption); the generic agent runtime (`agents/messaging`, `agents/nodes`) is NOT voice-specific despite past naming.
- Third-party integrations were stripped from the SDK; avoid reintroducing integration routers or services unless explicitly requested.
- Provider errors belong in `agentkit/providers/errors.py`; avoid parallel `service_errors`-style modules.
- Keep generated artifacts out of the repo: ignore and delete `__pycache__/`, `*.pyc`, `logs/`, and common Python tool caches per the root `.gitignore`.
