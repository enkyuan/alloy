## Task 3: Make MCP Setup Honest

**Purpose:** `kaji mcp` currently writes config for a non-existent `mcp-server` subcommand. That is worse than an unimplemented feature because it creates a broken setup path in user tools.

**Modify:**

- `apps/cli/src/commands/mcp.ts`
- `apps/cli/test/commands/mcp.test.ts`
- `apps/cli/README.md`
- `apps/docs/content/cli.mdx`
- `apps/docs/components/landing/install/mcp-dropdown.tsx`

**Decision:** Do not implement a full MCP server in this plan. Make the command and docs honest. If a server is later built, it should get its own implementation plan and tests.

**Implementation requirements:**

- Remove or gate `MCP_ARGS = ["-y", "@kaji/cli", "mcp-server"]`.
- `kaji mcp` must not write MCP config that points to `mcp-server`.
- The command should exit with a clear unsupported message:

```text
Kaji MCP setup is not shipped in @kaji/cli yet.
Use `kaji gen` to generate tools today. MCP server support is planned separately.
```

- Keep any helper functions only if tests use them or if they will be reused by a future real MCP server.
- Docs should not instruct users to run `npx kaji mcp --cursor`, `--claude-code`, `--open-code`, or `--manual` because those flags do not exist in the current CLI.
- Landing-page install dropdown should either remove MCP entries or label them as "coming soon" without executable commands.

**Tests:**

- `mcp` action does not write any config file.
- Output contains "not shipped" or equivalent clear unsupported phrasing.
- No test fixture or source file under `apps/cli` still contains `mcp-server` except in a negative assertion or migration note.

**Verify:**

```bash
cd apps/cli
bun run test -- test/commands/mcp.test.ts
rg -n "mcp-server|npx kaji mcp --|--claude-code|--open-code|--manual" apps/cli apps/docs
```

Expected `rg` result after implementation: no executable setup instructions for the unsupported MCP path. If a docs note remains, it must say MCP server support is deferred.

**Checkpoint:** `fix(cli): stop advertising broken mcp setup`

