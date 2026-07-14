# Kaji CLI contract

The stable scaffold grammar in both packages is:

```text
kaji [--no-color] [--verbose] init [path] --provider mock|openai|anthropic --yes --force
```

`path` defaults to `.` and `--provider` defaults to `mock`. `--yes` guarantees
that no prompt is displayed and is currently a no-op. Every generated
destination is checked before any write. A collision without `--force` writes
nothing. Final-component symlinks are rejected and replacement writes do not
follow a raced-in symlink.

Both package CLIs use positional `init [path]` syntax. Unknown options,
including the removed init-only `--out` spelling, fail with a usage error. The
`add` command retains its separate `--out` destination flag.

## Command stability

| Operation | Python | TypeScript | Tier |
|---|---|---|---|
| `init` with mock/OpenAI/Anthropic | Yes | Yes | Stable |
| Echo `add` and `list-integrations` | Yes | Yes | Stable for Echo only |
| `replay` | No | Yes | Stable, redaction-safe projection |
| Python `doctor`, `gen`, `info`, `secret`, `upgrade` | Experimental | No | Experimental |
| GitHub `add` | Opt-in | Opt-in | Experimental |

Python OAuth hosts implement the public asynchronous `CredentialStore`
protocol to load, save, and delete principal-scoped credential records behind
the CLI boundary. Kaji's macOS adapter keeps the concrete keychain mechanism
out of integration and runtime code.

## Streams and exits

Requested data and successful write summaries use stdout. Warnings and
diagnostics use stderr. Exit `0` means success or help, `1` means validation,
runtime, file, or collision failure, and `2` means malformed usage.

`replay` fails closed on corrupt JSONL. Human and JSON formats contain only a
closed safe projection: structural IDs, tool identity, and error paths are
deterministically pseudonymized with bounded hashes so one session still groups
consistently without exposing source strings. Sequence and timestamp values are
bounded, while event/version/failure strings are closed allowlisted literals
with safe sentinels for unknown values. The stable failure fields are
`error_code`, `phase`, `retryable`, and `outcome`.
Prompts, assistant text, tool arguments/results, arbitrary metadata, key-like
fields, and raw causes are never printed. `--verbose` cannot expand this
redaction boundary. `--no-color` removes ANSI output.
