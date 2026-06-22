# @agentkit/cli

CLI for agentkit. Works with TypeScript and Python projects.

## Install

```bash
bun add -D @agentkit/cli
# or
npx @agentkit/cli --help
```

## Commands

- `agentkit init` - scaffold a new agent (`--lang ts|python`, `--provider openai|anthropic|kimi|gemini`)
- `agentkit gen --spec <path> --out <dir>` - generate tool stubs from an OpenAPI spec (`--lang ts|python`)
- `agentkit info` - show environment + installed agentkit packages
- `agentkit doctor` - check the environment for common issues
- `agentkit secret` - generate a random 32-byte hex secret
- `agentkit upgrade` - upgrade installed `@agentkit/*` packages
- `agentkit mcp` - register agentkit MCP server with your AI tool

Run any command with `--help` for full flags.
