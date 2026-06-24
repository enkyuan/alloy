# @kaji/cli

CLI for kaji. Works with TypeScript and Python projects.

## Install

```bash
bun add -D @kaji/cli
# or
npx @kaji/cli --help
```

## Commands

- `kaji init` - scaffold a new agent (`--lang ts|python`, `--provider openai|anthropic|kimi|gemini`)
- `kaji gen --spec <path> --out <dir>` - generate tool stubs from an OpenAPI spec (`--lang ts|python`)
- `kaji info` - show environment + installed kaji packages
- `kaji doctor` - check the environment for common issues
- `kaji secret` - generate a random 32-byte hex secret
- `kaji upgrade` - upgrade installed `@kaji/*` packages
- `kaji mcp` - register kaji MCP server with your AI tool

Run any command with `--help` for full flags.
