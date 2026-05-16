## Learned User Preferences

- During cleanup and refactors, do not intentionally change product behavior, add features, docs, or examples, implement swarm, or rewrite runtime logic unless explicitly asked.
- Consolidate redundant or overlapping modules (e.g. routers vs api, duplicate error helpers) instead of keeping parallel implementations.
- Use CamelCase for public voice-modality adapter types and constants; remove legacy Hermes-style naming when touching that code.
- Prefer deleting or quarantining legacy Milo-era and node-graph agent artifacts over leaving stale structure in the main tree.
- Align tests with current domain naming (`test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`) rather than old `routers_*` patterns.

## Learned Workspace Facts

- The Python FastAPI agent SDK lives at `apps/sdk` (import package `src`); it was renamed from `apps/api` and is meant as a developer toolkit, not a product-specific app shell.
- Target layout under `apps/sdk/src/`: `api/`, `core/`, `agents/`, `events/`, `providers/`, `sessions/`, `tools/`, `memory/`, `modalities/` (text + voice), `workflows/`, `observability/`, `models/`, `schemas/`, `workers/`.
- Voice is a modality (STT, TTS, turn detection, interruption); generic agent runtime must not live under `modalities/voice`.
- Third-party integrations were stripped from the SDK; avoid reintroducing integration routers or services unless explicitly requested.
- Remove legacy product branding (`milo`, `hermes`, old `modal` references) from code and Docker config when encountered.
- Provider errors belong in `src/providers/errors.py`; avoid parallel `service_errors`-style modules.
- Keep generated artifacts out of the repo: ignore and delete `__pycache__/`, `*.pyc`, `logs/`, and common Python tool caches per `apps/sdk/.gitignore`.
