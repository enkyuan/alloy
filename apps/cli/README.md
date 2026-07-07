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
- `kaji mcp` - explain MCP setup status; server support is planned separately

Run any command with `--help` for full flags.

## First run

```bash
kaji init --cwd ./my-agent --lang ts --provider openai --yes
cd ./my-agent
bun install
export OPENAI_API_KEY=sk-...
bun start
```

Python scaffolds use the same high-level SDK path:

```bash
kaji init --cwd ./my-agent --lang python --provider openai --yes
cd ./my-agent
python -m pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
python agent.py
```

The generated agents call `turn("Say hello.")`. OpenAI `gpt-5.4-mini` is the
recommended first live model in the SDK test path; provider env overrides remain
available in each SDK.
