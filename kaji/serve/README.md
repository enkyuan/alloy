# kaji-serve

The experimental FastAPI + voice reference service for the
[Kaji SDK](../sdk/README.md).

Wraps `kaji` as a real-time service experiment with REST, a voice WebSocket,
and a Redis-backed reasoning worker. For the supported beta surface, embed the
SDK in your own app.

Status: excluded from the 0.2 SDK beta. The active worker still uses the legacy
service Bus/AgentReasoningNode path and executes ordinary tool calls in-process.
TaskIQ code is present, but the normal reasoning path does not dispatch through
it. This package is not a production durability or horizontal-scaling claim.

Current surface:

- REST health, auth, Gemini convenience, tool, and session-index routes.
- Real-time STT WebSocket backed by Soniox.
- A legacy Redis-backed reasoning worker and separate TaskIQ worker surface.

Not included yet:

- A canonical `AgentRuntime` service adapter and persistent `EventStore`.
- Input acknowledgement after successful turn completion and output hand-off.
- Restart-safe tool idempotency and distributed same-session coordination.
- A generic hosted-agent REST API beyond the current reference routes.
- Load-tested voice/runtime production hardening.

```bash
cd kaji/serve
uv sync
```

Auth-enabled deployments must set `JWT_SECRET`, `JWT_ISSUER`, and
`JWT_AUDIENCE`; tokens are accepted only when all three match. The voice
WebSocket accepts either an `Authorization: Bearer ...` header or a
`kaji_access_token` cookie. `kaji-serve` does not issue that cookie: the host
application owns its secure/HttpOnly policy, and cookie auth is accepted only
when the browser `Origin` exactly matches `CORS_ALLOW_ORIGINS`.

Before packaging, remove local Python caches from the repo tree from the repo
root:

```bash
uv run --project kaji/sdk python kaji/sdk/scripts/clean_caches.py --root kaji/serve
```
