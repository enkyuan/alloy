# kaji-serve

The FastAPI + workers reference service for the [Kaji SDK](../sdk/README.md).

Wraps `kaji` as a deployable real-time service (REST + voice WebSocket, an
LLM reasoning worker, and async tool workers over Redis). Install it when you
want to run the service; for embedding the SDK in your own app, use `kaji`
directly.

Status: reference implementation, not a production durability layer by itself.
Redis handles process hand-off, and Postgres stores session-list metadata.
Durable event replay requires a persistent `EventStore` to be wired in before
production use.

Current surface:

- REST health, auth, Gemini convenience, tool, and session-index routes.
- Real-time STT WebSocket backed by Soniox.
- TaskIQ workers for Redis-backed reasoning and tool jobs.

Not included yet:

- A persistent `EventStore` for durable replay.
- A generic hosted-agent REST API beyond the current reference routes.
- Load-tested voice/runtime production hardening.

```bash
pip install kaji-serve
```

Before packaging, remove local Python caches from the repo tree from the repo
root:

```bash
find kaji \( -path '*/.venv/*' -o -path '*/node_modules/*' \) -prune -o \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \) -type d -exec rm -rf {} +
find kaji \( -path '*/.venv/*' -o -path '*/node_modules/*' \) -prune -o -name '*.pyc' -type f -delete
```
