# Kaji beta release runbook

Kaji betas are immutable, same-commit releases. A release is rebuilt from a
verified, signed, annotated beta tag; passes offline, compatibility,
performance, and provider gates; and then requires a separate approval before
npm may be written. This release publishes the TypeScript package only. The
Python wheel and sdist remain protected build and compatibility evidence; PyPI
publication is deferred.

Three protected environments have intentionally different authority:

- `kaji-beta-onboarding` protects only the deterministic TypeScript onboarding
  aggregate. It receives no provider or registry secret. Its single deployment
  is `typescript-onboarding-evidence`, after the unprotected archive calibration
  has validated the same three current-run raw REST ZIP bodies.
- `kaji-beta` protects mandatory keyed OpenAI proof in Python and TypeScript.
  Configure `OPENAI_API_KEY` here only. It has no registry publisher authority.
- `kaji-beta-publish` protects the sole final npm write. Its single deployment
  is `publish-npm`, and only credentialed steps in that job receive
  `NPM_TOKEN`. It must not contain a provider key.

Approve these environments separately and in that order. An onboarding
approval cannot authorize provider proof or registry publication.

The automated onboarding claim is deliberately narrow: the exact current-run
tarball passed npm and Bun install, scaffold, no-key, deterministic Echo
lifecycle, cold-run, and warm-run proofs on GitHub-hosted Linux/x64, with Node
22 on `ubuntu-22.04` and Node 24 on `ubuntu-24.04`. It does not claim five
human participants, macOS or arm64 onboarding, Windows onboarding, or fully
offline dependency installation. The separate paired benchmark and soak
receipts retain their own reviewed runner claims. The closed fields, exact
archive bindings, and canonical executable snippets are documented in the
[TypeScript onboarding evidence guide](typescript-onboarding-evidence.md).

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
4. Configure all three environments with required reviewer `enkyuan`,
   `prevent_self_review=false`, and `can_admins_bypass=false`.
   `kaji-beta-onboarding` and `kaji-beta` permit only `main` and
   `kaji-v0.2.0-beta.11`; `kaji-beta-publish` permits only
   `kaji-v0.2.0-beta.11`. Configure `OPENAI_API_KEY` only in `kaji-beta`, and
   configure `KAJI_NPM_PUBLISHER` only for the final publisher boundary. Audit
   the complete reviewer and custom branch-policy state without reading any
   secret:

   ```bash
   uv run --project kaji/packages/python --no-sync python \
     kaji/scripts/approve_typescript_onboarding_gate.py audit-environments
   ```

5. Confirm the exact first-publication registry state. The protected workflow
   fails closed unless the stable `tiny-tarball@1.0.0` npm control is an exact
   200 JSON document, the `kaji-sdk` packument is an exact 404 JSON object
   `{"error":"Not found"}`, and the exact beta.11 endpoint is an exact 404 JSON
   string `"Not Found"`. It binds every response to its original HTTPS URL,
   forbids redirects, bounds the body, and requires a JSON content type. Do not
   infer absence from npm CLI error text or a substring match. The PyPI beta
   endpoint must independently return HTTP 404; that invariant is not
   permission to publish Python.

   Immutable beta.9 run `30726249929` failed closed before `npm publish` when
   npm 11.16 warned about setup-node's deprecated `always-auth=false` setting;
   npm and PyPI remained absent. Do not rerun that workflow or reuse its tag.
   Before beta.11 tag creation, the operator must explicitly confirm that a
   fresh `NPM_TOKEN` is stored only in `kaji-beta-publish`. Do not inspect,
   copy, or test the secret locally. Do not run a local credential preflight;
   the protected `publish-npm` job removes
   only setup-node's deprecated setting, then performs exact `npm whoami`
   equality with `KAJI_NPM_PUBLISHER` as its first credentialed action and
   fails closed before publication.
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
uv run --project kaji/packages/python python kaji/scripts/beta_release_check.py --release
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

### Rehearse the exact reviewed `main`

1. Set `REVIEWED_COMMIT` to the exact reviewed 40-lowercase-hex commit. Require
   remote `main` to equal it, recheck npm beta.11 and PyPI absence, and audit all
   three protected environments:

   ```bash
   test "$(gh api repos/enkyuan/alloy/commits/main --jq .sha)" \
     = "$REVIEWED_COMMIT"
   uv run --project kaji/packages/python --no-sync python \
     kaji/scripts/approve_typescript_onboarding_gate.py audit-environments
   ```

2. Dispatch the rehearsal at ref `main`; never dispatch a raw SHA:

   ```bash
   gh workflow run .github/workflows/kaji.rehearsal.yml \
     --ref main \
     --field expected-commit="$REVIEWED_COMMIT"
   ```

   Record the exact run ID, run attempt, `head_sha`, workflow path, workflow
   SHA, and producer artifact ID/digest. Attempt must be 1, and every commit
   value must equal `REVIEWED_COMMIT`.

3. Wait for offline gates, Python and Node compatibility, all three paired
   benchmark replicas and their aggregate, the 30-minute soak, and
   `typescript-onboarding-archive-calibration`. The calibration must be
   terminal success before `typescript-onboarding-evidence` becomes the sole
   waiting deployment under `kaji-beta-onboarding`. Do not approve a run with
   a failed calibration, a rerun, a mixed attempt, or any other waiting job.

4. Query the complete current-run artifact collection. Resolve exactly one
   unexpired `kaji-beta-artifacts`, `kaji-node-compat-22`, and
   `kaji-node-compat-24`. Record each exact artifact ID and canonical
   `sha256:<64 lowercase hex>` REST digest, then raw-download each ZIP by its
   exact ID:

   ```bash
   umask 077
   EVIDENCE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/kaji-beta10.XXXXXX")"
   gh api -H "X-GitHub-Api-Version: 2026-03-10" \
     "repos/enkyuan/alloy/actions/runs/$REHEARSAL_RUN_ID/artifacts?per_page=100" \
     >"$EVIDENCE_ROOT/artifacts.json"
   gh api -H "X-GitHub-Api-Version: 2026-03-10" \
     "repos/enkyuan/alloy/actions/artifacts/$PRODUCER_ARTIFACT_ID/zip" \
     >"$EVIDENCE_ROOT/producer.zip"
   gh api -H "X-GitHub-Api-Version: 2026-03-10" \
     "repos/enkyuan/alloy/actions/artifacts/$NODE22_ARTIFACT_ID/zip" \
     >"$EVIDENCE_ROOT/node22.zip"
   gh api -H "X-GitHub-Api-Version: 2026-03-10" \
     "repos/enkyuan/alloy/actions/artifacts/$NODE24_ARTIFACT_ID/zip" \
     >"$EVIDENCE_ROOT/node24.zip"
   ```

   Resolve the IDs and digests from the complete collection and three by-ID
   responses; do not use name-only downloads. Do not extract and re-zip these
   inputs. The helper authenticates the exact raw ZIP bytes against their REST
   digests and recomputes the two-cell aggregate.

5. Run the approved helper first without `--approve`. This is the complete
   read-only rehearsal audit and dry run:

   ```bash
   uv run --project kaji/packages/python --no-sync python \
     kaji/scripts/approve_typescript_onboarding_gate.py gate \
     --mode rehearsal \
     --run-id "$REHEARSAL_RUN_ID" \
     --expected-commit "$REVIEWED_COMMIT" \
     --producer-archive "$EVIDENCE_ROOT/producer.zip" \
     --producer-artifact-id "$PRODUCER_ARTIFACT_ID" \
     --producer-artifact-digest "$PRODUCER_ARTIFACT_DIGEST" \
     --node22-archive "$EVIDENCE_ROOT/node22.zip" \
     --node22-artifact-id "$NODE22_ARTIFACT_ID" \
     --node22-artifact-digest "$NODE22_ARTIFACT_DIGEST" \
     --node24-archive "$EVIDENCE_ROOT/node24.zip" \
     --node24-artifact-id "$NODE24_ARTIFACT_ID" \
     --node24-artifact-digest "$NODE24_ARTIFACT_DIGEST"
   ```

   Only after that command succeeds, rerun the identical command with
   `--approve` appended. The helper stable-reads the archives, repeats the
   complete local and 13-GET remote snapshot, requires unchanged state, and
   approves exactly the sole `kaji-beta-onboarding` deployment. Do not approve
   onboarding manually in the Actions UI. A failure after the approval POST is
   ambiguous; do not retry it or rerun the workflow.

6. Require the protected onboarding aggregate and its retained
   `status.json`, `validation.log`, and
   `typescript-onboarding-evidence.json` to pass. Approve the later, distinct
   `kaji-beta` deployment separately. The keyed provider proof must complete a
   normalized OpenAI tool loop in Python and TypeScript; missing-key hygiene is
   not provider evidence.

7. Wait for terminal-green candidate evidence and independently select the
   exact `kaji-beta-artifacts` and `kaji-release-candidate-evidence` IDs,
   names, canonical REST digests, manifest hash, and npm tarball hash. Download
   and verify both artifacts by exact ID. These immutable rehearsal identities,
   not a later rebuild or same-named artifact, form the tag authorization.

### Bind the signed beta.11 tag to the rehearsal

The authorization object has no optional or extra fields. Serialize it with
recursively lexicographically sorted keys, compact `,`/`:` separators, ASCII
JSON, and exactly one terminal LF:

```json
{"candidateArtifact":{"digest":"sha256:<64 lowercase hex>","id":456,"name":"kaji-beta-artifacts"},"commit":"<40 lowercase hex>","evidenceArtifact":{"digest":"sha256:<64 lowercase hex>","id":789,"name":"kaji-release-candidate-evidence"},"npmTarball":{"name":"kaji-sdk-0.2.0-beta.11.tgz","sha256":"<64 lowercase hex>"},"rehearsal":{"runAttempt":1,"runId":123,"workflowPath":".github/workflows/kaji.rehearsal.yml","workflowSha":"<same commit>"},"releaseManifestSha256":"<64 lowercase hex>","schemaVersion":"1.0.0"}
```

The exact message is that one compact line plus one LF, with no CR, BOM,
leading/trailing space, second LF, or signature text. Hash those exact message
bytes, including the LF, as the authorization SHA-256. Require the commit and
workflow SHA to equal `REVIEWED_COMMIT`, run attempt 1, distinct positive-safe
artifact IDs, fixed artifact names, and the exact beta.11 tarball name.

Stop here until the operator explicitly confirms a fresh `NPM_TOKEN` is stored
only in `kaji-beta-publish`. Do not inspect or test the secret. After that
confirmation and one final registry/tag/main/environment recheck, write the
exact authorization bytes to `AUTHORIZATION_FILE`.

Validate the file before signing. This rejects CR, BOM, NUL, tabs, non-ASCII,
multiple lines, a missing or second terminal LF, non-JSON input, and any
serialization other than recursively sorted compact JSON:

```bash
set -euo pipefail
: "${AUTHORIZATION_FILE:?set the exact authorization-message path}"
: "${REVIEWED_COMMIT:?set the exact rehearsed commit}"

AUTHORIZATION_SHA256="$(
  uv run --project kaji/packages/python --no-sync python - "$AUTHORIZATION_FILE" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

raw = Path(sys.argv[1]).read_bytes()
if not raw or len(raw) > 2_048:
    raise SystemExit("authorization must contain 1..2048 bytes")
if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
    raise SystemExit("authorization must be one line with exactly one terminal LF")
if b"\r" in raw or b"\0" in raw or b"\t" in raw or raw.startswith(b"\xef\xbb\xbf"):
    raise SystemExit("authorization contains a forbidden byte")
try:
    text = raw.decode("ascii")
except UnicodeDecodeError as error:
    raise SystemExit("authorization must be ASCII") from error

def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")

try:
    value = json.loads(text[:-1], parse_constant=reject_constant)
except (json.JSONDecodeError, ValueError) as error:
    raise SystemExit("authorization is not strict JSON") from error
if type(value) is not dict:
    raise SystemExit("authorization root must be an object")
canonical = (
    json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n"
).encode("ascii")
if canonical != raw:
    raise SystemExit("authorization bytes are not canonical compact JSON plus LF")
print(hashlib.sha256(raw).hexdigest())
PY
)"

TAG=kaji-v0.2.0-beta.11
git tag -s --cleanup=verbatim -F "$AUTHORIZATION_FILE" \
  "$TAG" "$REVIEWED_COMMIT"
```

The local tag is not yet authorized for push. Read its raw annotated-tag
object, require the frozen four-header/direct-commit shape and exactly one
supported GPG or SSH signature-begin marker, and compare the signature-bound
message bytes before that marker byte-for-byte with the unchanged
`AUTHORIZATION_FILE`:

```bash
set -euo pipefail
: "${TAG:?create the local beta.11 tag first}"
: "${AUTHORIZATION_FILE:?retain the exact authorization-message path}"
: "${AUTHORIZATION_SHA256:?retain the validated authorization digest}"

uv run --project kaji/packages/python --no-sync python - \
  "$TAG" "$REVIEWED_COMMIT" "$AUTHORIZATION_FILE" \
  "$AUTHORIZATION_SHA256" <<'PY'
import hashlib
from pathlib import Path
import subprocess
import sys

tag, commit, authorization_path, expected_sha256 = sys.argv[1:]
authorization = Path(authorization_path).read_bytes()
if hashlib.sha256(authorization).hexdigest() != expected_sha256:
    raise SystemExit("authorization file changed after canonical validation")

tag_object = subprocess.run(
    ["git", "cat-file", "tag", tag],
    check=True,
    stdout=subprocess.PIPE,
).stdout
headers, separator, body_and_signature = tag_object.partition(b"\n\n")
if separator != b"\n\n":
    raise SystemExit("annotated tag lacks one header/body separator")
header_lines = headers.split(b"\n")
expected_prefix = [
    f"object {commit}".encode("ascii"),
    b"type commit",
    f"tag {tag}".encode("ascii"),
]
if (
    len(header_lines) != 4
    or header_lines[:3] != expected_prefix
    or not header_lines[3].startswith(b"tagger ")
):
    raise SystemExit("annotated tag headers do not bind the direct commit")

formats = (
    (
        b"-----BEGIN PGP SIGNATURE-----\n",
        b"-----END PGP SIGNATURE-----\n",
    ),
    (
        b"-----BEGIN SSH SIGNATURE-----\n",
        b"-----END SSH SIGNATURE-----\n",
    ),
)
marker_count = sum(body_and_signature.count(begin) for begin, _ in formats)
matches = [(begin, end) for begin, end in formats if begin in body_and_signature]
if marker_count != 1 or len(matches) != 1:
    raise SystemExit("tag must contain exactly one supported GPG/SSH signature")
begin, end = matches[0]
marker_offset = body_and_signature.index(begin)
signed_message = body_and_signature[:marker_offset]
signature = body_and_signature[marker_offset:]
if signed_message != authorization:
    raise SystemExit("signed tag message differs from AUTHORIZATION_FILE")
if signature.count(begin) != 1 or signature.count(end) != 1 or not signature.endswith(end):
    raise SystemExit("tag signature armor is malformed or has trailing bytes")
PY

git verify-tag "$TAG"
git push origin "refs/tags/$TAG"
```

This mirrors the publish verifier's use of GitHub's signature-bound
`verification.payload`: the local raw tag object before its signature armor is
the four headers, one blank separator, and the exact authorization message.
Never use a broad free-form `-m` tag message. Never move, delete, recreate, or
reuse this tag after it is pushed.

### Approve the tag-triggered publish gates

1. Require the publish run to be attempt 1 and bound to the exact tag object,
   peeled commit, signed authorization digest, rehearsal run, and signed
   candidate/evidence IDs and digests. The workflow parses only GitHub's
   verified, valid `verification.payload`, never the tag API's message field.
   Its offline gate rebuild must byte-match the signed rehearsal npm tarball;
   only signed rehearsal bytes may populate the current carrier.

2. Wait for the current publish run's producer and Node 22/24 artifacts and
   successful unprotected archive calibration. Raw-download all three exact
   current-run ZIP bodies by artifact ID and record their canonical REST
   digests exactly as in the rehearsal.

3. Run the same helper without `--approve`, now with `--mode publish` and the
   publish run's exact IDs, digests, and raw ZIPs:

   ```bash
   uv run --project kaji/packages/python --no-sync python \
     kaji/scripts/approve_typescript_onboarding_gate.py gate \
     --mode publish \
     --run-id "$PUBLISH_RUN_ID" \
     --expected-commit "$REVIEWED_COMMIT" \
     --producer-archive "$PUBLISH_EVIDENCE_ROOT/producer.zip" \
     --producer-artifact-id "$PUBLISH_PRODUCER_ARTIFACT_ID" \
     --producer-artifact-digest "$PUBLISH_PRODUCER_ARTIFACT_DIGEST" \
     --node22-archive "$PUBLISH_EVIDENCE_ROOT/node22.zip" \
     --node22-artifact-id "$PUBLISH_NODE22_ARTIFACT_ID" \
     --node22-artifact-digest "$PUBLISH_NODE22_ARTIFACT_DIGEST" \
     --node24-archive "$PUBLISH_EVIDENCE_ROOT/node24.zip" \
     --node24-artifact-id "$PUBLISH_NODE24_ARTIFACT_ID" \
     --node24-artifact-digest "$PUBLISH_NODE24_ARTIFACT_DIGEST"
   ```

   After the dry run succeeds, rerun the identical command with `--approve`
   appended. Require the protected onboarding aggregate to finish terminal
   green, then approve the later `kaji-beta` keyed-provider deployment
   separately.

4. Review the exact manifest, checksums, offline summary, compatibility,
   onboarding, provider, paired benchmark, soak, SBOM, provenance,
   attestation, signed-source/rebuild/carrier, and registry-absence evidence.
   Keep `kaji-beta-publish` unapproved until every upstream gate is terminal
   green and fresh-token storage has already been explicitly confirmed.

5. Approve the sole `kaji-beta-publish` deployment, `publish-npm`, exactly
   once. There is no separate publisher deployment and no Python publisher.
   Inside this job, exact `npm whoami` equality with `KAJI_NPM_PUBLISHER` is
   the first credentialed action. The job then reverifies the signed tag,
   authorization, rehearsal source artifacts, and current carrier immediately
   before `npm publish --provenance`.

6. Require the final status `npm_byte_verified`. The registry verifier
   downloads the authoritative tarball by exact version and requires its raw
   bytes, SHA-256, SRI, npm signature, provenance, and GitHub attestation to
   match the frozen candidate. It also requires PyPI to remain absent. Only
   then may the exact ordered 27 assets be attached to the GitHub prerelease;
   Python wheel and sdist remain private Actions evidence.

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
- Check the exact npm version through its HTTPS registry endpoint and preserve
  the bounded status, content type, effective URL, redirect count, and parsed
  JSON body. Never classify a version from npm CLI error text. Independently
  preserve the PyPI beta endpoint's HTTP status.

- If `registry-preflight` failed and the npm publisher was skipped, the
  workflow records a no-publication status. Do not yank or deprecate a
  pre-existing collision based on that run; investigate its ownership and
  still choose a new npm beta version.

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
- Treat `kaji-v0.2.0-beta.8` as a burned, immutable TTHW-input attempt.
  Protected run `30296132900` at
  `4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e` passed exact tag and artifact
  verification, Python and Node compatibility, all three raw paired replicas
  and their aggregate, and the 30-minute soak. It then failed closed because
  `KAJI_TTHW_EVIDENCE_JSON` was empty when the protected environment was
  approved, so the required five-user TTHW validation did not start. Provider
  proof, registry and publisher preflight, and npm publication were skipped;
  npm and PyPI remained absent. Never move, retry, approve, or add evidence to
  it, and never reuse its artifacts or participant receipts;
  recovery requires the new beta.9 attempt. Obsolete same-commit rehearsal `30291287818` is
  terminal cancelled and cannot be reused as beta.9 evidence.
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

## Automated TypeScript onboarding evidence

Both protected workflows derive onboarding evidence only from the exact
current-run `kaji-beta-artifacts`, `kaji-node-compat-22`, and
`kaji-node-compat-24` raw REST ZIP bodies. Each archive is selected from the
complete run collection, requeried by exact ID, checked for canonical name,
digest, producer run, head commit, attempt 1, and non-expiration, then hashed
before any member is read.

The unprotected `typescript-onboarding-archive-calibration` job and the
protected `typescript-onboarding-evidence` job independently repeat that
lookup, byte authentication, validation, and aggregate recomputation.
Calibration success is only a prerequisite and Actions diagnostic; the
protected job does not trust calibration output.

The aggregate has exactly two ordered cells:

- Node 22 on GitHub-hosted Linux/x64 `ubuntu-22.04`;
- Node 24 on GitHub-hosted Linux/x64 `ubuntu-24.04`.

Each cell proves npm and Bun installation from the frozen npm tarball,
scaffold initialization, a deterministic no-key run, the ordered Echo
`requested` → `started` → `completed` lifecycle with exact result identity,
and equal cold/warm terminal behavior. A failed, incomplete, mismatched,
wrong-runner, wrong-runtime, byte-different, or cross-attempt receipt fails
closed.

The protected job retains exactly `status.json`, `validation.log`, and
`typescript-onboarding-evidence.json` in
`kaji-typescript-onboarding-evidence`. The same three files replace the prior
onboarding assets one-for-one in provenance and in the 27-asset release
contract. Calibration diagnostics remain Actions-only. No human receipt,
environment secret, extracted-receipt input, or later same-named archive can
substitute for these exact raw current-run sources.

See the [TypeScript onboarding evidence guide](typescript-onboarding-evidence.md)
for the exact two-cell claim boundary, retained fields, and unchanged
installed-artifact Echo snippets.

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
