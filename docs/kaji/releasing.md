# Kaji beta release runbook

Kaji betas are immutable, same-commit releases. A release is rebuilt from a
verified, signed, annotated beta tag; passes offline, compatibility,
performance, and provider gates; and then requires a separate approval before
npm may be written. This release publishes the TypeScript package only. The
Python wheel and sdist remain protected build and compatibility evidence; PyPI
publication is deferred.

Only a signed beta tag accepted by the protected `kaji-beta` environment can
advance to provider proof; registry authorization remains separate.

The two protected environments have intentionally different authority:

- `kaji-beta` permits mandatory keyed OpenAI proof in Python and TypeScript,
  plus validation of the exact-commit five-user TTHW document. Configure
  `OPENAI_API_KEY` and the raw redacted JSON document as
  `KAJI_TTHW_EVIDENCE_JSON`; missing or invalid evidence blocks release. This
  environment has no registry publisher authority.
- `kaji-beta-publish` permits npm publication only. Its required reviewers
  approve that registry write only after all preceding evidence is green. It
  must not contain `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other provider
  key.

Protect `kaji-v*-beta.*` tags against update and deletion. Each tag must be an
annotated Git tag with a verified signature and must target a commit directly.
Set the repository variable `KAJI_RELEASE_SIGNER_EMAIL` to the approved tagger
email. GitHub's signature verification must report `reason=valid`, and the
signed tagger metadata must match that value at every verification point. This
is the repository's current signer policy; it does not claim a separately
managed GPG/SSH fingerprint allowlist.
The publish workflow records both the annotated tag object SHA and the peeled
commit, then verifies the same pair again immediately before the npm write and
before attaching release assets. Lightweight, unsigned, retargeted, or
indirect tags fail closed.

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
4. Confirm `npm view kaji-sdk name --json --registry=https://registry.npmjs.org/`
   returns `E404` immediately before tagging, then confirm
   `npm whoami --registry=https://registry.npmjs.org/` returns the approved
   `KAJI_NPM_PUBLISHER`. The first unscoped publication requires a short-lived
   npm token authorized to create public packages, with 2FA bypass enabled when
   the account policy requires it. Store it only as `NPM_TOKEN` in
   `kaji-beta-publish`; after the first release, configure npm trusted publishing
   for `kaji-sdk` and revoke the bootstrap token. npm exposes no non-mutating
   check that proves a token may create a new unscoped package, so the protected
   publisher remains the fail-closed authorization check.
5. Configure `kaji-beta` with required reviewers and `OPENAI_API_KEY` as its
   only provider key. Leave the final
   `KAJI_TTHW_EVIDENCE_JSON` value unset until the tag-triggered workflow has
   built the exact artifacts used by the five participants. Configure
   `kaji-beta-publish` with separate required reviewers, `NPM_TOKEN`, and
   `KAJI_NPM_PUBLISHER`; do not copy provider keys into it.
6. Set the repository variable `KAJI_RELEASE_SIGNER_EMAIL`. Performance jobs
   run on GitHub-hosted `macos-15` ARM64 and fail closed unless GitHub's runner
   classification, the actual host, and the image's `imagedata.json` agree.
   The paired benchmark runs the immutable reference recorded in
   `kaji/benchmarks/beta-reference.json` beside the exact candidate on three
   numbered `macos-15` matrix replicas in one workflow run attempt. Each case
   uses five adjacent matched A/B pairs after two warmups. The exact
   runner/image receipts are retained; `RUNNER_NAME` is diagnostic and may
   repeat, but every replica must independently prove GitHub-hosted arm64
   macOS. Do not substitute a self-hosted runner. The 30-minute candidate soak
   is a separate required job and receipt.

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

1. Confirm npm `kaji-sdk@0.2.0-beta.8` is unused. Confirm PyPI
   `kaji-sdk==0.2.0b1` is absent as a negative invariant; this workflow must not
   create it.
2. Before creating the tag, configure the required `kaji-beta` reviewer and
   `OPENAI_API_KEY`. Leave `KAJI_TTHW_EVIDENCE_JSON` unset; remove any value from
   a prior run because it cannot bind the artifact bytes that this run will
   build. Keep the environment approval requirement enabled.
3. Create and push the signed, annotated tag targeting the approved commit
   directly:

   ```bash
   git tag -s -a kaji-v0.2.0-beta.8 <approved-commit> -m "Kaji 0.2.0 beta 8"
   git push origin refs/tags/kaji-v0.2.0-beta.8
   ```

4. Wait for the exact tag-triggered workflow run to upload
   `kaji-beta-artifacts` and for every ungated job to pass: offline gates,
   Python and Node compatibility, all three paired benchmark replicas and
   their aggregate, and the separate 30-minute soak. Do not approve the waiting
   `tthw-evidence` job yet. The `kaji-beta` approval is the safe pause that
   permits the final secret to be created from the current run. Do not remove
   the approval requirement.
5. Download `kaji-beta-artifacts` by the exact workflow run ID and artifact ID,
   not by a mutable branch or a same-named artifact from another run. In the
   operator shell, set `RUN_ID` to that numeric tag-triggered workflow run ID,
   then run:

   ```bash
   set -euo pipefail
   umask 077

   : "${RUN_ID:?set RUN_ID to the numeric tag-triggered workflow run ID}"
   case "$RUN_ID" in
     "" | *[!0-9]*)
       echo "RUN_ID must be one numeric workflow run ID" >&2
       exit 1
       ;;
   esac

   ARTIFACT_ID="$(
     gh api "repos/enkyuan/alloy/actions/runs/$RUN_ID/artifacts?per_page=100" \
       --jq '.artifacts[] | select(.name == "kaji-beta-artifacts" and .expired == false) | .id'
   )"
   case "$ARTIFACT_ID" in
     "" | *[!0-9]*)
       echo "expected exactly one numeric kaji-beta-artifacts ID" >&2
       exit 1
       ;;
   esac

   EVIDENCE_ROOT="$(mktemp -d "$HOME/.kaji-release-${RUN_ID}.XXXXXX")"
   ARTIFACTS_DIR="$EVIDENCE_ROOT/artifacts"
   ARCHIVE="$EVIDENCE_ROOT/kaji-beta-artifacts.zip"
   mkdir -m 700 "$ARTIFACTS_DIR"
   gh api "repos/enkyuan/alloy/actions/artifacts/$ARTIFACT_ID/zip" \
     >"$ARCHIVE"
   unzip -q "$ARCHIVE" -d "$ARTIFACTS_DIR"
   ```

   Confirm the query returned one ID and record both IDs with the private
   operator evidence. Keep the fresh owner-only directory until release
   evidence is complete; verify its downloaded manifest and all three artifacts
   before distributing them.

6. After the Python and Node compatibility jobs finish, download the exact
   final `kaji-python-compat-3.14` and `kaji-node-compat-24` artifacts by their
   artifact IDs from this same `RUN_ID`. Extract them into distinct owner-only
   directories, set `RUN_ATTEMPT` to this run's current attempt, and verify both
   receipts contain the exact run URL and attempt. Do not download an
   `*-initial` artifact. Generate five candidate-bound participant skeletons
   from the manifest and artifact directory, collect the five real arm64 macOS
   runs, and let the composer derive Python-wheel and Node npm/Bun timings from
   those two closed receipts by following
   [the TTHW evidence operator guide](tthw-evidence.md). Python 3.11, Node 22,
   and the Python sdist timing remain secondary compatibility evidence. Prior
   release, rehearsal, and performance artifacts are invalid substitutes;
   rehearsal evidence is never publication proof.
7. Use the approval helper for the exact validate → attempt-1 remote preflight
   → secret metadata snapshot → secret set-time/freshness check → repeated
   identical remote preflight → unchanged-secret metadata recheck →
   exact-deployment approval/response transaction:

   ```bash
   uv run --project kaji --no-sync python kaji/scripts/approve_tthw_gate.py \
     --run-id "$RUN_ID" \
     --evidence "$TTHW_DIR/KAJI_TTHW_EVIDENCE_JSON.json" \
     --release-manifest "$ARTIFACTS_DIR/manifest.json" \
     --artifacts-dir "$ARTIFACTS_DIR" \
     --python-compatibility-receipt \
       "$PYTHON_COMPAT_DIR/compatibility-receipt.json" \
     --node-compatibility-receipt \
       "$NODE_COMPAT_DIR/compatibility-receipt.json" \
     --approve
   ```

   Do not set `KAJI_TTHW_EVIDENCE_JSON` separately and do not approve
   `tthw-evidence` manually or in the Actions UI. The helper sends the exact
   newline-free validated file bytes to the environment secret through stdin
   and rejects terminal CR/LF bytes that GitHub CLI would remove. It requires
   the secret timestamp to change and be fresh for this set operation at the
   GitHub API's second precision. It then rechecks that the exact attempt-1 TTHW
   job is the sole waiting job in the run, the complete protected
   reviewer/custom branch-policy configuration and exact tag-policy identity,
   and the sole pending `kaji-beta` deployment snapshot. Immediately before
   approving, it confirms the complete post-set secret metadata snapshot is
   still unchanged; the approval response must contain exactly one deployment
   for the candidate commit, tag, and `kaji-beta`. Omitting `--approve`
   performs the complete local and remote preflight without changing state.
   Protected environment secrets are read when the job starts, so it validates
   the value just set against the current run's downloaded manifest, wheel,
   sdist, and npm tarball. After it passes, approve the downstream provider
   proof under
   `kaji-beta` if prompted; `OPENAI_API_KEY` must complete a normalized tool
   loop in Python and TypeScript. Missing-key hygiene is not release evidence.
   Anthropic and other experimental/WIP provider credentials are neither
   required nor accepted as substitutes for this proof.
   `kaji-beta-publish` remains a separate approval boundary and is not approved
   at this stage.
8. Review the exact manifest, checksums, offline summary, provider status,
   paired benchmark, soak, SBOM, and provenance evidence. The first
   `kaji-beta-publish` approval runs a non-mutating publisher preflight. It
   requires `NPM_TOKEN`, requires `KAJI_NPM_PUBLISHER` to match `npm whoami`,
   and verifies existing `kaji-sdk` write access when the package already
   exists. For the first publication it instead requires an unambiguous `E404`
   for the unscoped package name and records that npm cannot prove new-package
   write authorization without performing the protected publication.
9. After publisher preflight passes, approve the npm publisher under
   `kaji-beta-publish`. It revalidates the artifact manifest, reverifies the
   same signed tag object/direct commit, and rechecks that `npm whoami` still
   matches `KAJI_NPM_PUBLISHER` in the publication step immediately before the
   registry write. There is no Python publisher job.
10. The workflow records a final npm publication status. After the publisher
    reports success, the npm registry byte verifier makes at most 45 attempts
    with exponential delays starting at 2 seconds and capped at 20 seconds (830
    seconds of total scheduled backoff). The npm registry polling subprocess
    has a 20-minute outer cap that includes those delays and its bounded
    verification work. It requires PyPI to remain absent, downloads and hashes
    the npm tarball, and verifies npm integrity, signature, provenance, and
    GitHub attestation metadata. Only the explicit `npm_byte_verified` terminal
    is success; `npm_only` remains an incident in the default dual-registry
    state model.
    It attaches the exact npm tarball, manifest, checksums, offline test
    evidence, provider/performance evidence, SPDX SBOM, provenance bundle,
    attestation ID and URL, and publication status to the GitHub prerelease.
    The Python wheel and sdist remain retained Actions evidence and are not
    public release assets.

The GitHub prerelease step is safe to retry only after the npm publisher has
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
- Check the target npm version and the PyPI absence invariant exactly:

  ```bash
  test "$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      https://pypi.org/pypi/kaji-sdk/0.2.0b1/json
  )" = 404
  npm view kaji-sdk@0.2.0-beta.8 version --json --registry=https://registry.npmjs.org/
  ```

- If `registry-preflight` or `publisher-preflight` failed and the npm publisher
  was skipped, the workflow records a no-publication status. Do not yank
  or deprecate a pre-existing collision based on that run; investigate its
  ownership and still choose a new npm beta version.

- If Python `0.2.0b1` exists, stop: an out-of-band publication violated this
  release target. Preserve the evidence and remediate it separately before
  recommending either SDK.
- Treat `kaji-v0.2.0-beta.3` as a burned, immutable pre-build attempt. Protected
  run `30190948860` rejected it before artifact build or publication, so it is
  history, not release evidence. Never move or retry it; recovery requires the
  new beta.4 attempt.
- Treat `kaji-v0.2.0-beta.4` as a burned, immutable TTHW attempt. Protected run `30206052570`
  built candidate artifacts but failed because the protected TTHW evidence
  secret was empty; its paired benchmark aggregate also classified Python
  `toolBatch100` as inconclusive. It never reached publisher preflight or a
  registry transition. Never move or retry it, and never reuse its artifacts
  or evidence; recovery requires the new beta.5 attempt.
- Treat `kaji-v0.2.0-beta.5` as a burned, immutable signed attempt. Protected
  run `30215694650` built the exact candidate artifacts and passed the ungated
  release, compatibility, paired benchmark, and soak gates, then failed closed
  at `tthw-evidence`: `KAJI_TTHW_EVIDENCE_JSON` was unset, so
  the job received zero bytes. It never reached provider proof, publisher
  preflight, or a registry transition; its tag also predates the settled benchmark
  measurement-floor protocol. Never move, retry, approve, or add evidence to
  it, and never reuse its artifacts or evidence; recovery requires the new
  beta.6 attempt.
- Treat `kaji-v0.2.0-beta.6` as a burned, immutable performance attempt.
  Protected run `30230234051` passed tag verification, offline release,
  compatibility, all three raw paired replicas, and the 30-minute soak, then
  failed closed because TypeScript `crossSessionCommit100` replica duration
  ratios were `1.2059658457`, `1.0034830060`, and `1.0137219363`. The mixed
  aggregate was inconclusive. TTHW, provider proof, publisher preflight, and
  npm publication were skipped; npm and PyPI remained absent. Never move,
  retry, approve, or add evidence to it, and never reuse its artifacts or
  participant receipts; recovery requires the new beta.7 attempt.
- Treat `kaji-v0.2.0-beta.7` as a burned, immutable performance attempt.
  Protected run `30265105639` at
  `45bde8630154c61a97986f220a0df08d5ba6240b` passed all three raw paired
  replicas and the 30-minute soak, then failed closed because Python
  `toolBatch100` replica duration ratios were `0.9805314383`, `0.9756823917`,
  and `1.2290586651`. The mixed aggregate was inconclusive. TTHW, provider
  proof, publisher preflight, and npm publication were skipped; npm and PyPI
  remained absent. Never move, retry, approve, or add evidence to it, and
  never reuse its artifacts or
  participant receipts; recovery requires the new beta.8 attempt.
- Preserve the existing beta.2 signed tag and its history. Its original
  creation command is retained here only as a historical record; do not rerun
  it or move the tag:

  ```bash
  git tag -s -a kaji-v0.2.0-beta.2 <approved-commit> -m "Kaji 0.2.0 beta 2"
  ```

- If npm `0.2.0-beta.2` exists, deprecate it with a forward pointer:

  ```bash
  npm deprecate kaji-sdk@0.2.0-beta.2 "Unsafe beta; use the next published beta"
  ```

- Increment the npm beta version, update locks/changelogs, pass all gates again
  from the new commit, and create a new signed annotated tag. Never reuse the
  old npm version, retarget the old tag, resume the old workflow, or attach
  rebuilt files to its release.

There is one narrow rerun exception. When the original npm publisher succeeded,
`kaji-publication-status/publication-status.json` says `npm_byte_verified`,
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

Create the redacted evidence document only from the current tag-triggered
release artifacts, then store it in the protected `kaji-beta` environment as
`KAJI_TTHW_EVIDENCE_JSON` while the `tthw-evidence` job is waiting for approval.
Both protected release workflows validate it with
`kaji/scripts/validate_tthw_evidence.py` and retain `kaji-tthw-evidence`; they
do not retain the document when validation fails. It must bind one 40-hex commit
and release-manifest hash to exact wheel, sdist, and npm artifact names, sizes,
versions, and SHA-256 values; automated Python/npm/Bun cold/warm timings; and
exactly five distinct pseudonymous fresh-user runs on arm64 macOS split as two
Python, two npm, and one Bun. Each participant receipt repeats the exact commit,
manifest hash, measured macOS version, and artifact it installed: Python uses
the wheel, while npm and Bun use the npm tarball.
Configuration alone does not claim that the cohort passed; until that real
evidence exists, TTHW is **unmeasured**.
Prior release, rehearsal, and performance artifacts are invalid substitutes.

Collect and compose it only through the
[TTHW evidence operator guide](tthw-evidence.md). The guide provides the
candidate-bound participant-template command, exact no-source Python/npm/Bun
commands, required Echo tool-loop observations, canonical Python 3.14 and
Node 24 compatibility-receipt derivation, and the atomic
`compose_tthw_evidence.py` command. The composer rejects stale participant and
workflow-attempt identity, derives timings, totals, and summary, and calls the
same protected validator before writing owner-only output.

The validator recomputes median and maximum totals. No-key median must be under
5 minutes and every run under 10; Echo median must be under 10 minutes and
every run under 20. Retain clean/no-source attestations, toolchain versions,
ordered step milliseconds, deterministic lifecycle assertions, redacted
confusion/remediation, owner, review date, and follow-up date. Human
attestations start false; final receipts must prove clean/no-source execution,
monotonic timing, and the absence of failed, exhausted, or cancelled terminal
events. Placeholder values are rejected. Each review must fall on or within
seven days before the composer-owned `collectedDate`; the protected release
validator rejects a collection date in the future or more than seven days old.
The composed secret must not exceed 49,152 bytes.
Repeat the protocol 30 days after publication.

## Immutable reference and paired candidate evidence

`kaji/benchmarks/beta-reference.json` is the reviewed reference record. It
binds the exact reference commit, release-manifest hash, dependency-lock hash,
wheel, sdist, npm tarball, and retained GitHub artifact identity and digest.
Every protected replica downloads those immutable bytes, verifies every hash,
and installs the reference and exact release candidate independently. Never
rebuild or substitute the reference artifact. A reference expiry, missing
artifact, hash mismatch, absolute reference-budget failure, or dependency-lock
drift invalidates the evidence and requires an intentional reviewed reference
replacement.

The protected paired benchmark uses three numbered GitHub-hosted `macos-15`
matrix replicas in one workflow run attempt. For every Python and TypeScript
case, each replica records five adjacent matched reference/candidate pairs
after two warmups, with deterministic counterbalancing. A
candidate/reference peak-RSS ratio above `1.20` in any pair is a hard failure.
For timing, each replica's median paired ratio is compared with `1.20`: all
three at or below the threshold pass, all three above it are a regression, and
a mixed result is inconclusive and blocks release. Absolute candidate budgets
remain hard gates. `RUNNER_NAME` is retained only as diagnostic metadata and
is not required to be unique.

Retain the aggregate plus all three raw replica reports, runner identities, and
`imagedata.json` receipts. The 30-minute soak is separate evidence: it installs,
hashes, and reports only the exact candidate and retains its own runner/image
receipt. Neither performance receipt may stand in for the other.
