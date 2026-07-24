# Kaji beta release runbook

Kaji betas are immutable, same-commit releases. A release is rebuilt from a
verified, signed, annotated beta tag; passes offline, compatibility,
performance, and provider gates; and then requires a separate approval before
either registry may be written.

Only a signed beta tag accepted by the protected `kaji-beta` environment can
advance to provider proof; registry authorization remains separate.

The two protected environments have intentionally different authority:

- `kaji-beta` permits mandatory keyed OpenAI and Anthropic proof in Python and
  TypeScript, plus validation of the exact-commit five-user TTHW document.
  Configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and the raw redacted JSON
  document as `KAJI_TTHW_EVIDENCE_JSON`; missing or invalid evidence blocks
  release. This environment has no registry publisher authority.
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

## First-publication prerequisites

Complete these once before creating the release tag:

1. Make `enkyuan/alloy` public. The npm provenance required by this release is
   unsupported for a private source repository. First review the full Git
   history and Actions logs for secrets. After the visibility change, re-enable
   the branch and tag push rulesets that GitHub disables, and confirm standard
   GitHub-hosted runners are available.
2. Land the approved release commit on the default branch before tagging it.
   Never tag a feature-branch-only commit: package metadata and READMEs link to
   canonical documentation on the default branch, and the publish workflow
   rejects a tag whose commit is not already contained there.
3. Verify that the root and both package license files are byte-identical,
   package metadata declares `FSL-1.1-ALv2`, and the notice identifies
   `Copyright 2026 Enkang Yuan`. Record each version's first-public-availability
   date in its changelog and release notes: that version becomes available
   under Apache-2.0 on the second anniversary of that date.
4. In PyPI account publishing settings, add a pending trusted publisher for
   project `kaji-sdk`, owner `enkyuan`, repository `alloy`, workflow `kaji.publish.yml`,
   and environment `kaji-beta-publish`.
5. Confirm `npm view kaji-sdk name --json --registry=https://registry.npmjs.org/`
   returns `E404` immediately before tagging, then confirm
   `npm whoami --registry=https://registry.npmjs.org/` returns the approved
   `KAJI_NPM_PUBLISHER`. The first unscoped publication requires a short-lived
   npm token authorized to create public packages, with 2FA bypass enabled when
   the account policy requires it. Store it only as `NPM_TOKEN` in
   `kaji-beta-publish`; after the first release, configure npm trusted publishing
   for `kaji-sdk` and revoke the bootstrap token. npm exposes no non-mutating
   check that proves a token may create a new unscoped package, so the protected
   publisher remains the fail-closed authorization check.
6. Configure `kaji-beta` with required reviewers and only
   `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `KAJI_TTHW_EVIDENCE_JSON`.
   Configure `kaji-beta-publish` with separate required reviewers,
   `NPM_TOKEN`, and `KAJI_NPM_PUBLISHER`; do not copy provider keys into it.
7. Set repository variables `KAJI_RELEASE_SIGNER_EMAIL`,
   `KAJI_BENCHMARK_RUNNER_MANIFEST`, and
   `KAJI_BENCHMARK_RUNNER_MANIFEST_SHA256`. Register the pinned arm64 macOS
   performance runner with labels `self-hosted`, `macOS`, `ARM64`, and
   `kaji-benchmark`.

## Offline rehearsal

From a clean, real Git checkout with its `.git` metadata present, using Bun
1.3.11, Node 22 or 24, uv 0.11.25, and the locked Python interpreters, run:

```bash
uv run --project kaji python kaji/scripts/beta_release_check.py --release
```

Source archives are unsupported because the release gate must bind artifacts
to the exact checked-out commit and verify the source tree before packaging.
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
   git tag -s -a kaji-v0.2.0-beta.2 <approved-commit> -m "Kaji 0.2.0 beta 2"
   git push origin refs/tags/kaji-v0.2.0-beta.2
   ```

3. Approve `kaji-beta` only after offline, compatibility, and benchmark/soak
   jobs pass. `KAJI_TTHW_EVIDENCE_JSON` must contain the redacted five-user
   document for the exact current-run manifest and wheel, sdist, and npm
   artifacts. `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are both required; each
   must complete a normalized tool loop in Python and TypeScript. Missing-key
   hygiene is not release evidence.
4. Review the exact manifest, checksums, offline summary, provider status,
   benchmark, soak, SBOM, and provenance evidence. The first
   `kaji-beta-publish` approval runs a non-mutating publisher preflight. It
   requires `NPM_TOKEN`, requires `KAJI_NPM_PUBLISHER` to match `npm whoami`,
   and verifies existing `kaji-sdk` write access when the package already
   exists. For the first publication it instead requires an unambiguous `E404`
   for the unscoped package name and records that npm cannot prove new-package
   write authorization without performing the protected publication.
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
   verifies npm integrity metadata. Only byte-exact convergence is
   `byte_verified`; `both_published` is not a success terminal.
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
  curl --fail --silent --show-error https://pypi.org/pypi/kaji-sdk/0.2.0b1/json
  npm view kaji-sdk@0.2.0-beta.2 version --json --registry=https://registry.npmjs.org/
  ```

- If `registry-preflight` or `publisher-preflight` failed and both publisher
  jobs were skipped, the workflow records a no-publication status. Do not yank
  or deprecate a pre-existing collision based on that run; investigate its
  ownership and still choose new beta versions.

- If Python `0.2.0b1` exists, open
  `https://pypi.org/manage/project/kaji-sdk/release/0.2.0b1/`, select **Options**,
  and yank the release with the incident/new-version reason. Do not delete its
  files or upload replacements.
- If npm `0.2.0-beta.2` exists, deprecate it with a forward pointer:

  ```bash
  npm deprecate kaji-sdk@0.2.0-beta.2 "Unsafe beta; use the next published beta"
  ```

- Increment both package beta versions, update locks/changelogs, pass all gates
  again from the new commit, and create a new signed annotated tag. Even when
  only one registry write succeeded, never reuse either old version, retarget
  the old tag, resume the old workflow, or attach rebuilt files to its release.

There is one narrow rerun exception. When both original publisher jobs
succeeded, `kaji-publication-status/publication-status.json` says `byte_verified`,
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

## Human TTHW evidence

Store one redacted evidence document in the protected `kaji-beta` environment
as `KAJI_TTHW_EVIDENCE_JSON`. Both protected release workflows validate it with
`kaji/scripts/validate_tthw_evidence.py` and retain `kaji-tthw-evidence`; they
do not retain the document when validation fails. It must bind one 40-hex commit
and release-manifest hash to exact wheel, sdist, and npm artifact names, sizes,
versions, and SHA-256 values; automated Python/npm/Bun cold/warm timings; and
exactly five distinct pseudonymous fresh-user runs on arm64 macOS across
Python/npm/Bun. Each participant receipt repeats the exact commit, manifest
hash, measured macOS version, and artifact it installed: Python uses the wheel,
while npm and Bun use the npm tarball. Configuration alone does not claim that the cohort passed;
until that real evidence exists, TTHW is **unmeasured**.

Collect and compose it only through the
[TTHW evidence operator guide](tthw-evidence.md). The guide provides the
candidate-bound participant-template command, checked-in automated-timing
template, exact no-source Python/npm/Bun commands, required Echo tool-loop
observations, and the atomic `compose_tthw_evidence.py` command. The composer
rejects stale participant identity, derives totals and summary, and calls the
same protected validator before writing owner-only output.

The validator recomputes median and maximum totals. No-key median must be under
5 minutes and every run under 10; Echo median must be under 10 minutes and
every run under 20. Retain clean/no-source attestations, toolchain versions,
ordered step milliseconds, deterministic lifecycle assertions, redacted
confusion/remediation, owner, review date, and follow-up date. Repeat the
protocol 30 days after publication.

## Calibration provenance versus candidate evidence

The reviewed baseline retains the calibration commit and hashes for artifact
set A as provenance. Its applicability to candidate B is determined only by
the explicit benchmark source hash, dependency-lock hash, runtime/toolchain
versions, and pinned-runner fingerprint. The committed baseline does not need
to name B's release manifest.

This does not relax candidate evidence. Protected full benchmark and soak
receipts must install and identify candidate B's artifacts and must bind to
B's commit, release-manifest hash, and artifact hashes. Any applicability
fingerprint change requires a new calibration.
