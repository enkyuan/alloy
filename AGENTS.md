## Learned User Preferences

- During cleanup and refactors, do not intentionally change product behavior, add features, docs, or examples, implement swarm, or rewrite runtime logic unless explicitly asked.
- Consolidate redundant or overlapping modules (e.g. routers vs api, duplicate error helpers) instead of keeping parallel implementations.
- Use CamelCase for public voice-modality adapter types and constants; remove legacy Hermes-style naming when touching that code.
- Prefer deleting or quarantining legacy Milo-era and node-graph agent artifacts over leaving stale structure in the main tree.
- Align tests with current domain naming (`test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`) rather than old `routers_*` patterns.

## Learned Workspace Facts

- Monorepo layout: ryo services under `ryo/` (`api`, `consumer`, `auth`); the Python `kaji` package at `kaji/packages/py/`, `kaji-serve` at `kaji/packages/serve/`, and the TypeScript `kaji` package at `kaji/packages/ts/`; web studio under `apps/web/`. The Python SDK and serve form a `uv` workspace rooted at the repo root. Compose infra under `docker/`. Repo-wide JS workspace config (`package.json`, `turbo.json`, `bun.lock`) at the root.
- Python SDK layout under `kaji/packages/py/src/`: `core/`, `contracts/`, `infra/` (`events/`, `realtime/`, `observability/`), `integrations/`, `knowledge/`, `modalities/`, and `runtime/` (`agents/`, `providers/`, `tools/`, `sessions/`, `workflows/`). The FastAPI `server/` and TaskIQ `workers/` live in `kaji/packages/serve/` (the `kaji_serve` package), NOT in the SDK.
- Voice is a modality (STT, TTS, turn detection, interruption); the generic agent runtime (`agents/messaging`, `agents/nodes`) is NOT voice-specific despite past naming.
- Bundled integrations are manifest-driven under `kaji/packages/py/src/integrations/registry/` and `kaji/packages/ts/registry/`; avoid reintroducing integration routers or services unless explicitly requested.
- Provider errors belong in `kaji/packages/py/src/runtime/providers/errors.py` and `kaji/packages/ts/src/providers/errors.ts`; avoid parallel `service_errors`-style modules.
- Keep generated artifacts out of the repo: ignore and delete `__pycache__/`, `*.pyc`, `logs/`, and common Python tool caches per the root `.gitignore`.
