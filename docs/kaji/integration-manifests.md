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

Echo is the only beta integration. GitHub is experimental and requires
`--allow-experimental` when copied by either CLI. Every retained catalog entry
has a canonical cross-SDK ABI digest in copied-bundle provenance.

Manifest and index schema failures both normalize to
`INTEGRATION_SCHEMA_INVALID` with a JSON Pointer; their distinct exception
types retain which document failed. Experimental CLI denial uses
`INTEGRATION_EXPERIMENTAL`. These loader codes are a domain contract and are
not represented as provider errors.

## Validate and synchronize

```bash
uv run --project kaji/packages/py python kaji/scripts/sync_integration_contracts.py --check
bun --filter @irogane/kaji validate:registry
bun --filter @irogane/kaji check:integrations
bun --filter @irogane/kaji typecheck:registry
```

Corrupt or unreadable indexed manifests are fatal. List commands must not hide
them or silently skip an entry.

## Exact-artifact GitHub proof

The source-only `live_github_proof.py` operator tool can prove one
`github.get_issue` read and one exactly approved `github.add_comment` call from
the candidate wheel and npm tarball. It accepts an owner-only fixture for an
existing private-repository issue, binds both installed-runtime cells to the
same protected compatibility run, and publishes a redacted receipt only after
the temporary comments are independently read back and deleted.

Proof and standalone cleanup commands take one exclusive owner-only lock for
the selected state file. A concurrent invocation fails before transport; rerun
it only after the active operator command exits.

If cleanup reports a pending absence, wait for GitHub visibility to converge
and rerun the ordinary cleanup command. Only after an ordinary run has observed
zero exact-marker comments may an operator perform a fresh, explicit absence
check with `github_proof_cleanup.py --confirm-absence`. That confirmation never
retries the comment mutation and closes the proof as failed rather than
converting an unknown dispatch into a pass.

If an exact marker is observed on an issue other than the designated fixture,
cleanup stays pending for manual review. Do not use absence confirmation to
clear that state, and do not automatically delete the out-of-scope comment.

This tooling does not promote GitHub by itself. A catalog-beta integration
still owes a valid exact-artifact proof receipt for the release artifacts
(`github-proof-v1.schema.json` for GitHub) from a protected operator run before
its live side effects are claimed. Gmail is now a catalog-beta integration on
the same footing: its receipt schema is `gmail-proof-v1.schema.json`, and its
protected operator run (one `gmail.get_message` read plus one exactly-approved
`gmail.send_message`, read back and deleted) is pending on the release commit.
Until that receipt exists, treat Gmail's live send path as unproven, not the
catalog stability, which is beta.
