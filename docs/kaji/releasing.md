# Kaji beta release runbook

Kaji betas are immutable, same-commit releases. A release is rebuilt from a
verified, signed, annotated beta tag; passes offline, compatibility,
performance, and provider gates; and then requires a separate approval before
either registry may be written.

Only a signed beta tag accepted by the protected `kaji-beta` environment can
advance to provider proof; registry authorization remains separate.

The two protected environments have intentionally different authority:

- `kaji-beta` permits the keyed OpenAI proof and optional Anthropic proof. It
  has provider secrets but no registry publisher authority.
- `kaji-beta-publish` permits PyPI trusted publishing and npm publication. Its
  required reviewers approve registry writes only after all preceding evidence
  is green. It must not contain provider keys.

Protect `kaji-v*-beta.*` tags against update and deletion. Each tag must be an
annotated Git tag with a verified signature and must target a commit directly.
Set the repository variable `KAJI_RELEASE_SIGNER_EMAIL` to the approved tagger
email. GitHub's signature verification must report `reason=valid`, and the
signed tagger metadata must match that value at every verification point. This
is the repository's current signer policy; it does not claim a separately
managed GPG/SSH fingerprint allowlist.
The publish workflow records both the annotated tag object SHA and the peeled
commit, then verifies the same pair again immediately before each registry
write and before attaching release assets. Lightweight, unsigned, retargeted,
or indirect tags fail closed.

## Offline rehearsal

From a clean checkout with Bun 1.3.11, Node 22 or 24, uv 0.11.25, and the locked
Python interpreters available, run:

```bash
uv run --project kaji/sdk python kaji/scripts/beta_release_check.py --release
uv run --project kaji/sdk python kaji/scripts/verify_package_metadata.py
```

`--release` is deliberately offline with respect to provider APIs and package
registries. It builds fresh Python wheel/sdist and npm tarball artifacts, tests
installed ESM and CommonJS entrypoints, validates metadata, audits locked
production dependencies, and writes `.artifacts/kaji-release/manifest.json`
plus `SHA256SUMS`. No keyed provider or publisher evidence is claimed by this
offline run.

The rehearsal and tag workflows retain the actual gate log and a machine-
readable result as `kaji-offline-evidence`, including when the gate fails. A
successful publish release attaches both files; a summary reconstructed from a
later run is not acceptable evidence.

## Protected release

1. Confirm the exact Python and TypeScript beta versions are unused on both
   registries.
2. Create a signed, annotated tag targeting the approved commit directly:

   ```bash
   git tag -s -a kaji-v0.2.0-beta.1 <approved-commit> -m "Kaji 0.2.0 beta 1"
   git push origin refs/tags/kaji-v0.2.0-beta.1
   ```

3. Approve `kaji-beta` only after offline, compatibility, and benchmark/soak
   jobs pass. `OPENAI_API_KEY` is required and missing it is a hard failure.
   `ANTHROPIC_API_KEY` is conditional: when configured, its normalized
   tool-call proof must pass; otherwise evidence records
   `anthropic=not_configured` and does not claim Anthropic readiness.
4. Review the exact manifest, checksums, offline summary, provider status,
   benchmark, soak, SBOM, and provenance evidence. The first
   `kaji-beta-publish` approval runs a non-mutating publisher preflight. It
   requires `NPM_TOKEN`, requires `KAJI_NPM_PUBLISHER` to match `npm whoami`,
   and verifies that identity has package write scope for `@kaji/sdk` or an
   approved write-capable `kaji` organization role for a first publication.
5. After publisher preflight passes, the Python and npm publisher jobs become
   eligible together under `kaji-beta-publish`. Approve both pending jobs in
   one final approval batch. Do not approve one publisher and defer or reject
   the other; neither registry write is intentionally ordered after the other.
   After approval, each publisher independently revalidates the artifact
   manifest and reverifies the same signed tag object/direct commit immediately
   before its registry write.
6. The workflow records a final registry status. After both publisher jobs
   report success it polls at most eight times with delays capped at 20 seconds
   (a 90-second total backoff window), compares PyPI's exact filename/size/
   SHA-256 metadata to the manifest, downloads and hashes the npm tarball, and
   verifies npm integrity metadata. Only byte-exact convergence is `complete`.
   It attaches the
   exact wheel, sdist, npm tarball, manifest, checksums, offline test evidence,
   provider/performance evidence, SPDX SBOM, provenance bundle, attestation ID
   and URL, and publication status to the GitHub prerelease.

The GitHub prerelease step is safe to retry only after both registry jobs have
succeeded: it reuses the existing prerelease, compares every existing asset's
SHA-256 digest, uploads only missing assets, and fails rather than replacing a
mismatched asset.

High or critical dependency findings fail the release. An exception requires a
named owner, affected package and advisory, compensating control, approval, and
an expiry date; expired exceptions are invalid.

## Partial or ambiguous publication

Registry versions and protected beta tags are immutable. A failed or cancelled
publisher can leave an externally visible package even when its job conclusion
is failure. Therefore:

- Before registry publication is proven complete, never click **Re-run failed jobs**
  or **Re-run all jobs**. The workflow rejects `run_attempt > 1` at
  registry preflight and never resumes a registry version.
- Treat any publisher failure, timeout, cancellation, or inconclusive registry
  lookup as `partial_or_ambiguous`; preserve `kaji-beta-artifacts`,
  `kaji-offline-evidence`, `kaji-supply-chain-evidence`, and
  `kaji-publication-status` from that run before remediation.
- Check both registry states exactly:

  ```bash
  curl --fail --silent --show-error https://pypi.org/pypi/kaji/0.2.0b1/json
  npm view @kaji/sdk@0.2.0-beta.1 version --json
  ```

- If `registry-preflight` or `publisher-preflight` failed and both publisher
  jobs were skipped, the workflow records a no-publication status. Do not yank
  or deprecate a pre-existing collision based on that run; investigate its
  ownership and still choose new beta versions.

- If Python `0.2.0b1` exists, open
  `https://pypi.org/manage/project/kaji/release/0.2.0b1/`, select **Options**,
  and yank the release with the incident/new-version reason. Do not delete its
  files or upload replacements.
- If npm `0.2.0-beta.1` exists, deprecate it with a forward pointer:

  ```bash
  npm deprecate @kaji/sdk@0.2.0-beta.1 "Unsafe beta; use the next published beta"
  ```

- Increment both package beta versions, update locks/changelogs, pass all gates
  again from the new commit, and create a new signed annotated tag. Even when
  only one registry write succeeded, never reuse either old version, retarget
  the old tag, resume the old workflow, or attach rebuilt files to its release.

There is one narrow rerun exception. When both original publisher jobs
succeeded, `kaji-publication-status/publication-status.json` says `complete`,
the registry-byte verification is retained, and the only failed job is
`release-evidence`, do not republish. In the Actions UI choose **Re-run jobs →
Re-run failed jobs**, or run:

```bash
gh run view <run-id> --json jobs
gh run rerun <run-id> --failed
```

First confirm the failed-job set contains only `release-evidence`. That rerun
reverifies the unchanged signed tag and invokes only the idempotent attachment
path: it rejects unexpected or duplicate remote assets, checks every existing
asset digest, uploads only missing assets, and requires the final remote asset-
name set to equal the desired set. Never delete, overwrite, or auto-replace a
mismatch.
