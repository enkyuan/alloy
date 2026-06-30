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

```bash
pip install kaji-serve
```
