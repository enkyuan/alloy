# kaji × agentOS interop example

**Platform support (read first):** this example needs
[`@rivet-dev/agentos-core`](https://github.com/rivet-dev/agentos), which ships a
native sidecar (~130 MB) and runs on **macOS or Linux (glibc), x64 or arm64,
Node >= 22, ESM only**. It does **not** run on Windows, on musl/Alpine, or from a
CommonJS (`require`) context. If `npm install` fails on the native dependency, your
platform is unsupported — that is expected, not a bug.

It also pins `@rivet-dev/agentos-core@0.2.15` exactly. agentOS is preview software
whose API is still changing (its v0.2.15 already deprecates the flat `vm.exec`/
`vm.readFile` methods in favor of `vm.process.*`/`vm.filesystem.*`). An exact pin
keeps this example honest against a moving target; bump it deliberately.

## Why this is an example, not part of kaji

`kaji` is an infra-free, portable, dual-ESM/CJS package. agentOS is the opposite:
native, platform-gated, ESM-only, preview. Putting it behind a first-class `kaji`
export would break the package's portability contract for a large share of users at
`npm install` and couple a stable published package to a churning preview API. So this
interop lives here, outside the published tarball. If real demand appears and agentOS
stabilizes, the right home is a separately-versioned `@kaji/agentos` package — not a
subpath of the core SDK.

## What it does

Boots an agentOS VM with **network egress denied**, exposes three tools (`exec`,
`read_file`, `write_file`) to a kaji `AgentRuntime` as the `agentos` integration, and
runs one prompt that executes a shell command inside the VM.

The `exec` tool normalizes agentOS's `CodeExecutionResult` correctly: it branches on
`outcome`, so a failed or timed-out command surfaces as a failure with its `error`,
rather than being silently reported as success. `exitCode` (agentOS camelCase) is
mapped to `exit_code` (kaji snake_case).

## Security posture (explicit, not assumed)

agentOS's `permissions` has one field per category (`network`, `fs`, `childProcess`,
`process`, `env`), each `"allow"`, `"deny"`, or a `{ default, rules }` object. The docs
say it defaults to allow-all, but that is not reliable across sidecar builds — on the
build this example was verified against, setting only `network: "deny"` flipped the other
categories to deny and `exec` could not even spawn a shell. So this example sets **every
category explicitly**: `network: "deny"`, and `fs`/`childProcess`/`process`/`env`:
`"allow"`. Nothing is left to a default.

If you adapt this, tighten deliberately:

- **Network:** denied. Widen only with an explicit `{ default: "deny", rules: [...] }`
  allow-list of hosts a tool actually needs.
- **Filesystem:** allowed here for simplicity. In production, scope it with a
  `{ default: "deny", rules: [{ mode: "allow", paths: [...] }] }` and/or `mounts` in
  `AgentOsOptions`. `WORKDIR` (`/tmp`) is the path the read/write example uses.
- **childProcess / process:** allowed because `exec` spawns a shell. This is the whole
  point of the sandbox — the VM, not the permission set, is the isolation boundary.
- **Env / secrets:** nothing from the host env reaches the VM unless you pass it. Do not
  forward host secrets in.

**`exec` runs arbitrary commands** inside the VM. Treat everything the agent runs as
untrusted; the VM is what contains it.

### Known quirk

On the verified sidecar build, a successful `exec` may return an empty `stdout` (agentOS's
default output-capture behavior), while `outcome` and `exit_code` are always correct. If
you need captured stdout, configure the VM's execution output options. The kaji tool result
always carries the reliable fields (`outcome`, `exit_code`, and `error` on failure).

## Run

```bash
cd examples/agentos
npm install
OPENAI_API_KEY=... npm start   # or ANTHROPIC_API_KEY=...
```

## Files

- `agentos-integration.ts` — the kaji `Integration` wrapping the VM (exec normalization,
  missing-dep reframing, explicit egress deny).
- `exec-agent.ts` — boots the VM, wires the integration into an `AgentBuilder`, runs one
  turn, disposes the VM.
