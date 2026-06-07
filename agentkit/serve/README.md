# agentkit-serve

The FastAPI + workers reference service for the [AgentKit SDK](../agentkit/README.md).

Wraps `agentkit` as a deployable real-time service (REST + voice WebSocket, an
LLM reasoning worker, and async tool workers over Redis). Install it when you
want to run the service; for embedding the SDK in your own app, use `agentkit`
directly.

```bash
pip install agentkit-serve
```
