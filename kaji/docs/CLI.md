# kaji CLI

The `kaji` CLI ships with the Python SDK. After `pip install kaji`,
run `kaji --help` for the current command list. Subcommands below.

| command | what it does |
| --- | --- |
| [`init`](#init) | scaffold a new agent project |
| [`gen`](#gen) | generate tool stubs from an OpenAPI spec |
| [`add`](#add) | install an integration (shadcn-style copy) |
| [`list-integrations`](#list-integrations) | enumerate integrations available via `add` |
| [`info`](#info) | print environment + config diagnostics |
| [`secret`](#secret) | mint a random 32-byte hex secret |
| [`doctor`](#doctor) | check the environment for common setup issues |
| [`upgrade`](#upgrade) | upgrade installed kaji packages |

## init

Scaffold `agent.py` and `.env.example` in a target directory.

```bash
kaji init ./my-agent --provider openai
```

| flag | default | meaning |
| --- | --- | --- |
| `path` (positional) | `.` | where to write files |
| `--provider` | prompted | `openai`, `anthropic`, `kimi`, or `gemini` |
| `--force` | off | overwrite existing files |
| `--yes` | off | non-interactive; use defaults |

The scaffold wires `AgentBuilder` to an env-driven provider; set
`KAJI_MODEL_PROVIDER` plus the matching `*_API_KEY` to run it.

## gen

Read an OpenAPI 3 spec and emit a tool module the runtime can register.

```bash
kaji gen --spec petstore.json --out ./tools --lang python --prefix pet
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

## add

Install an integration into your project. The CLI copies the
integration's source files out of the registry bundled with the SDK,
shadcn-style, so you own the copies and can edit them freely.

```bash
kaji add github                       # writes ./integrations/github.py
kaji add github --out ./custom/path   # custom destination
kaji add github --force               # overwrite existing files
```

| flag | default | meaning |
| --- | --- | --- |
| `name` (positional) | required | integration name; see `kaji list-integrations` |
| `--out` | `./integrations` | destination directory |
| `--force` | off | overwrite existing files |

After install, the CLI prints any setup steps (env var to set, OAuth
scopes, optional `pip install` extras). Currently shipping:

- `github` -- read repos, issues, PRs via a personal access token.
- `gmail` -- read-only Gmail access via OAuth 2.0 (gmail.readonly).
- `gcal` -- read-only Google Calendar via OAuth 2.0 (calendar.readonly).

The Google integrations bundle a `SETUP.md` walking through the
one-time Google Cloud Console step. Both share the same OAuth client
credentials (`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`).

## list-integrations

Enumerate everything `kaji add` can install.

```bash
kaji list-integrations            # human-readable
kaji list-integrations --json     # machine-readable
```

## info

Print Python / kaji / provider config diagnostics. Useful when filing
issues.

```bash
kaji info             # human-readable
kaji info --json      # machine-readable
```

## secret

Mint a hex secret suitable for `KAJI_SECRET` or any 32-byte signing key.

```bash
kaji secret                       # prints "KAJI_SECRET=<hex>"
kaji secret --name JWT_SECRET     # different env var name
kaji secret --json                # {"name": "KAJI_SECRET", "value": "<hex>"}
```

## doctor

Runs a fixed checklist: Python version, installed kaji packages,
provider env vars, write permissions on the working directory. Exits
non-zero if any check fails; prints a one-line remedy for each issue.

```bash
kaji doctor              # human-readable
kaji doctor --json       # machine-readable
```

## upgrade

Pip-upgrade installed kaji packages. Prompts by default; pass `--yes`
to run unattended.

```bash
kaji upgrade --yes
```

## TS CLI parity

The TypeScript SDK ships a parallel `kaji` CLI (see `kaji/ts`); its
commands mirror the Python ones (`init`, `gen`, `info`, `doctor`,
`upgrade`). When in doubt the Python CLI is the reference implementation.

## See also

- [README.md](../README.md) for the shared concepts overview.
- [RUNTIME_API.md](RUNTIME_API.md) for the runtime API reference.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common errors and fixes.
