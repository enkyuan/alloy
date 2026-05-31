## Learned User Preferences

- During cleanup and refactors, do not intentionally change product behavior, add features, docs, or examples, implement swarm, or rewrite runtime logic unless explicitly asked.
- Consolidate redundant or overlapping modules (e.g. routers vs api, duplicate error helpers) instead of keeping parallel implementations.
- Use CamelCase for public voice-modality adapter types and constants; remove legacy Hermes-style naming when touching that code.
- Prefer deleting or quarantining legacy Milo-era and node-graph agent artifacts over leaving stale structure in the main tree.
- Align tests with current domain naming (`test_api_*`, `test_agents_*`, `test_events_*`, `test_providers_*`, `test_tools_*`, `test_sessions_*`, `test_modalities_voice_*`) rather than old `routers_*` patterns.

## Learned Workspace Facts

- The Python FastAPI agent SDK is the ROOT project: the `agentkit` package lives at the repo root (`./agentkit/`), with `pyproject.toml`, `tests/`, `Dockerfile`, and `alembic/` at the root too. It is a developer toolkit, not a product-specific app shell. Client apps live under `apps/`.
- Layout under `./agentkit/`: `server/` (FastAPI app + routes), `core/` (infra: redis, db, config, auth, errors), `agents/` (`messaging/` event bus, `nodes/` reasoning), `events/`, `providers/` (LLM), `sessions/`, `tools/`, `text/` + `voice/` (modalities; `voice/tts/` has Gemini + OpenAI), `workflows/`, `observability/`, `workers/`.
- Voice is a modality (STT, TTS, turn detection, interruption); the generic agent runtime (`agents/messaging`, `agents/nodes`) is NOT voice-specific despite past naming.
- Third-party integrations were stripped from the SDK; avoid reintroducing integration routers or services unless explicitly requested.
- Provider errors belong in `agentkit/providers/errors.py`; avoid parallel `service_errors`-style modules.
- Keep generated artifacts out of the repo: ignore and delete `__pycache__/`, `*.pyc`, `logs/`, and common Python tool caches per the root `.gitignore`.
