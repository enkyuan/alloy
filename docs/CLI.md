# agentkit CLI

The `agentkit` CLI ships with the Python SDK. After `pip install agentkit`,
run `agentkit --help` for the current command list. Subcommands below.

| command | what it does |
| --- | --- |
| [`init`](#init) | scaffold a new agent project |
| [`gen`](#gen) | generate tool stubs from an OpenAPI spec |
| [`info`](#info) | print environment + config diagnostics |
| [`secret`](#secret) | mint a random 32-byte hex secret |
| [`doctor`](#doctor) | check the environment for common setup issues |
| [`upgrade`](#upgrade) | upgrade installed agentkit packages |

## init

Scaffold `agent.py` and `.env.example` in a target directory.

```bash
agentkit init ./my-agent --provider openai
```

| flag | default | meaning |
| --- | --- | --- |
| `path` (positional) | `.` | where to write files |
| `--provider` | prompted | `openai`, `anthropic`, `kimi`, or `gemini` |
| `--force` | off | overwrite existing files |
| `--yes` | off | non-interactive; use defaults |

The scaffold wires `AgentBuilder` to an env-driven provider; set
`AGENTKIT_MODEL_PROVIDER` plus the matching `*_API_KEY` to run it.

## gen

Read an OpenAPI 3 spec and emit a tool module the runtime can register.

```bash
agentkit gen --spec petstore.json --out ./tools --lang python --prefix pet
```

| flag | required | meaning |
| --- | --- | --- |
| `--spec` | yes | path to a JSON or YAML OpenAPI spec |
| `--out` | yes | output directory |
| `--lang` | no (default `python`) | `python` writes `tools.py`; `ts` writes `index.ts` |
| `--prefix` | no | string prepended to each generated tool name |

The generator inspects path + query parameters (typed as integer / string /
boolean / number when the spec declares it), excludes them from the JSON body
on non-GET methods, and emits an async HTTP handler per operation. Only
operations with an `operationId` are picked up. Bearer auth is assumed; the
env var name is derived from the spec title.

## info

Print Python / agentkit / provider config diagnostics. Useful when filing
issues.

```bash
agentkit info             # human-readable
agentkit info --json      # machine-readable
```

## secret

Mint a hex secret suitable for `AGENTKIT_SECRET` or any 32-byte signing key.

```bash
agentkit secret                       # prints "AGENTKIT_SECRET=<hex>"
agentkit secret --name JWT_SECRET     # different env var name
agentkit secret --json                # {"name": "AGENTKIT_SECRET", "value": "<hex>"}
```

## doctor

Runs a fixed checklist: Python version, installed agentkit packages,
provider env vars, write permissions on the working directory. Exits
non-zero if any check fails; prints a one-line remedy for each issue.

```bash
agentkit doctor              # human-readable
agentkit doctor --json       # machine-readable
```

## upgrade

Pip-upgrade installed agentkit packages. Prompts by default; pass `--yes`
to run unattended.

```bash
agentkit upgrade --yes
```

## TS CLI parity

The TypeScript SDK ships a parallel `agentkit` CLI (see `agentkit/ts`); its
commands mirror the Python ones (`init`, `gen`, `info`, `doctor`,
`upgrade`). When in doubt the Python CLI is the reference implementation.

## See also

- [AGENTKIT.md](AGENTKIT.md) for the shared concepts overview.
- [RUNTIME_API.md](RUNTIME_API.md) for the runtime API reference.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common errors and fixes.
