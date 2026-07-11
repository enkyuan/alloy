# Integration Manifests

The canonical schemas are
[`manifest.schema.json`](../../kaji/contracts/integrations/manifest.schema.json)
and [`index.schema.json`](../../kaji/contracts/integrations/index.schema.json).
Both SDK loaders consume byte-identical package copies and normalize manifest
validation failures to JSON Pointers.

## Manifest shape

Each manifest is closed: unknown fields fail. It requires a safe name,
namespace, semantic version, non-empty description, one auth variant, contained
relative files, and at least one tool. Every tool has a unique name,
description, and explicit risk.

Auth is a closed union:

- `{"kind":"none"}` has no credential fields.
- `{"kind":"env","env":"API_KEY","optional":false}` uses an uppercase
  safe environment name; `optional` defaults to false.
- `{"kind":"oauth","scopes":["scope"]}` uses a non-empty unique scope set.

Optional auth documentation must be a valid URI. File paths cannot be
absolute, contain backslashes, or traverse through `.` or `..`. Schema checks
are followed by resolved-path containment and referenced-file existence checks.
`extras` is an optional unique list of Python package extras. `peerDeps` is an
optional map of non-empty package names to non-empty version ranges. Both are
installation metadata only; they do not weaken runtime auth or risk checks.

## Index shape and stability

The registry index points to its own `index.schema.json`. Keys must match the
referenced manifest name. Each entry declares the manifest, stability, and
supported runtimes:

```json
{
  "echo": {
    "manifest": "echo/manifest.json",
    "stability": "beta",
    "runtimes": ["python", "typescript"]
  }
}
```

Echo is the only beta integration. TypeScript HTTP, Web, filesystem, and SQLite
entries are experimental and require `--allow-experimental` when copied by the
CLI. HTTP and Web also require an application-owned address-pinning transport
or egress proxy; the SDK deliberately has no native `fetch()` fallback.

Manifest and index schema failures both normalize to
`INTEGRATION_SCHEMA_INVALID` with a JSON Pointer; their distinct exception
types retain which document failed. Experimental CLI denial uses
`INTEGRATION_EXPERIMENTAL`. These loader codes are a domain contract and are
not represented as provider errors.

## Validate and synchronize

```bash
uv run --project kaji/sdk python kaji/scripts/sync-integration-contracts.py --check
cd kaji/ts
bun run validate:registry
bun run check:integrations
bun run typecheck:registry
```

Corrupt or unreadable indexed manifests are fatal. List commands must not hide
them or silently skip an entry.
