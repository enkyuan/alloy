# web

The reference web client for [AgentKit](../../README.md).

A [TanStack Start](https://tanstack.com/start) (React 19 + Vite) application
that demonstrates the AgentKit SDK in the browser — streaming audio to the
voice service over a WebSocket and rendering agent responses in real time.

## Stack

- **Framework:** TanStack Start + TanStack Router (file-based routing in `src/routes/`)
- **Build:** [Vite](https://vite.dev), [Vitest](https://vitest.dev) for tests
- **Styling:** Tailwind CSS
- **Talks to:** the `agentkit` SDK API (see [`agentkit/`](../../agentkit))

## Development

Run from the repository root so Bun resolves the workspace:

```bash
bun install                    # once, from the repo root
bun --filter web dev           # dev server on http://localhost:3000
bun --filter web build         # production build (Nitro server output)
bun --filter web test          # run the Vitest suite
```

The web client expects the SDK API to be reachable (run the backend per
[`agentkit/README.md`](../../agentkit/README.md)).

## Routing

File-based via TanStack Router — add a route by creating a file under
`src/routes/`. The root layout lives in `src/routes/__root.tsx`. See the
[TanStack Router docs](https://tanstack.com/router) for details.
