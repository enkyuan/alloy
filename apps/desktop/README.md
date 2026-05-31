# @agentkit/desktop

The native desktop client for [AgentKit](../../README.md).

A [Tauri 2](https://tauri.app) + React 19 application that captures microphone
audio and streams it to the AgentKit SDK's STT WebSocket, rendering transcripts
and agent responses in real time. Tauri wraps the React UI in a lightweight
native shell (Rust core) rather than bundling a full browser.

## Stack

- **Shell:** Tauri 2 (Rust)
- **UI:** React 19, [Vite](https://vite.dev)
- **Talks to:** the `agentkit` SDK API (see [`packages/sdk`](../../packages/sdk))

## Development

Run from the repository root so Bun resolves the workspace:

```bash
bun install                              # once, from the repo root
bun --filter @agentkit/desktop dev       # run in development
bun --filter @agentkit/desktop build     # production build
```

The desktop client expects the SDK API to be reachable (run the backend per
[`packages/sdk/README.md`](../../packages/sdk/README.md)).

### Recommended IDE setup

[VS Code](https://code.visualstudio.com/) with the
[Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode)
and [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
extensions.
