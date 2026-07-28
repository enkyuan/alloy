# Kaji npm-Only Beta.9 Protected Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development` to implement this plan task by task. Keep the
> release immutable, fail closed, and bound to one reviewed commit and one exact
> npm tarball.

**Goal:** Abandon the unpublished `kaji-v0.2.0-beta.8` attempt without moving or
deleting its signed tag, replace the five-human arm64 macOS TTHW policy with
deterministic current-run exact-artifact npm and Bun onboarding evidence on
GitHub-hosted Linux/x64 runners, and publish the next unused TypeScript beta
(`kaji-sdk@0.2.0-beta.9`) to npm only after the revised policy is reviewed,
landed, and proven by a terminal-green exact-main rehearsal.

**Architecture:** Reuse the existing Node 22/24 compatibility jobs and
`kaji/ts/scripts/smoke_package.mts`; they already install the frozen npm tarball
with both npm and Bun, generate a scaffold, execute token-free no-key and Echo
lifecycle paths, and run cold/warm checks. Strengthen their closed receipts with
runner, invocation, producer-artifact, and phase evidence. Replace the protected
`tthw-evidence` job with an honestly named
`typescript-onboarding-evidence` aggregate behind a distinct
`kaji-beta-onboarding` required-reviewer environment. Keep `kaji-beta` solely
for the later keyed-provider proof so one environment approval cannot race into
authorizing a different job. The aggregate must independently revalidate both
source receipts, the exact candidate manifest, and the exact npm tarball.
After the terminal-green rehearsal, bind that exact artifact and its canonical
evidence bundle into the signed beta.9 tag annotation. The publish workflow may
rebuild for comparison, but it must publish the rehearsed tarball bytes and
must reject any byte mismatch. Preserve all other release gates and keep PyPI
absent.

**Tech stack:** GitHub Actions; GitHub-hosted Ubuntu 22.04 and 24.04 x64 runners;
Node 22/24; npm; Bun 1.3.11; TypeScript; Python 3.14 validation utilities; JSON
Schema; Vitest; pytest; GitButler; token-authenticated first-release npm
publication with publisher-identity checks and npm provenance. Trusted
publishing is a separately configured post-first-release improvement and is
not claimed by this plan.

**Current remote baseline (verified 2026-07-27/28 UTC):**

- `kaji-v0.2.0-beta.8` is a valid signed annotated tag at commit
  `4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e`; the active tag ruleset forbids
  deletion and non-fast-forward updates.
- Publish run `30296132900` is terminal failed before provider, publisher, or
  npm mutation. The beta.8 audit prerelease is explicitly marked unpublished
  and has zero assets.
- npm returns 404 for both `kaji-sdk@0.2.0-beta.8` and
  `kaji-sdk@0.2.0-beta.9`; beta.9 has no tag, workflow run, or GitHub release.
- PyPI returns 404 for `kaji-sdk` and `0.2.0b1`.
- Post-Task-0 environment audit: `kaji-beta-onboarding`, `kaji-beta`, and
  `kaji-beta-publish` have exact reviewer `enkyuan` (`id=90286412`),
  `prevent_self_review=false`, `can_admins_bypass=false`, and only the
  `required_reviewers` plus custom `branch_policy` rule types. Onboarding and
  provider permit branch `main` plus tag `kaji-v0.2.0-beta.9`; publisher
  permits only that exact tag.
- The obsolete beta.8 rehearsal `30291287818` is terminal cancelled and may
  never be reused as beta.9 evidence.
- The user reports that the existing npm granular access token is expired.
  Do not test or expose it. Policy implementation and the exact-main rehearsal
  may proceed, but the tag-triggered publish must stop before its final
  protected publisher job until the user has stored a fresh token as
  `NPM_TOKEN` in `kaji-beta-publish`.
- A concurrent release automation handed off 58 uncommitted beta.9
  identity/incident edits. Preserve and independently verify them; do not
  attribute them to the revised policy until the complete checkpoint is green.

## Non-negotiable invariants

- [ ] Never move, delete, recreate, or reuse `kaji-v0.2.0-beta.8`.
- [ ] Never rerun a burned beta.8 job or accept any beta.8 receipt as beta.9
      evidence.
- [ ] Do not create or push `kaji-v0.2.0-beta.9` until the policy commit is on
      `main` and an unchanged exact-main rehearsal is terminal green.
- [ ] Keep `kaji-beta` as the keyed-provider required-reviewer environment and
      `kaji-beta-publish` as the final publication required-reviewer
      environment. Add the distinct required-reviewer environment
      `kaji-beta-onboarding` for the aggregate proof. Removing a human-input
      secret does not remove a human authorization boundary.
- [ ] Configure and revalidate exact custom deployment policies:
      `kaji-beta-onboarding` and `kaji-beta` permit `main` for rehearsal and
      the exact `kaji-v0.2.0-beta.9` publish tag; `kaji-beta-publish` permits
      only the exact `kaji-v0.2.0-beta.9` tag. Wildcard policies and
      administrator bypass are not acceptable for this release.
- [ ] Never reuse one environment for two sequential jobs. GitHub's pending
      deployment API approves an environment ID rather than a job ID; distinct
      onboarding and provider environments are the structural protection
      against an approval race. Publisher identity verification and publication
      intentionally occur in one final job after one final publish approval.
- [ ] Keep signed annotated tag validation, attempt-1 publication, tag
      immutability/concurrency, exact commit/manifest/artifact binding, Python
      and Node compatibility, three-replica performance, 30-minute soak, keyed
      provider proof, publisher identity, SBOM/provenance attestations,
      registry-absence preflight, and exact npm byte/SRI/signature/provenance
      verification.
- [ ] Do not publish Python. Exact `kaji-sdk==0.2.0b1` absence and the absence
      of every Python publisher job are npm-publication preconditions. The
      final independent check also verifies that the PyPI project remains
      absent.
- [ ] Do not claim human usability, macOS, arm64, Windows, a fully offline
      dependency install, or any runtime/platform combination absent from the
      retained runner receipts.
- [ ] Do not add a second onboarding smoke implementation. Strengthen the
      existing exact-tarball `smoke_package.mts` path.
- [ ] Do not accept summary booleans without revalidating their source receipts.
      Reject mixed run attempts, initial/failure receipts, extra fields, stale
      manifests, and substituted artifacts.
- [ ] Do not expose keys, npm credentials, inherited environments, raw provider
      content, or unbounded command output in logs or receipts.
- [ ] Never attempt npm publication with the reported expired token. Do not
      create, rotate, inspect, or copy a replacement token without separate
      authority; require confirmation that a fresh token is stored before the
      irreversible tag-triggered publish.
- [ ] Use GitButler for branch, diff, checkpoint, push, PR, and landing
      operations. Preserve unrelated work.

## Evidence model

The protected policy proves only these two current-run cells:

| Cell | Configured runner | Measured platform | Runtime | Managers |
| --- | --- | --- | --- | --- |
| 1 | `ubuntu-22.04` | GitHub-hosted Linux/x64 | Node 22 | npm and Bun |
| 2 | `ubuntu-24.04` | GitHub-hosted Linux/x64 | Node 24 | npm and Bun |

Each Node compatibility receipt must close over:

- exact commit, workflow run URL, run attempt, workflow ref/SHA, and job;
- producer `kaji-beta-artifacts` artifact ID and `sha256:` digest;
- for the tag-triggered run, the signed authorized-rehearsal tuple and the
  current-run carrier artifact ID/digest that contains byte-identical files;
- exact `manifest.json` SHA-256 and exact
  `kaji-sdk-0.2.0-beta.9.tgz` name, size, and SHA-256;
- configured runner label, hosted environment, actual OS/architecture, and
  current image OS/version reported by the runner;
- resolved Node, npm, and Bun versions;
- separate npm and Bun proof records emitted only after exact-tarball install,
  scaffold initialization, no-key execution, Echo requested/started/completed
  lifecycle verification, deterministic result/final text, no forbidden
  terminal event, cleanup, and cold/warm execution all pass.

The protected aggregate must contain only a deterministic projection of those
two receipts and the exact candidate manifest. It records each source receipt's
SHA-256 and rejects any mismatch. It does not infer a claim from a phase name or
from a generic compatibility conclusion.

### Rehearsal-to-tag-to-publish binding

The exact-main rehearsal produces two immutable GitHub artifacts:

1. `kaji-beta-artifacts`: wheel, sdist, npm tarball, `manifest.json`, and
   `SHA256SUMS`;
2. the canonical candidate evidence bundle containing compatibility,
   performance/soak, onboarding, provider, and candidate-validation receipts.

The signed annotated beta.9 tag message must be one bounded closed JSON object
containing the rehearsal run ID and attempt, rehearsal workflow SHA, both
artifact IDs and `sha256:` digests, release-manifest SHA-256, npm tarball name,
and npm tarball SHA-256. The tag object already binds this authorization object
to the peeled commit and approved signer.

The publish workflow must:

- parse that signed object with an exact schema and no extra fields;
- query the GitHub API for the rehearsal run and both artifacts by ID;
- require the rehearsal workflow path/SHA, event, attempt, head commit,
  terminal conclusion, artifact names, artifact digests, and non-expiration to
  match the signed tuple;
- download by artifact ID, never by name alone;
- rerun the offline source gate and compare its rebuilt npm tarball bytes to
  the signed rehearsed tarball;
- use the rehearsed artifact directory as the candidate, optionally reuploading
  it as a current-run carrier artifact while retaining both source and carrier
  identities; and
- publish only the signed rehearsed npm tarball bytes.

## Task 0: Preconfigure exact protected environments before workflow edits

This is a blocking external-state prerequisite. GitHub can auto-create a named
environment without protection when a workflow first references it, so the new
environment must exist before the revised workflow is pushed or dispatched.

- [x] Update `kaji-beta` to the exact reviewer allowlist
      `User enkyuan (id=90286412)`, `prevent_self_review=false`,
      `can_admins_bypass=false`, and only the `required_reviewers` plus
      `branch_policy` protection-rule types. Its only policies are branch
      `main` and tag `kaji-v0.2.0-beta.9`.
- [x] Create `kaji-beta-onboarding` with the exact same reviewer/self-review/
      administrator-bypass/rule-type settings and the same exact `main` plus
      beta.9 policies. It has no secrets.
- [x] Update `kaji-beta-publish` to the exact same reviewer/self-review/
      administrator-bypass/rule-type settings with only tag
      `kaji-v0.2.0-beta.9`.
- [x] Do not read, rotate, copy, or move secret values. `kaji-beta` retains only
      its keyed-provider secret boundary. `kaji-beta-publish` retains
      `NPM_TOKEN` and the expected publisher identity configuration.
- [x] Query all three environments and policy collections after mutation.
      Compare the closed normalized snapshots to the exact desired JSON; reject
      an unknown reviewer, rule type, branch/tag policy, bypass setting, or
      environment name.
- [x] Save only non-secret environment-policy evidence in the release work
      report. If repository permissions cannot create or harden these
      environments, stop before changing workflow YAML.

## Task 1: Close beta.8 and verify the beta.9 identity boundary

**Files:**

- Modify: `docs/kaji/releasing.md`
- Modify: `kaji/ts/CHANGELOG.md`
- Modify: all live beta identity files already present in the handed-off
  58-file diff
- Test: `kaji/tests/test_release_task15.py`
- Test: `kaji/ts/tests/release-security.test.ts`

- [x] Recheck that beta.8 npm remains absent, PyPI remains absent, the beta.8
      tag object/commit/signature are unchanged, and rehearsal `30291287818` is
      terminal cancelled.
- [x] Recheck that beta.9 has no tag, release, workflow run, or npm version.
- [x] Audit the handed-off identity diff. Keep beta.8 only in immutable incident
      history and tests protecting that history. Every active workflow, package
      version, tarball constant, lockfile, runtime fixture, registry command,
      install command, schema enum, and user-facing current-version claim must
      use beta.9.
- [x] Produce a pre-commit identity inventory from the final GitButler diff and
      retain an explicit test that protects both sides of the boundary:
      beta.9 is the only active identity, while the exact beta.8 tag/commit/run
      incident remains historical evidence.
- [x] Preserve the beta.8 audit record: exact tag/commit/run, empty old TTHW
      input, skipped downstream jobs, npm/PyPI absence, and prohibition on
      reusing the attempt.
- [x] Keep Python at `0.2.0b1`; do not manufacture a Python beta.9 identity.

Run:

```bash
rg -n '0\.2\.0-beta\.(8|9)|kaji-v0\.2\.0-beta\.(8|9)' \
  .github apps docs kaji package.json bun.lock
```

Expected: beta.8 occurs only in historical incident text/assertions; all live
identity is beta.9.

## Task 2: Add closed runner and onboarding proof to Node receipts

**Files:**

- Modify: `kaji/ts/scripts/smoke_package.mts`
- Modify: `kaji/ts/tests/package-contract.test.ts`
- Modify: `.github/workflows/kaji.publish.yml`
- Modify: `.github/workflows/kaji.rehearsal.yml`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [x] Add failing type/contract tests for the exact success receipt shape:
      `runner`, `invocation`, producer artifact identity, and separate closed
      npm/Bun onboarding proofs.
- [x] Add hostile tests for missing/extra keys, non-hosted environment,
      runner-label/OS/arch drift, workflow SHA drift, wrong Node major, false
      phases, and failure receipts that retain partial passed claims.
- [x] Refactor `runScaffold` to return a typed proof only after every existing
      manager phase passes. Preserve the actual command sequence and behavior.
- [x] Rename `docs-tthw-echo-run` to neutral onboarding/installed-artifact
      terminology. Do not weaken its requested -> started -> completed ->
      observed checks or forbidden failed/exhausted/cancelled-event rejection.
- [x] Populate runner/invocation data only from reviewed workflow inputs and
      GitHub runner variables. Treat missing variables as a protected-mode
      failure; local smoke may emit an explicitly local receipt that protected
      validation rejects.
- [x] Change the Node matrix to the two explicit runner/runtime cells above and
      assert the matrix exactly in workflow tests.
- [x] Thread the offline producer artifact ID/digest into both Node cells and
      receipts. Preserve exact artifact verification before smoke execution.
- [x] Before downloading a producer artifact, query it by ID and require exact
      name, digest, producer run ID/attempt/head commit, and non-expiration.
      Download it by `artifact-ids`; never accept a name-only lookup.
- [x] Grant each Node cell explicit least-privilege `actions: read` and provide
      `github.token` only to its artifact API lookup/download steps. GitHub
      changes unspecified job permissions to `none` once any permission is
      declared; same-run artifact API reads still require `Actions: read`.

Run:

```bash
bun run --cwd kaji/ts test -- \
  tests/package-contract.test.ts tests/release-security.test.ts
bun run --cwd kaji/ts typecheck
```

Expected: focused tests pass and the success receipt is closed; failure receipts
contain no successful onboarding claim.

## Task 3: Replace the human TTHW contract with automated TypeScript onboarding evidence

**Files:**

- Add:
  `kaji/contracts/release/typescript-onboarding-evidence-v1.schema.json`
- Sync-add:
  `kaji/src/kaji/contracts/release/typescript-onboarding-evidence-v1.schema.json`
- Sync-add:
  `kaji/ts/contracts/release/typescript-onboarding-evidence-v1.schema.json`
- Add: `kaji/scripts/validate_compatibility_receipts.py`
- Add: `kaji/scripts/validate_typescript_onboarding_evidence.py`
- Add: `kaji/tests/test_typescript_onboarding_evidence.py`
- Modify: `kaji/scripts/validate_tthw_evidence.py`
- Modify without changing its live TTHW CLI yet:
  `kaji/scripts/validate_release_evidence.py`
- Modify: `kaji/scripts/check_beta_contract.py`
- Modify: `kaji/tests/test_beta_contract.py`
- Modify/migrate non-human coverage from:
  `kaji/tests/test_tthw_composer.py`
- Modify: `kaji/tests/test_beta_release_check.py`
- Modify: `kaji/tests/test_production_beta_docs.py`
- Keep the old TTHW schema, composer, validator, and human-only tests until
  Tasks 4 and 5 have replaced every live consumer.

- [x] First extract the generic closed compatibility-receipt readers,
      hash/binding checks, and validators currently imported from
      `validate_tthw_evidence.py`. Migrate the old TTHW validator and
      `validate_release_evidence.py` to the neutral imports without changing
      their live CLI or behavior; prove parity before adding the new aggregate.
- [x] Define a strict schema with `additionalProperties: false` at every object
      boundary. Require two ordered cells: Node 22 on Ubuntu 22.04 Linux/x64 and
      Node 24 on Ubuntu 24.04 Linux/x64.
- [x] Implement a pure deterministic composer and validator in
      `validate_typescript_onboarding_evidence.py`. The CLI writes atomically
      only after schema and binding validation.
- [x] Authenticate the exact `kaji-beta-artifacts`,
      `kaji-node-compat-22`, and `kaji-node-compat-24` Actions archive bytes
      against their independently obtained REST digests before extraction.
      Reject unsafe/ambiguous ZIP members and derive the manifest, retained
      candidate files, and both immutable receipt byte streams only from those
      authenticated archives. No extracted path or caller-supplied
      document/hash pair is an authenticated input.
- [x] Bind static runner/workflow policy independently, but treat dynamic
      runner image version as a validated observation from the authenticated
      exact-run receipt unless a concrete GitHub-issued corroborating source
      is added. Do not copy receipt values back as trusted CLI inputs.
- [x] Expose pure recomputation and strict-comparison primitives for Task 5.
      Do not replace `validate_release_evidence.py`'s live
      `--tthw-status`/`--tthw-evidence` interface until the workflows and
      approval helper have switched atomically.
- [x] Test mutations for every field, cross-run and cross-attempt substitution,
      wrong workflow SHA, stale commit/manifest/tarball, producer artifact
      ID/digest drift, authorized-rehearsal/source-vs-carrier drift,
      source-receipt hash drift, wrong/missing Node cell,
      runner/platform mismatch, missing/false npm or Bun phase, extra fields,
      nonterminal status, and failure/initial receipt substitution.
- [x] Split `test_tthw_composer.py` deliberately: move its executable Echo
      snippet checks to the new onboarding/docs tests, move its two benchmark
      applicability tests to the existing benchmark test module. Retain the
      human participant/composer/secret tests until Task 5 removes the old
      implementation; do not lose unrelated coverage during cleanup.
- [x] Add the new schema to the canonical-contract inventory alongside the old
      schema/template while they still have live consumers, and synchronize
      both packaged copies from the canonical source.
- [x] Anchor the atomic writer to one no-follow directory descriptor, verify
      the installed inode and bytes before success, and reject parent/temp-name
      substitution. Preserve prior bytes on normal failure. If both a
      post-replace durability step and rollback fail, retain exactly one
      owner-only recovery copy and raise a distinct terminal ambiguous outcome;
      never delete the only recovery evidence or retry automatically.

Run:

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_tthw_evidence.py \
  kaji/tests/test_approve_tthw_gate.py \
  kaji/tests/test_release_task15.py
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_typescript_onboarding_evidence.py \
  kaji/tests/test_beta_contract.py \
  kaji/tests/test_tthw_evidence.py \
  kaji/tests/test_tthw_composer.py \
  kaji/tests/test_release_task15.py
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji --no-sync python \
  kaji/scripts/check_beta_contract.py
```

Expected: all valid current-run fixtures pass; every hostile mutation fails
closed with a stable failure code; old TTHW and release-evidence behavior is
unchanged; packaged contracts equal canonical bytes.

## Task 4: Preserve the protected reviewer transaction without the secret

**Files:**

- Add: `kaji/scripts/approve_typescript_onboarding_gate.py`
- Add: `kaji/tests/test_approve_typescript_onboarding_gate.py`
- Retain until the Task 5 workflow/runbook cutover:
  `kaji/scripts/approve_tthw_gate.py`
- Retain until the Task 5 workflow/runbook cutover:
  `kaji/tests/test_approve_tthw_gate.py`
- Keep the live `docs/kaji/releasing.md` approval instructions unchanged until
  Task 5.

- [x] Port the old helper's exact remote preflight: repository/workflow
      identity, run and attempt, candidate commit/tag where applicable, sole
      waiting job, exact environment ID, required-reviewer policy, deployment
      branch/tag policy, and pending-deployment snapshot.
- [x] Remove all environment-secret read/write and freshness logic. No
      `KAJI_TTHW_EVIDENCE_JSON` replacement is introduced.
- [x] Before approval, stable-read the exact raw producer/Node 22/Node 24
      Actions ZIP archives, terminally match their bytes to the three
      independently obtained REST artifact digests, and validate the exact
      release manifest, tarball, producer identity, and both current-run Node
      receipts derived from those authenticated archives. Repeat the complete
      local archive validation and remote snapshot immediately before the
      approval POST. Require both local and remote normalized snapshots to be
      byte/semantically unchanged. Extracted directories or standalone receipt
      paths are not authenticated substitutes.
- [x] Support two explicit preflight modes. Rehearsal mode requires
      `workflow_dispatch`, `head_branch == main`, `head_sha == expected commit`,
      the rehearsal workflow path/SHA, the required expected-commit workflow
      input having already passed upstream validation, and an exact `main`
      deployment policy. Publish mode requires tag-triggered `push`, attempt 1,
      the exact signed tag/commit, the publish workflow path/SHA, and the exact
      `kaji-v0.2.0-beta.9` tag deployment policy. A rerun, broad policy, or
      ambiguous pending deployment fails closed.
- [x] Approve exactly one `kaji-beta-onboarding` deployment for the exact
      `typescript-onboarding-evidence` job. No later job may use that
      environment, so a concurrent approval cannot advance into keyed provider
      or publisher authorization.
- [x] Test zero GitHub mutations on any validation/preflight failure, one exact
      approval on success, and post-validation race rejection. Treat a
      malformed response after the one POST as an ambiguous result and never
      retry automatically.
- [x] Add a read-only environment-audit path and fixtures proving the three
      environments have the exact allowlisted reviewer, explicitly configured
      `prevent_self_review=false`, `can_admins_bypass=false`,
      deployment policies, and no bypass actors before any rehearsal or publish
      approval is attempted. It must not query a secret endpoint, and every
      GitHub API call must use the reviewed explicit REST API version.
- [x] Expose separate `audit-environments` and `gate` commands. `gate` is a
      complete dry run unless `--approve` is present; mode fixes all workflow,
      job, environment, policy, artifact-name, and tag constants rather than
      accepting them from the caller.
- [x] Treat the new helper as staged and non-live in this checkpoint. Do not
      invoke it against a workflow, delete the old helper/tests, or switch the
      live runbook until Task 5 atomically adds the new protected job.

Run:

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_approve_tthw_gate.py \
  kaji/tests/test_approve_typescript_onboarding_gate.py
```

Expected: all new transaction/race tests pass and no new-helper test handles a
secret value; the old live TTHW helper and its tests remain green and unchanged.

## Task 5: Replace the protected workflow boundary and canonical evidence bundle

**Files:**

- Modify: `.github/workflows/kaji.publish.yml`
- Modify: `.github/workflows/kaji.rehearsal.yml`
- Modify: `.github/actions/verify-kaji-beta-tag/action.yml`
- Modify: `kaji/scripts/validate_release_evidence.py`
- Modify: `kaji/scripts/check_beta_contract.py`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `kaji/tests/test_beta_contract.py`
- Modify: `kaji/ts/tests/release-security.test.ts`
- Modify: `docs/kaji/releasing.md`
- Delete after the new workflow/runbook cutover:
  `kaji/scripts/approve_tthw_gate.py`
- Delete after the new workflow/runbook cutover:
  `kaji/tests/test_approve_tthw_gate.py`
- Delete after the new approval helper and both workflows have no live
  references:
  `kaji/contracts/release/tthw-evidence-v1.schema.json`
- Delete after replacement:
  `kaji/src/kaji/contracts/release/tthw-evidence-v1.schema.json`
- Delete after replacement:
  `kaji/ts/contracts/release/tthw-evidence-v1.schema.json`
- Delete after replacement:
  `kaji/contracts/release/tthw-participant.template.json`
- Delete after replacement:
  `kaji/src/kaji/contracts/release/tthw-participant.template.json`
- Delete after replacement:
  `kaji/ts/contracts/release/tthw-participant.template.json`
- Delete after replacement: `kaji/scripts/compose_tthw_evidence.py`
- Delete after replacement: `kaji/scripts/validate_tthw_evidence.py`
- Delete after migrating retained Echo/benchmark coverage:
  `kaji/tests/test_tthw_evidence.py`
- Delete after migrating retained Echo/benchmark coverage:
  `kaji/tests/test_tthw_composer.py`

- [x] Replace—not alias—`tthw-evidence` with
      `typescript-onboarding-evidence`.
- [x] Add a required `expected-commit` input to the rehearsal
      `workflow_dispatch`. At the first executable boundary, require
      `github.ref == refs/heads/main`,
      `inputs.expected-commit == github.sha`, and a full 40-lowercase-hex
      commit. Export that identity into every downstream receipt. A caller
      cannot dispatch a raw SHA; the workflow must instead be dispatched at
      `main` only after remote `main` equals the reviewed commit.
- [x] Put `typescript-onboarding-evidence` behind
      `environment: kaji-beta-onboarding`. Keep `keyed-proof` behind
      `environment: kaji-beta`. Preserve upstream dependency closure,
      initial-status retention, exact candidate revalidation, terminal
      normalization, and always-retained diagnostics.
- [x] Add a secret-free, unprotected
      `typescript-onboarding-archive-calibration` job on fixed
      `ubuntu-24.04` before the protected onboarding job in both workflows.
      It must independently resolve and authenticate the three exact
      current-run raw ZIP archives, recompute the Task 3b aggregate, retain
      only bounded Actions diagnostics, expose no outputs, and complete
      successfully before the sole onboarding deployment can wait for
      approval. The protected onboarding job must repeat the same lookup,
      raw-byte authentication, validation, and recomputation rather than
      trusting calibration output.
- [x] Assert `kaji-beta-onboarding` occurs exactly once per workflow and only
      on `typescript-onboarding-evidence`; no downstream job may reuse it.
- [x] Download both current-run `kaji-node-compat-22` and
      `kaji-node-compat-24` artifacts plus `kaji-beta-artifacts`; reject mixed
      run attempts and ambiguous files.
- [x] Resolve the candidate and both Node receipt artifacts through the Actions
      artifact API by exact ID. Require name, digest, producer run,
      head commit, attempt, and non-expiration before downloading with
      exact REST archive download URLs. Save and hash the raw ZIP response
      bytes; fail terminally if any archive hash differs from its canonical
      REST digest. Do not rely on `download-artifact`'s warning-only digest
      behavior or reconstruct an archive from extracted files. Record each
      source artifact identity in the aggregate.
- [x] Grant `actions: read` to every job that queries the Actions run/artifact
      API, whether the producer is in the same run or another run. Scope
      `github.token` to the lookup/download steps and pass `github-token`
      explicitly to cross-run downloads. Keep all unrelated job permissions
      unchanged.
- [x] Retain exactly three renamed evidence files:
      `status.json`, `validation.log`, and
      `typescript-onboarding-evidence.json` under
      `kaji-typescript-onboarding-evidence`.
- [x] Update `keyed-proof`, supply-chain/candidate-evidence, provenance
      subjects, release evidence, and all `needs`/`if` closures to require the
      renamed protected job.
- [x] Preserve the exact 27-asset publish evidence cardinality by replacing the
      three old TTHW assets one-for-one; do not retain stale TTHW paths.
- [x] Assert the complete absence of the old secret, participant schema,
      five-human policy, TTHW job/artifact IDs, and TTHW validator arguments
      from active workflows.
- [x] Atomically switch `validate_release_evidence.py` from the old TTHW
      inputs to the exact onboarding status/evidence plus Node source artifact
      IDs/digests. Recompute the aggregate from both raw source receipts and
      reject any non-identical document. The recomputation inputs are the exact
      authenticated producer/Node ZIP byte streams and their REST identities,
      never separately extracted paths.
- [x] After the replacement helper and both workflows pass, require an empty
      active-code reference search for the old secret, schema/template,
      composer, validator, approval helper, job/artifact IDs, and CLI
      arguments. Then remove the old contracts/modules and only the human-only
      tests; keep immutable beta.8 incident history and archived plans.
- [x] In that same cleanup, switch the live runbook from the old approval
      helper to `approve_typescript_onboarding_gate.py`, remove the old schema
      and participant template from `REQUIRED_JSON`/`DATA_DOCUMENTS`, use
      `sync_beta_contracts.py --write` to remove stale packaged copies, and
      re-run the inventory plus byte-sync gates.
- [x] Keep Python compatibility receipts in the canonical evidence bundle even
      though PyPI publication is deferred.
- [x] In the tag-triggered workflow, validate the signed rehearsal
      authorization object before any candidate consumption. Parse only the
      verified, valid `verification.payload`; require the exact four signed tag
      headers plus the recursively key-sorted compact ASCII authorization JSON
      and exactly one terminal LF; and bind its SHA-256, exact rehearsal
      run/attempt/path/SHA, candidate/evidence IDs/names/digests, manifest hash,
      and npm tarball name/hash to separately validated outputs. Requery the
      signed run and both artifacts by exact ID. Run the local offline gate for
      unchanged-source confirmation, byte-compare its npm tarball with the
      authorized rehearsal tarball, then populate the current carrier only
      from the exact rehearsed artifact bytes. Retain signed source, rebuild,
      and current carrier identities separately.
- [x] Upgrade `.github/actions/verify-kaji-beta-tag/action.yml` to reparse the
      signature-bound authorization and revalidate every signed primitive,
      exact rehearsal run, candidate/evidence artifact, and current carrier
      identity immediately before `npm publish` and again before release
      attachment. It must pin the reviewed GitHub media type and REST API
      version and never accept or emit an unvalidated raw JSON payload.
- [x] Change the release-evidence validator to explicit rehearsal/publish
      modes. Require the exact producer, Node 22, and Node 24 raw REST ZIP
      paths plus canonical artifact IDs/digests in both modes; recompute with
      the public Task 3b archive APIs; and reject extracted JSON or IDs alone.
      Publish mode additionally requires the complete signed authorization,
      signed candidate/evidence raw ZIPs, signed npm tarball, and rebuilt npm
      tarball, with exact signed-source/rebuild/current-carrier byte equality.
      Rehearsal mode rejects all signed-source options.
- [x] Remove the separate `publisher-preflight` deployment job. In
      `publish-npm`, behind the sole `kaji-beta-publish` approval, make
      `npm whoami` plus exact expected-identity comparison the first
      credentialed step immediately before final tag/artifact revalidation and
      `npm publish`. Retain a fail-closed publisher-identity receipt on every
      exit. Only this job receives `NPM_TOKEN`; onboarding and provider jobs
      must not receive npm credentials.

Run:

```bash
bun run check:workflows
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_typescript_onboarding_evidence.py \
  kaji/tests/test_release_task15.py \
  kaji/tests/test_beta_contract.py \
  kaji/tests/test_approve_typescript_onboarding_gate.py
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji --no-sync python \
  kaji/scripts/check_beta_contract.py
bun run --cwd kaji/ts test -- tests/release-security.test.ts
bun run --cwd kaji/ts typecheck
actionlint .github/workflows/kaji.rehearsal.yml \
  .github/workflows/kaji.publish.yml
```

Expected: workflow parsing and security tests pass with the same non-TTHW gate
closure, exact calibration/onboarding archive recomputation, signature-bound
authorization, unchanged performance/soak/provider gates, exact 27-asset
contract, and the new protected reviewer boundary.

## Task 6: Correct documentation and claims

**Files:**

- Add/rename: `docs/kaji/typescript-onboarding-evidence.md`
- Delete after replacement: `docs/kaji/tthw-evidence.md`
- Modify: `docs/kaji/releasing.md`
- Modify: `docs/kaji/testing.md`
- Modify: `docs/kaji/README.md`
- Modify: `kaji/RELEASE_MATRIX.md`
- Modify: `SUPPORT.md`
- Modify: `kaji/scripts/smoke_install.py`
- Modify: `kaji/ts/scripts/smoke_package.mts`
- Modify: `kaji/tests/test_production_beta_docs.py`
- Modify: `kaji/ts/tests/docs-contract.test.ts`
- Modify: `kaji/ts/CHANGELOG.md`

- [x] Rehome the canonical Echo snippets first, preserving their markers and
      executable behavior, then update `kaji/scripts/smoke_install.py`,
      `kaji/ts/scripts/smoke_package.mts`, Python docs tests, and TypeScript
      docs-contract tests to the new path. Only after those consumers pass may
      the old TTHW guide be deleted. Do not weaken Python installed-artifact
      compatibility smoke.
- [x] Document the two exact GitHub-hosted Linux/x64 cells, their runtime
      versions, the npm/Bun phases, and the evidence fields.
- [x] State explicitly that the policy is automated compatibility/onboarding
      evidence, not a measurement of five humans or a macOS/arm64 claim.
- [x] Remove active instructions for participant receipts, review windows,
      timing medians/maxima, secret composition, secret byte limits, and the old
      approval helper.
- [x] Preserve the keyed-provider and publisher reviewer instructions and
      npm-only/PyPI-deferred boundary.
- [x] Preserve archived plans as historical records; do not rewrite prior
      design history.

Run:

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_production_beta_docs.py
bun run --cwd kaji/ts test -- tests/docs-contract.test.ts
```

Expected: docs make only evidence-backed claims and embedded snippets execute
unchanged from exact installed artifacts.

## Task 7: Close publisher identity and registry provenance into canonical evidence

**Files:**

- Add: `kaji/contracts/release/publisher-identity-receipt-v1.schema.json`
- Sync-add:
  `kaji/src/kaji/contracts/release/publisher-identity-receipt-v1.schema.json`
- Sync-add:
  `kaji/ts/contracts/release/publisher-identity-receipt-v1.schema.json`
- Modify: `kaji/scripts/check_beta_contract.py`
- Modify: `kaji/scripts/validate_release_evidence.py`
- Modify: `kaji/scripts/verify_published_packages.py`
- Modify: `.github/workflows/kaji.publish.yml`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `kaji/tests/test_beta_contract.py`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [x] Define a strict closed publisher-identity receipt with exact commit, tag,
      workflow run/attempt/path/SHA, expected publisher, actual publisher,
      terminal conclusion, exit code, and failure code. It must never contain a
      token, npm configuration, home path, inherited environment, or raw
      command output.
- [x] In the final publish job, create an initial fail-closed identity receipt
      before setup, normalize it immediately after `npm whoami`, and always
      upload it as a uniquely named current-run artifact. A passed identity
      receipt is necessary but not sufficient for publication success.
- [x] Give the publisher-identity upload step an ID and expose its artifact ID
      digest, and exact unique name as `publish-npm` job outputs. Do not
      rediscover a same-name artifact and assume it is the producer output.
- [x] Make `publication-status` resolve that artifact by exact ID/name/digest/
      run/attempt/head commit, download it by `artifact-ids`, validate it
      against the expected publisher and publish tuple, and hash its raw bytes.
      Embed the normalized identity and raw receipt SHA-256 into the existing
      `publication-status.json`.
- [x] Grant `publication-status` explicit least-privilege `actions: read` and
      pass its scoped `github-token` to artifact API/download operations. Match
      the resolved artifact to the exact ID/digest exported by `publish-npm`.
- [x] Model the path where `publish-npm` never starts because an upstream gate
      fails or the final environment approval is rejected. In that case no raw
      receipt can exist: every publication-status writer must emit a strict
      `publisherIdentity` object with `conclusion: not_run`, a closed reason,
      and a null receipt hash. Only a terminal `npm_byte_verified` state may
      require and contain the passed normalized identity plus raw SHA-256.
- [x] Make `release-evidence` require the closed publisher identity embedded in
      `publication-status.json`. Retain the raw receipt as a workflow artifact,
      not a 28th GitHub Release asset; embedding its normalized fields and
      SHA-256 in the existing publication-status asset preserves the exact
      27-asset release contract. Assert that attachment contract as one exact
      ordered list, not a loose contains check.
- [x] Make `dist.integrity` and `dist.shasum` mandatory closed fields in
      `verify_published_packages.py`. Verify SRI against the downloaded bytes
      as exactly one canonical SHA-512 token and require exactly one
      40-lowercase-hex SHA-1 shasum; absence, ambiguity, or malformed metadata
      fails closed.
- [x] Strengthen the verifier and hostile fixtures so both npm and GitHub
      attestations bind the exact subject digest, source repository, publish
      workflow path, workflow SHA, immutable beta.9 tag ref, and peeled commit.
      A cryptographically valid attestation for a different ref, workflow SHA,
      tag, or subject must fail.
- [x] Verify registry signatures and require the npm signature/provenance audit
      result to identify the exact package version and accepted attestation
      bundle; do not accept the mere presence of an arbitrary bundle.
- [x] Extend the single publication-state writer (or one tested
      post-classification merge) so normal, fallback, partial, skipped, and
      ambiguous status paths preserve or deliberately construct the strict
      publisher-identity subobject. Test missing, skipped, failed,
      artifact-ID/digest-mismatched, malformed, and passed receipts across
      every writer path.
- [x] Update the canonical contract inventory and sync both packaged schema
      copies.

Run:

```bash
uv run --project kaji --no-sync pytest -q \
  kaji/tests/test_release_task15.py kaji/tests/test_beta_contract.py
bun run --cwd kaji/ts test -- tests/release-security.test.ts
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --write
uv run --project kaji --no-sync python \
  kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji --no-sync python \
  kaji/scripts/check_beta_contract.py
```

Expected: hostile publisher/provenance/shasum mutations fail closed; the
publisher receipt is transitively bound into the unchanged 27-asset contract.

## Task 8: Run local gates and independent review

- [x] Run focused Python and TypeScript policy/security tests first.
- [x] Run contract sync/checks, workflow checks, typecheck, lint, package
      contract, and all offline release checks.
- [x] Run the complete repository Kaji gates serially where they share generated
      artifacts.
- [x] Ask one independent reviewer to inspect security/evidence boundaries and
      one independent reviewer to inspect tests/docs/claim scope. Resolve every
      material finding and rerun affected gates.
- [x] Confirm the final diff changes no benchmark threshold, soak duration,
      provider requirement, existing environment protection, publisher
      identity requirement, signing requirement, or registry publication
      target. Provenance and registry-verifier changes must be limited to the
      explicit fail-closed strengthening in Task 7.

Run:

```bash
bun run check:workflows
bun run ci:kaji
bun run ci:local
uv run --project kaji python kaji/scripts/beta_release_check.py --release
```

Expected: all deterministic local gates pass. This remains rehearsal evidence,
not publication authorization.

## Task 9: Checkpoint, review, and land the exact implementation

- [ ] Use `but diff` to refresh change IDs and split only if the inherited
      beta.9 identity history is independently coherent from the policy. Keep
      tests with behavior.
- [ ] Before committing, inventory every handed-off beta.9 file from the
      GitButler diff and verify that no unowned path entered the checkpoint.
      Run the active-beta.9/historical-beta.8 identity contract against the
      exact final diff.
- [ ] Commit to `chore/npm-only-beta9-release` with a conventional,
      purpose-specific message and verified authorship/signature.
- [ ] Push the exact checkpoint, create the GitButler PR, and wait for every
      required hosted check and review.
- [ ] Verify PR head SHA and diff after review. Land only the exact reviewed
      checkpoint, then verify `origin/main` equals the landed SHA.

Suggested checkpoint:

```text
ci(kaji): replace human TTHW with npm onboarding proof
```

## Task 10: Run the unchanged exact-main rehearsal

- [ ] Verify remote `main` equals the exact landed SHA. Dispatch
      `.github/workflows/kaji.rehearsal.yml` with ref `main` and the required
      `expected-commit=<landed SHA>` input. Record run ID, attempt, `head_sha`,
      workflow SHA, and producer artifact ID/digest; require all recorded
      commit values to equal the landed SHA.
- [ ] Before dispatch, audit all three release environments.
      `kaji-beta-onboarding` and `kaji-beta` must have the exact required
      reviewer, `prevent_self_review=false`, `can_admins_bypass=false`, and
      exact custom policies for `main` and `kaji-v0.2.0-beta.9`;
      `kaji-beta-publish` must allow only the exact beta.9 tag policy.
- [ ] Wait for all ungated jobs to pass and for only
      `typescript-onboarding-evidence` to wait at
      `kaji-beta-onboarding`.
- [ ] Download the exact candidate and Node 22/24 receipts by run/artifact IDs.
      Run `approve_typescript_onboarding_gate.py` in dry-run mode, then approve
      exactly that pending deployment after an unchanged-state recheck.
- [ ] Verify the aggregate job and retained evidence terminally pass.
- [ ] Approve the later `kaji-beta` keyed-provider deployment separately and
      require all keyed OpenAI cells to pass. Its distinct environment prevents
      the onboarding approval transaction from authorizing it.
- [ ] Require candidate evidence/supply-chain aggregation to finish terminal
      green. Download and independently validate the retained evidence bundle.
- [ ] Do not edit tracked files after this point. Any tracked change requires a
      new review/landing and a fresh exact-main rehearsal.

## Task 11: Create the signed beta.9 tag and publish npm through protected gates

- [ ] Before creating the tag, require explicit confirmation that the expired
      npm granular token has been replaced in `kaji-beta-publish`. Do not read
      the secret value or use it in a local preflight; the protected job's
      first credentialed step remains the fail-closed `npm whoami` identity
      check.
- [ ] Download and independently verify the terminal rehearsal candidate and
      canonical evidence artifacts by exact IDs. Construct the bounded
      canonical tag-authorization JSON from their API identities and verified
      hashes.
- [ ] Immediately recheck exact `main` SHA, beta.9 tag/release/npm absence,
      beta.8 immutability, exact `kaji-sdk==0.2.0b1` PyPI absence, signing
      identity, environment policies, and repository rules.
- [ ] Create one signed annotated `kaji-v0.2.0-beta.9` tag targeting the exact
      rehearsed SHA, with the canonical rehearsal-authorization JSON as its
      signed message, and push only that tag. Record tag object, peeled commit,
      tagger, authorization tuple, and remote signature verification.
- [ ] Verify the tag-triggered publish run is attempt 1 and bound to the exact
      tag/commit/workflow SHA and signed rehearsal run/artifact/evidence tuple.
- [ ] Require publish `offline-gates` to fetch the authorized rehearsal
      artifact by ID/digest, rerun the offline source gate, prove rebuilt npm
      bytes equal the signed rehearsal bytes, and expose only the rehearsed
      candidate bytes to downstream jobs.
- [ ] Repeat the exact Node-receipt download/local validation and approve only
      the protected TypeScript onboarding deployment.
- [ ] Approve keyed provider proof separately only after the onboarding
      aggregate is terminal green.
- [ ] Approve only `kaji-beta-publish`, after registry absence, supply-chain
      evidence, SBOM, and attestations are green. In that single final job,
      require exact `npm whoami` identity and retain its receipt before
      executing `npm publish`. No other job may use this environment or receive
      `NPM_TOKEN`.
- [ ] Publish only `kaji-sdk@0.2.0-beta.9` with npm provenance. PyPI jobs and
      credentials remain absent.
- [ ] Never rerun a failed publish attempt or reuse beta.9 if its one-way
      attempt is burned; record it and fix forward to the next unused beta.

## Task 12: Independently verify the registry and close the release

- [ ] Download the authoritative npm tarball by exact version, not dist-tag.
- [ ] Compare its raw bytes and SHA-256 with the frozen candidate tarball and
      retained manifest.
- [ ] Run the already-reviewed Task 7 verifier unchanged against the
      authoritative registry responses, downloaded bytes, npm signature audit,
      and GitHub/npm attestations. Do not patch or weaken it after tagging.
- [ ] Verify retained `publication-status.json` is terminal
      `npm_byte_verified` and independently recompute that result.
- [ ] Recheck exact `kaji-sdk==0.2.0b1` and the PyPI project remain absent and
      confirm no Python publisher job or credential path ran.
- [ ] Only after all checks pass, create/update the normal beta.9 GitHub
      prerelease with verified assets and npm-only installation guidance.
- [ ] Report the npm version, exact tarball SHA-256/SRI, publish run, tag object
      and commit, evidence artifact IDs/digests, provenance verification, GitHub
      release URL, and PyPI-absent result.

## Final acceptance checklist

- [ ] beta.8 tag unchanged and unpublished on npm; obsolete rehearsal cancelled.
- [ ] beta.9 policy and identity reviewed and landed on exact `main`.
- [ ] No active human TTHW secret/schema/helper/job/artifact path remains.
- [ ] Two exact GitHub-hosted Linux/x64 Node cells prove npm and Bun onboarding
      from the same frozen tarball.
- [ ] Three purpose-specific reviewer environments are exact and approved
      separately: onboarding, keyed provider, and final publisher.
- [ ] Compatibility, performance, soak, provider, publisher, SBOM,
      attestation, signing, and registry gates are unchanged or stronger.
- [ ] Exact-main rehearsal is terminal green before tag creation.
- [ ] Signed beta.9 tag and publish run bind the rehearsed commit, exact
      candidate/evidence artifact IDs and digests, manifest, and npm tarball
      bytes.
- [ ] npm bytes, SHA-256, SRI, signature, and provenance independently match.
- [ ] PyPI remains absent.
