# kaji-serve

The experimental FastAPI + voice reference service for the
[Kaji SDK](../py/README.md).

Wraps `kaji` as a service experiment with REST and a Soniox speech-to-text
WebSocket. For the supported beta surface, embed the SDK in your own app.

Status: excluded from the 0.2 SDK beta. This package intentionally has no hosted
agent runtime or background tool worker; applications own the hand-off from a
final transcript to the canonical embedded `AgentRuntime`. It is not a
production durability or horizontal-scaling claim.

Current surface:

- REST health, auth, Gemini convenience, and session-index routes.
- Real-time Soniox STT WebSocket that returns partial, final, and complete
  transcripts without queuing an agent turn.

Not included yet:

- A hosted `AgentRuntime` adapter or persistent `EventStore`.
- Agent command submission, response relay, or TTS output hand-off.
- Background tool execution and distributed same-session coordination.
- A generic hosted-agent REST API beyond the current reference routes.
- Load-tested voice/runtime production hardening.

```bash
cd kaji/packages/serve
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
uv run --project kaji/packages/py python kaji/scripts/clean_caches.py --root kaji/packages/serve
```
