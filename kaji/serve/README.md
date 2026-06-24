# kaji-serve

The FastAPI + workers reference service for the [Kaji SDK](../kaji/README.md).

Wraps `kaji` as a deployable real-time service (REST + voice WebSocket, an
LLM reasoning worker, and async tool workers over Redis). Install it when you
want to run the service; for embedding the SDK in your own app, use `kaji`
directly.

```bash
pip install kaji-serve
```
