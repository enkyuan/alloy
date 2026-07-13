# Kaji Python + TypeScript Beta Release Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `kaji` (Python) and `@kaji/sdk` (TypeScript) from internal-test readiness to a defensible production beta by closing the remaining local code gates and proving the exact frozen package bytes through runtime matrices, performance/soak, keyed provider loops, TTHW, signing, provenance, and publication verification.

**Architecture:** Preserve the implemented process-local `AgentBuilder -> AgentRuntime -> provider -> tool execution -> EventCommitter/EventJournal` design. Add no runtime abstraction layer. Close the remaining type and CI gaps, then make every protected consumer verify and execute the single wheel/sdist/npm artifact set produced by the offline release job. Treat beta readiness as an evidence state bound to one immutable commit and artifact manifest.

**Tech Stack:** Python 3.11/3.14, asyncio, Pydantic 2, pytest, Ruff, ty, uv; TypeScript 5.7/current 6.x, Node 22/24, Vitest, tsup, Bun; ast-grep 0.44.1; GitHub Actions; PyPI trusted publishing; npm provenance; GitButler.

**Status:** Implementation plan written from the 2026-07-13 repository audit. Engineering review is required before implementation.

**Supersedes:** This is the remaining-work delta to `docs/superpowers/plans/2026-07-10-kaji-sdk-production-beta.md` and `docs/superpowers/plans/2026-07-11-kaji-sdk-production-beta-gap-closure.md`. It does not reopen completed architecture or contract work.

## Global Constraints

- [ ] Use GitButler for every version-control operation and keep each checkpoint on the implementing agent's dedicated branch.
- [ ] Do not promote GitHub, HTTP, Web, filesystem, SQLite, Gmail, Redis, voice, RAG, native Gemini/Kimi, or tool retrieval into the first beta. Echo remains the only stable integration.
- [ ] Do not add distributed session serialization, durable snapshots, exactly-once external effects, or killable provider isolation. The first beta remains embedded and process-local.
- [ ] Do not weaken a gate with ignores, broad `Any`, checker exclusions, skipped tests, source fallbacks, permissive artifact matching, or best-effort evidence.
- [ ] Never log provider keys, OAuth credentials, TTHW raw secrets, registry tokens, or complete inherited environments.
- [ ] Never commit `.artifacts/`, temporary virtual environments, generated package archives, provider evidence containing secrets, or local benchmark output.
- [ ] Full benchmark, soak, compatibility, TTHW, and provider evidence bind the exact candidate commit and `manifest.json` hashes they name. Calibration separately records artifact set A provenance; baseline applicability to candidate B binds benchmark source, dependency, toolchain, and pinned-runner fingerprints rather than B's manifest.
- [ ] Any tracked change after a protected candidate run invalidates the affected candidate evidence. After calibration, recalibrate only when the benchmark applicability fingerprint changes; always rebuild and rerun affected candidate gates for changed package bytes.
- [ ] A successful local `beta_release_check.py --release` means offline rehearsal only. It does not authorize a tag, push, registry publication, or beta claim.
- [ ] Do not create or push a signed tag and do not publish to PyPI/npm without a separate, explicit user instruction after every required evidence row is green.

---

## 1. Release Outcome and Boundaries

The first beta is ready only when one immutable commit has all of the following:

- zero Python type diagnostics and green Python lint/tests;
- green TypeScript build, typecheck, lint, declarations, package contract, and tests from a clean checkout;
- all canonical contracts, integration schemas/ABIs, registry copies, and cross-SDK scenarios synchronized;
- live OpenAI and Anthropic tool-loop proofs in both SDKs using the stable default event committer;
- the same wheel, sdist, and npm tarball verified and consumed by Python 3.11/3.14 and Node 22/24;
- calibrated full performance evidence and a 30-minute soak on the pinned Linux/x64 runner from those package bytes;
- exactly five fresh time-to-hello-world (TTHW) receipts spanning macOS, Linux, Python, npm, and Bun and bound to the same manifest;
- an approved signed tag, SBOM/provenance/attestations, registry publication, and byte-exact post-publication verification.

### Milestones

1. **Internal test-ready:** Tasks 1-4 are green. Both SDKs may enter broad internal testing.
2. **Beta release-candidate ready:** Tasks 5-9 are green on one immutable commit. The commit may be proposed for a signed beta tag.
3. **Published beta:** Task 10 completes after separate user authorization. PyPI/npm bytes match the frozen artifacts and the release evidence bundle is attached.

### NOT in scope

- Raising coverage to a guessed percentage. After beta, measure current branch/line coverage and introduce a non-decreasing ratchet in a separate change.
- Broad GitHub/Gmail integration promotion or new provider support.
- A second release implementation, two-clone reproducible-build system, or hermetic build farm. Artifact verification and same-run consumption are the beta requirement; independent reproducibility is a post-beta supply-chain improvement.
- macOS performance calibration. The pinned Linux/x64 runner remains authoritative; macOS is represented in TTHW.
- Product behavior changes while repairing types, tests, workflows, or evidence binding.

---

## 2. What Already Exists

Reuse these components; do not replace them:

- `kaji/scripts/beta_release_check.py` already orders local release construction, tests, package audits, archive smoke, npm packing, metadata, and checksum generation.
- `kaji/scripts/verify_release_artifacts.py` already rejects wrong commits, names, versions, build tools, sizes, hashes, extra files, symlinks, and checksum drift.
- `kaji/scripts/release_smoke.py` and `kaji/ts/scripts/smoke_package.mts` already exercise installed archives, public exports, stable CLI flows, no-key scaffolds, optional-provider boundaries, and cold/warm output.
- `kaji/scripts/{run_beta_benchmarks,run_beta_soak,live_provider_proof,validate_tthw_evidence}.py` already define the performance, soak, four-cell provider, and five-user evidence shapes.
- `.github/workflows/kaji.beta.yml` already orchestrates protected rehearsal; `.github/workflows/kaji.beta-publish.yml` already verifies signed tags, builds supply-chain evidence, gates publishers, publishes, checks registry bytes, handles partial incidents, and attaches release evidence.
- `kaji/scripts/check_sdk_parity.py`, the canonical contract/schema synchronizers, the integration ABI checker, and the 37 ast-grep guards already cover cross-SDK semantics and structural invariants.
- Python and TypeScript release-security tests already parse workflows and enforce action pins, permissions, dependency closure, fail-closed steps, and retained evidence.

The implementation should extend these seams rather than create a parallel release CLI, workflow, manifest, evidence schema, or provider harness.

---

## 3. Current Evidence

| Area                         | Confirmed state                                                                                                                       | Remaining blocker                                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Python behavior              | 1,659 tests were previously exercised; the four stale fixture/docs failures now pass                                                  | `scripts/check_types.py` reports 71 diagnostics: 22 in source and 49 in tests                                   |
| TypeScript behavior          | 1,441 passed, 16 skipped; clean build and declaration/package/runtime-builder checks pass                                             | PR workflow runs artifact-consuming tests without first building `dist/`                                        |
| Cross-SDK contracts          | 67/67 canonical parity scenarios pass; integration contracts, registry copies, schemas, and ABIs are synchronized                     | `kaji/RELEASE_MATRIX.md` still claims 59 scenarios                                                              |
| Structure/performance design | 37/37 ast-grep guards pass; bounded concurrency/deadlines, linear streaming, session commits, and incremental context are implemented | Baseline is still `uncalibrated`; protected full benchmark and soak are not retained evidence                   |
| Provider proofs              | Python and TypeScript live tests assert one requested/completed tool call with matching IDs and final text                            | TypeScript live tests inject deprecated `EventBus`; protected proof runs the checkout, not frozen package bytes |
| Release system               | Artifact manifest, checksums, TTHW validation, signed-tag checks, SBOM/provenance, publication, and byte verification exist           | Compatibility and performance jobs rebuild/use the checkout; provider jobs use source test suites               |
| External evidence            | Workflows declare Python 3.11/3.14, Node 22/24, four provider cells, five-user TTHW, and protected publishing                         | Required protected runs, human receipts, credentials, signed tag, and registry evidence remain pending          |

The architecture is valid for an embedded, process-local beta. No evidence supports a rewrite. The only new system-design correction is to close the identity gap between “built artifact” and “thing actually exercised” in protected jobs.

---

## 4. Proposed Design Decisions

1. **One artifact set per run.** `offline-release`/`offline-gates` builds exactly one wheel, one sdist, and one npm tarball under `.artifacts/kaji-release`, then writes `manifest.json` and `SHA256SUMS`.
2. **Verification precedes consumption.** Every downstream job downloads that artifact set, runs `verify_release_artifacts.py` against the exact commit, and records the manifest SHA-256 before installation or execution.
3. **Protected means package bytes.** In protected mode, performance, soak, compatibility, and live-provider commands require `--artifacts-dir`; source/editable fallback is a hard error.
4. **Source harness, installed runtime.** Benchmark/proof drivers may remain reviewed repository scripts, but their Python interpreter and TypeScript package resolution must point to isolated installations of the frozen wheel/npm tarball. Evidence records resolved module paths and artifact hashes.
5. **Stable committer only.** Live TypeScript proofs call `.build({ store })` and exercise the builder's `InMemoryEventCommitter` default. The deprecated bus compatibility path is not beta evidence.
6. **No behavior changes for typing.** Type repairs use exact protocols, `TypedDict`, literal narrowing, explicit keyword arguments, and typed fixtures. They do not change runtime branching, public signatures, failure codes, or integration stability.
7. **Narrow secret environments.** Each provider child receives only the selected provider credential/model plus an explicit operating-system/network allowlist. The other provider key and unrelated secrets are absent.
8. **Receipts are machine-readable and fail closed.** Compatibility, performance, soak, provider, TTHW, and publication receipts name the commit, workflow run, manifest hash, artifact hash, runtime version, conclusion, and failure code.
9. **Calibration is last code-adjacent work.** Calibrate only after Tasks 1-8 are merged. Commit only the reviewed baseline, then freeze the candidate commit and rerun all affected evidence.
10. **Publication is a separate authority boundary.** Green evidence permits proposing a signed tag; it never implicitly authorizes one.

---

## 5. Target Release Flow

```text
PR commit
  -> beta PR gate
       contracts + integration schemas/ABI + parity + ast-grep
       Python type/lint/tests
       TypeScript build + type/lint/tests
  -> pinned-runner calibration commit
  -> freeze candidate commit
  -> offline release job builds exactly once
       wheel + sdist + npm tgz + manifest + SHA256SUMS
  -> same-run artifact fan-out
       |-> Python 3.11/3.14 consume-only smoke receipts
       |-> Node 22/24 consume-only smoke receipts
       |-> installed-artifact benchmark + 30-minute soak receipts
       |-> five-user TTHW manifest-bound receipts
       +-> four installed-artifact provider-loop receipts
  -> explicit approval boundary
  -> annotated signed tag
  -> verify tag -> reverify same artifacts -> SBOM/provenance
  -> explicit protected publication approvals
  -> PyPI + npm
  -> download and byte-compare published packages
  -> attach final evidence bundle
```

### Evidence identity

```text
release commit
    |
    v
manifest.json --sha256--> releaseManifestSha256
    |
    +--> wheel sha256 --------> Python compat / benchmark / soak / provider / TTHW
    +--> sdist sha256 --------> Python compat / TTHW
    +--> npm tgz sha256 ------> Node compat / benchmark / soak / provider / TTHW

Receipt acceptance requires:
  receipt.commit == manifest.commit == workflow candidate commit
  receipt.releaseManifestSha256 == sha256(manifest.json)
  receipt.artifactSha256 == manifest.artifacts[file].sha256
  receipt.conclusion == "passed"
```

---

## 6. File Responsibility Map

| Responsibility                       | Files                                                                                                                                                                                                                                                |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python type closure                  | `kaji/src/kaji/cli/{connect,disconnect,list_integrations}.py`, `kaji/src/kaji/integrations/{__init__,copy,recovery}.py`, `kaji/src/kaji/integrations/registry/github/{client,github}.py`, `kaji/src/kaji/runtime/tools/execution.py`, matching tests |
| Stable TypeScript live proof         | `kaji/ts/tests/integration/{openai-tools,anthropic-live}.test.ts`, `kaji/ts/tests/release-security.test.ts`                                                                                                                                          |
| Clean PR build order                 | `.github/workflows/kaji.beta-pr.yml`, `kaji/ts/tests/release-security.test.ts`                                                                                                                                                                       |
| Executable contract counts           | `kaji/RELEASE_MATRIX.md`, `kaji/tests/test_stability_contract.py`                                                                                                                                                                                    |
| Artifact identity/consume-only smoke | `kaji/scripts/verify_release_artifacts.py`, `kaji/scripts/release_smoke.py`, `kaji/tests/{test_release_smoke,test_release_task15}.py`                                                                                                                |
| Installed runtime harness            | new `kaji/scripts/installed_release_runtime.py`, `kaji/ts/src/testing.ts`, benchmark/soak drivers and tests                                                                                                                                          |
| Installed provider proof             | new `kaji/scripts/installed_provider_proof.py`, new `kaji/ts/scripts/installed-provider-proof.mts`, `kaji/scripts/live_provider_proof.py`, `kaji/tests/test_live_gate.py`                                                                            |
| Protected orchestration              | `.github/workflows/{kaji.beta,kaji.beta-publish,kaji.benchmark}.yml`, Python workflow tests, TypeScript release-security tests                                                                                                                       |
| Calibration/evidence                 | `kaji/benchmarks/beta-baseline.json`, generated protected receipts under untracked `.artifacts/`                                                                                                                                                     |

---

## 7. Implementation Tasks

### Task 1: Close the Python type gate without behavior changes

**Files:**

- Modify: `kaji/src/kaji/cli/connect.py`
- Modify: `kaji/src/kaji/cli/disconnect.py`
- Modify: `kaji/src/kaji/cli/list_integrations.py`
- Modify: `kaji/src/kaji/integrations/__init__.py`
- Modify: `kaji/src/kaji/integrations/copy.py`
- Modify: `kaji/src/kaji/integrations/recovery.py`
- Modify: `kaji/src/kaji/integrations/registry/github/client.py`
- Modify: `kaji/src/kaji/integrations/registry/github/github.py`
- Modify: `kaji/src/kaji/runtime/tools/execution.py`
- Modify: `kaji/tests/cli/test_add.py`
- Modify: `kaji/tests/test_github_client.py`
- Modify: `kaji/tests/test_github_registry.py`
- Modify: `kaji/tests/test_integration_failures.py`
- Modify: `kaji/tests/test_integrations_oauth.py`

- [ ] **Step 1: Capture the red type baseline.**

  Run:

  ```bash
  uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise
  ```

  Expected: exit 1 with exactly `Found 71 diagnostics`; retain the output as the task baseline.

- [ ] **Step 2: Repair CLI and integration-copy typing at the real boundaries.**
  - Give the custom `argparse.Action.__call__` implementations the exact base signature, including `values: str | Sequence[Any] | None`.
  - Remove the untyped `**kwargs` action constructor in `disconnect.py`; pass `nargs=0` at registration.
  - Add `TypedDict` rows for integration/auth JSON rather than indexing `dict[Unknown, Unknown]`.
  - Use one relative `Manifest` import under `TYPE_CHECKING` so `src.integrations.Manifest` and `kaji.integrations.Manifest` cannot diverge.
  - Type the JSON Schema validator as `jsonschema.protocols.Validator`, narrow located paths before `Path(...)`, and narrow schema-validated file names to `str`.
  - Use explicit `isinstance` guards before reading recovery metadata.

- [ ] **Step 3: Repair GitHub client protocols and async scheduling.**
  - Define the structural HTTP protocol with the exact async request/response types consumed by `GitHubClient`.
  - Match the injected client protocol signatures in `github.py` exactly.
  - Wrap injected `_sleep()` in a local coroutine before `asyncio.create_task`; do not widen `create_task` or cast an arbitrary `Awaitable`.
  - Type `ScriptedHttp`, registry inspection fixtures, JSON mappings, and intentionally invalid token fixtures in tests.

- [ ] **Step 4: Repair event failure and OAuth fixture typing.**
  - Replace `**dict[str, str]` construction of failure events with explicit `reason_code`, `recovery_code`, and `doc_url` keywords so boolean/literal fields cannot receive strings.
  - Give hostile exception fixtures a typed test subclass instead of assigning attributes to `RuntimeError`.
  - Type shared event dictionaries as `dict[str, Any]` only at the test mutation boundary, then validate through the production schema.
  - Preserve exact OAuth state/status literals, the credential-store parameter name, the `cancellation` keyword, and narrowed wire tokens.

- [ ] **Step 5: Run the focused behavior suite.**

  ```bash
  env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GEMINI_API_KEY -u OPENROUTER_API_KEY \
    uv run --project kaji --no-sync pytest -q \
      kaji/tests/cli/test_add.py kaji/tests/cli/test_connect.py \
      kaji/tests/test_github_client.py kaji/tests/test_github_registry.py \
      kaji/tests/test_integration_failures.py kaji/tests/test_integrations_oauth.py
  ```

  Expected: at least the previously observed 133 focused tests pass; no keyed integration test runs.

- [ ] **Step 6: Prove the type gate and full Python suite.**

  ```bash
  uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise
  uv run --project kaji --no-sync ruff check kaji/src kaji/tests
  uv run --project kaji --no-sync pytest -m "not integration" kaji
  ```

  Expected: zero type diagnostics, zero Ruff errors, and no test failures.

- [ ] **Step 7: Commit the coherent type closure.**

  ```text
  fix(sdk): close Python beta type gate
  ```

### Task 2: Move TypeScript live proofs onto the stable event committer

**Files:**

- Modify: `kaji/ts/tests/integration/openai-tools.test.ts`
- Modify: `kaji/ts/tests/integration/anthropic-live.test.ts`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [ ] **Step 1: Add a deterministic structural regression test.**

  Add a release-security test that reads both live proof files and requires:

  ```ts
  expect(source).not.toContain("import { EventBus }");
  expect(source).not.toMatch(/\.build\(\{[^}]*\bbus:/s);
  expect(source).toMatch(/\.build\(\{\s*store(?:\s*:|\s*\})/s);
  ```

  Run:

  ```bash
  bun run --cwd kaji/ts test tests/release-security.test.ts
  ```

  Expected before implementation: the new test fails on both live proof files.

- [ ] **Step 2: Remove the compatibility bus from live proofs.**
  - Delete the `EventBus` imports.
  - Build with `.build({ store })` so the builder creates `InMemoryEventCommitter` through the stable default path.
  - Preserve the existing assertions: exactly one requested event, exactly one completed event, matching tool-call IDs, final text, and no failed/exhausted terminal.

- [ ] **Step 3: Run deterministic TypeScript gates.**

  ```bash
  bun run --cwd kaji/ts build
  bun run --cwd kaji/ts test tests/release-security.test.ts tests/runtime-builder.test.ts
  ```

  Expected: build succeeds and both test files pass without provider credentials.

- [ ] **Step 4: Defer real calls to the protected proof.**

  Do not run paid live tests from a developer shell unless explicitly requested. Task 8 will exercise both files with protected credentials and retained receipts.

- [ ] **Step 5: Commit.**

  ```text
  test(ts): prove live loops through stable committer
  ```

### Task 3: Build TypeScript before artifact-consuming PR tests

**Files:**

- Modify: `.github/workflows/kaji.beta-pr.yml`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [ ] **Step 1: Make the workflow contract fail first.**

  Insert this command into `requiredGateCommands` immediately before the TypeScript test command and change the expected step count from 13 to 14:

  ```text
  uv run --project kaji --no-sync python kaji/scripts/offline_gate.py -- bun run --cwd kaji/ts build
  ```

  Run the release-security test and confirm it fails because the workflow lacks the command.

- [ ] **Step 2: Add the fail-closed build step.**

  Add `Build TypeScript package offline` immediately before `Run TypeScript tests offline` in `.github/workflows/kaji.beta-pr.yml`. Keep the offline wrapper, pinned Bun setup, read-only permissions, and no `continue-on-error`.

- [ ] **Step 3: Prove clean-checkout ordering.**

  ```bash
  rm -rf kaji/ts/dist
  bun run --cwd kaji/ts test tests/release-security.test.ts
  bun run --cwd kaji/ts build
  bun run --cwd kaji/ts test tests/public-declarations.test.ts tests/package-contract.test.ts tests/runtime-builder.test.ts
  ```

  Expected: the workflow contract passes; build recreates `dist`; all artifact-consuming tests pass. Do not commit `dist`.

- [ ] **Step 4: Commit.**

  ```text
  ci(kaji): build TypeScript before beta PR tests
  ```

### Task 4: Make the parity count and schema gate executable documentation

**Files:**

- Modify: `kaji/RELEASE_MATRIX.md`
- Modify: `kaji/tests/test_stability_contract.py`

- [ ] **Step 1: Add a failing count-sync test.**

  Load `kaji/contracts/parity/scenarios.json`, compute `len(document["scenarios"])`, parse a single marker from the release matrix, and assert equality. Use:

  ```markdown
  <!-- beta-parity-scenarios: 67 -->
  ```

  Expected before the documentation change: the test fails because the marker is absent and the prose still says 59.

- [ ] **Step 2: Update the release matrix.**
  - Add the machine marker next to the cross-SDK parity row.
  - Change `59 deterministic scenarios` to `67 deterministic scenarios`.
  - Do not hand-copy the count into another file.

- [ ] **Step 3: Re-run all contract and integration schema gates.**

  ```bash
  uv run --project kaji --no-sync pytest -q kaji/tests/test_stability_contract.py
  uv run --project kaji --no-sync python kaji/scripts/sync_beta_contracts.py --check
  uv run --project kaji --no-sync python kaji/scripts/sync_integration_contracts.py --check
  uv run --project kaji --no-sync python kaji/scripts/check_integration_abi.py --explain
  uv run --project kaji --no-sync python kaji/scripts/check_sdk_parity.py
  bun run audit:ast-grep
  ```

  Expected: 67 parity scenarios pass, all synchronized copies are unchanged, ABI validation passes, and 37 structural guards pass.

- [ ] **Step 4: Commit.**

  ```text
  docs(kaji): bind release matrix to parity fixtures
  ```

### Task 5: Add a verified consume-only path for frozen release artifacts

**Files:**

- Modify: `kaji/scripts/verify_release_artifacts.py`
- Modify: `kaji/scripts/release_smoke.py`
- Modify: `kaji/tests/test_release_smoke.py`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `.github/workflows/kaji.beta.yml`
- Modify: `.github/workflows/kaji.beta-publish.yml`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [ ] **Step 1: Return verified artifact identity from the existing verifier.**

  Keep the current CLI behavior, but have `verify(...)` return an immutable value:

  ```python
  @dataclass(frozen=True)
  class VerifiedReleaseArtifacts:
      root: Path
      commit: str
      manifest_sha256: str
      python_wheel: Path
      python_sdist: Path
      npm_tarball: Path
      artifact_sha256: Mapping[str, str]

  def verify(artifacts: Path, expected_commit: str) -> VerifiedReleaseArtifacts: ...
  ```

  The verifier must continue rejecting extra files, symlinks, malformed manifests, mismatched tool versions, wrong commit/version, unsafe names, size/hash drift, and checksum drift.

- [ ] **Step 2: Test consume-only Python smoke before implementing it.**

  Add tests proving that `release_smoke.py --artifacts-dir DIR`:
  - requires exactly one verified wheel and sdist;
  - never calls `uv build` or deletes/recreates package outputs;
  - runs archive verification and installed wheel/sdist smoke against the supplied paths;
  - rejects a missing, extra, symlinked, or hash-mismatched artifact;
  - prints one JSON receipt containing commit, manifest hash, artifact hashes, Python version, and `conclusion`.

- [ ] **Step 3: Split build and consume phases without duplicating smoke logic.**

  Refactor `release_smoke(dist_dir)` into:

  ```python
  def build_archives(dist_dir: Path) -> tuple[Path, Path]: ...
  def smoke_archives(wheel: Path, sdist: Path, *, identity: ArtifactIdentity) -> dict[str, object]: ...
  ```

  Existing local behavior builds then calls `smoke_archives`. `--artifacts-dir` verifies the release manifest and calls only `smoke_archives`.

- [ ] **Step 4: Make compatibility matrices consume the upstream artifacts.**

  In both rehearsal and publish workflows:
  - make Python/Node compatibility jobs depend on the successful artifact-producing job;
  - download `kaji-beta-artifacts` into `.artifacts/kaji-release`;
  - re-run `verify_release_artifacts.py` with the candidate commit;
  - run Python smoke with `--artifacts-dir .artifacts/kaji-release`;
  - run `bun kaji/ts/scripts/smoke_package.mts .artifacts/kaji-release/kaji-sdk-0.2.0-beta.1.tgz` instead of `package:smoke`;
  - retain one compatibility receipt per matrix cell, even on failure.

- [ ] **Step 5: Prove workflow dependency, order, and no-rebuild contracts.**

  Extend Python workflow tests and `release-security.test.ts` to assert artifact download/verification precedes smoke and that compatibility sections contain none of:

  ```text
  uv build
  npm pack
  bun run package:smoke
  scripts/release_smoke.py          # without --artifacts-dir
  ```

- [ ] **Step 6: Run focused gates and commit.**

  ```bash
  uv run --project kaji --no-sync pytest -q \
    kaji/tests/test_release_smoke.py kaji/tests/test_release_task15.py
  bun run --cwd kaji/ts test tests/release-security.test.ts
  ```

  ```text
  ci(kaji): smoke frozen artifacts across runtime matrices
  ```

### Task 6: Run protected benchmarks and soak from installed package bytes

**Files:**

- Create: `kaji/scripts/installed_release_runtime.py`
- Modify: `kaji/scripts/run_beta_benchmarks.py`
- Modify: `kaji/scripts/beta_benchmark_gate.py`
- Modify: `kaji/scripts/run_beta_soak.py`
- Modify: `kaji/scripts/beta_soak_gate.py`
- Modify: `kaji/benchmarks/python/runtime_benchmark.py`
- Modify: `kaji/benchmarks/python/runtime_soak.py`
- Modify: `kaji/ts/benchmarks/runtime-benchmark.ts`
- Modify: `kaji/ts/benchmarks/runtime-soak.ts`
- Modify: `kaji/ts/src/testing.ts`
- Modify: `kaji/tests/test_beta_release_check.py`
- Modify: `kaji/ts/tests/package-contract.test.ts`

- [ ] **Step 1: Specify and test installed runtime isolation.**

  The new helper exposes one context manager:

  ```python
  @contextmanager
  def installed_release_runtime(
      artifacts_dir: Path,
      *,
      expected_commit: str,
      include_providers: bool = False,
  ) -> Iterator[InstalledReleaseRuntime]: ...
  ```

  `InstalledReleaseRuntime` provides the isolated Python executable, TypeScript work directory, resolved Python `kaji.__file__`, resolved TypeScript package root, manifest hash, and selected artifact hashes.

  Tests must prove both resolved package roots live under the temporary installed runtime and not under `kaji/src`, `kaji/ts/src`, `kaji/ts/dist`, or the repository's workspace link.

- [ ] **Step 2: Export only the test/benchmark seam needed by the installed TypeScript harness.**

  Rewrite benchmark imports to use `@kaji/sdk` and `@kaji/sdk/testing`. Add the minimum deterministic clocks, IDs, mock providers, and in-memory runtime helpers to `src/testing.ts`; do not add them to the root stable export.

  Add package-contract tests that install the npm tarball and import the new testing exports through ESM and CommonJS.

- [ ] **Step 3: Require artifact identity in protected benchmark mode.**

  Add `--artifacts-dir` to `run_beta_benchmarks.py` and `run_beta_soak.py`. In protected mode it is required; in quick local mode it is optional and the existing source harness remains available.

  `beta_benchmark_gate.py` and `beta_soak_gate.py` receipts add:

  ```json
  {
    "releaseManifestSha256": "<64 lowercase hex>",
    "artifacts": {
      "python": { "file": "kaji-0.2.0b1-py3-none-any.whl", "sha256": "..." },
      "typescript": { "file": "kaji-sdk-0.2.0-beta.1.tgz", "sha256": "..." }
    },
    "resolvedPackages": { "python": "<isolated path>", "typescript": "<isolated path>" }
  }
  ```

- [ ] **Step 4: Fail closed on source fallback or identity drift.**

  Add tests for missing `--artifacts-dir`, wrong commit, changed manifest, changed tarball, source-resolved module, mismatched benchmark/soak artifact identity, and missing receipt fields.

- [ ] **Step 5: Run quick deterministic regressions.**

  ```bash
  uv run --project kaji --no-sync pytest -q kaji/tests/test_beta_release_check.py
  bun run --cwd kaji/ts build
  bun run --cwd kaji/ts test tests/package-contract.test.ts tests/runtime-complexity.test.ts tests/runtime-faults.test.ts
  uv run --project kaji --no-sync python kaji/scripts/run_beta_benchmarks.py --quick
  ```

  Expected: installed-runtime negative cases pass, package exports remain valid, and quick performance/fault gates remain green.

- [ ] **Step 6: Commit.**

  ```text
  perf(kaji): bind protected evidence to release artifacts
  ```

### Task 7: Run all four keyed provider cells from installed package bytes

**Files:**

- Create: `kaji/scripts/installed_provider_proof.py`
- Create: `kaji/ts/scripts/installed-provider-proof.mts`
- Modify: `kaji/scripts/live_provider_proof.py`
- Modify: `kaji/tests/test_live_gate.py`
- Modify: `kaji/tests/test_beta_release_check.py`
- Modify: `kaji/ts/tests/package-contract.test.ts`

- [ ] **Step 1: Extract one SDK-neutral proof contract.**

  Each installed runner accepts `--provider openai|anthropic` and must emit one JSON object proving:
  - provider/model selected;
  - exactly one normalized `tool.call.requested`;
  - exactly one normalized `tool.call.completed`;
  - matching non-empty tool-call IDs;
  - expected deterministic Echo result;
  - non-empty final assistant text;
  - no failed, cancelled, timed-out, or exhausted terminal;
  - resolved package path under the isolated artifact runtime.

- [ ] **Step 2: Replace source-test commands in `live_provider_proof.py`.**

  Add required protected arguments:

  ```text
  --artifacts-dir .artifacts/kaji-release
  --expected-commit $KAJI_RELEASE_COMMIT
  ```

  Use `installed_release_runtime(..., include_providers=True)` once, then invoke four cells: Python/OpenAI, TypeScript/OpenAI, Python/Anthropic, TypeScript/Anthropic.

- [ ] **Step 3: Construct a narrow child environment.**

  Start from an explicit allowlist containing only required process/network variables (`PATH`, `HOME`, temp directory, certificate/proxy variables, locale), the selected provider key, and the selected model variable. Never copy the complete parent environment. Assert the other provider key and all common registry/cloud secrets are absent.

- [ ] **Step 4: Bind every proof row to package identity.**

  Extend each evidence row with `model`, `artifactFile`, `artifactSha256`, `releaseManifestSha256`, and `resolvedPackage`. The top-level conclusion is `passed` only when all four rows pass with identical commit/manifest identity.

- [ ] **Step 5: Cover failure and redaction behavior without paid calls.**

  Unit tests use fake child commands and verify missing key, invalid commit, artifact mismatch, one failed cell, malformed receipt, source-resolved package, environment leakage, interruption, and evidence write failure. Captured stdout/stderr must not contain fake secret values.

- [ ] **Step 6: Run deterministic tests and commit.**

  ```bash
  uv run --project kaji --no-sync pytest -q \
    kaji/tests/test_live_gate.py kaji/tests/test_beta_release_check.py
  bun run --cwd kaji/ts build
  bun run --cwd kaji/ts test tests/package-contract.test.ts tests/release-security.test.ts
  ```

  Do not run live calls here.

  ```text
  test(kaji): prove providers from installed artifacts
  ```

### Task 8: Rewire protected workflows around one artifact fan-out

**Files:**

- Modify: `.github/workflows/kaji.beta.yml`
- Modify: `.github/workflows/kaji.beta-publish.yml`
- Modify: `.github/workflows/kaji.benchmark.yml`
- Modify: `kaji/tests/test_release_task15.py`
- Modify: `kaji/ts/tests/release-security.test.ts`

- [ ] **Step 1: Make protected jobs depend on the artifact producer.**
  - Publish `performance`, `python-compat`, `node-compat`, `tthw-evidence`, and `keyed-proof` depend on `offline-gates` in addition to their current safety dependencies.
  - Rehearsal compatibility/TTHW/keyed jobs depend on `offline-release`.
  - Benchmark calibration builds/verifies one release artifact set before running installed-artifact calibration.

- [ ] **Step 2: Download, verify, and pass artifacts explicitly.**

  Every consumer uses the pinned `actions/download-artifact` revision, downloads only `kaji-beta-artifacts`, verifies the expected commit, and passes `.artifacts/kaji-release` explicitly. Performance and provider command lines become:

  ```bash
  uv run --project kaji --no-sync python kaji/scripts/run_beta_benchmarks.py \
    --full --protected --artifacts-dir .artifacts/kaji-release
  uv run --project kaji --no-sync python kaji/scripts/run_beta_soak.py \
    --minutes 30 --protected --artifacts-dir .artifacts/kaji-release
  uv run --project kaji --no-sync python kaji/scripts/live_provider_proof.py \
    --artifacts-dir .artifacts/kaji-release --expected-commit "$KAJI_RELEASE_COMMIT"
  ```

- [ ] **Step 3: Validate retained receipts centrally.**

  Extend workflow validation to require the manifest and artifact hashes in every successful compatibility, performance, soak, provider, and TTHW receipt. Reject mixed hashes, prior-run artifact IDs, missing failure receipts, or source paths.

- [ ] **Step 4: Keep credential boundaries unchanged or narrower.**
  - `kaji-beta` owns only provider keys and `KAJI_TTHW_EVIDENCE_JSON`.
  - Publish environments own registry credentials/trusted publishing and reviewers but receive no provider keys.
  - Self-hosted performance receives no provider or registry credentials.
  - Workflow-level permissions remain `contents: read`; job-level write permissions remain limited to existing attestation, incident, and release-evidence jobs.

- [ ] **Step 5: Prove workflow topology and pins.**

  Tests must parse YAML and assert dependency closure, exact pinned action SHAs, artifact producer/consumer order, mandatory flags, receipt upload under `if: always()`, narrow permissions, and absence of source-only protected commands.

- [ ] **Step 6: Run release-orchestration tests and commit.**

  ```bash
  uv run --project kaji --no-sync pytest -q \
    kaji/tests/test_release_task15.py kaji/tests/test_beta_release_check.py
  bun run --cwd kaji/ts test tests/release-security.test.ts
  ```

  ```text
  ci(kaji): fan out beta proofs from one artifact set
  ```

### Task 9: Calibrate, freeze, and collect protected release-candidate evidence

**Files:**

- Modify after review only: `kaji/benchmarks/beta-baseline.json`
- Do not track: `.artifacts/kaji-benchmarks/**`
- Do not track: `.artifacts/kaji-soak/**`
- Do not track: `.artifacts/kaji-evidence/**`

- [ ] **Step 1: Run the complete local gate before calibration.**

  ```bash
  uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise
  bun run --cwd kaji/ts build
  uv run --project kaji --no-sync python kaji/scripts/beta_release_check.py --release
  ```

  Expected: zero type diagnostics and `PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed`.

- [ ] **Step 2: Calibrate on the pinned runner from the frozen artifacts.**

  Dispatch `kaji.benchmark.yml` in `calibrate` mode. Require `KAJI_BENCHMARK_PINNED_RUNNER=1`, a reviewed `KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST`, and the exact artifact-manifest binding. Download and review `beta-baseline.candidate.json` for sample count, variance, memory ceilings, runtime/toolchain fingerprint, and artifact hashes.

- [ ] **Step 3: Commit only the reviewed baseline.**

  Replace `kaji/benchmarks/beta-baseline.json` with the candidate. Do not commit raw results or temporary artifacts.

  ```text
  perf(kaji): calibrate beta artifact baseline
  ```

- [ ] **Step 4: Freeze the candidate commit and rerun local gates.**

  Record the full 40-character commit. No further tracked edit is allowed without restarting this task from Step 1.

- [ ] **Step 5: Run protected, non-publishing evidence.**
  - Run `kaji.beta.yml` for the frozen commit.
  - Run the pinned full benchmark and 30-minute soak from the same artifact set.
  - Confirm Python 3.11/3.14 and Node 22/24 compatibility receipts.
  - Confirm all four OpenAI/Anthropic SDK/provider cells.
  - Confirm all candidate workflow receipts name the same candidate commit, manifest SHA, and artifact SHA values. Review calibration A provenance separately and confirm its applicability fingerprint matches candidate B.

- [ ] **Step 6: Gather exactly five fresh TTHW receipts.**

  Give each participant only the manifest, frozen package bytes, and canonical quickstart. Require exactly five users collectively covering macOS, Linux, Python, npm, and Bun. Validate with:

  ```bash
  uv run --project kaji --no-sync python kaji/scripts/validate_tthw_evidence.py \
    /secure/path/tthw-evidence.json \
    --release-manifest .artifacts/kaji-release/manifest.json \
    --artifacts-dir .artifacts/kaji-release
  ```

  Store the protected JSON in `KAJI_TTHW_EVIDENCE_JSON`; never commit it.

- [ ] **Step 7: Evaluate the beta release-candidate checklist.**

  Every row in Section 9 must be `PASS` with a retained link/receipt. If a provider outage or infrastructure failure occurs, retain a failed receipt and rerun that protected job on the same immutable commit; do not mark it passed manually.

### Task 10: Publish only after explicit authorization

**Files:**

- No planned source edits.
- Generated/retained: signed tag, GitHub prerelease, SBOM/provenance/attestation, registry receipts, final evidence bundle.

- [ ] **Step 1: Stop and request explicit authority.**

  Present the frozen commit, artifact manifest hash, complete checklist, protected workflow links, five-user TTHW summary, provider models/cost, and known limitations. Ask separately for permission to create/push the signed tag and publish the beta.

- [ ] **Step 2: Create the approved annotated signed tag.**

  The tagger must match `KAJI_RELEASE_SIGNER_EMAIL`, the tag must point directly to the frozen commit, and GitHub verification must succeed. Any mismatch stops the workflow before credentials or publication environments are reached.

- [ ] **Step 3: Let `kaji.beta-publish.yml` execute the existing protected chain.**

  Required order:

  ```text
  verify-tag -> offline-gates -> artifact-bound performance/matrices/TTHW/providers
  -> supply-chain -> registry-preflight -> publisher-preflight
  -> publish-python + publish-npm -> publication-status
  -> byte verification -> release-evidence
  ```

- [ ] **Step 4: Verify published bytes and attach evidence.**

  Require PyPI wheel/sdist and npm tarball downloads to match the frozen manifest byte-for-byte. Attach checksums, manifest, SBOM, provenance, attestations, compatibility/performance/provider/TTHW receipts, and publication status to the GitHub prerelease.

- [ ] **Step 5: Declare beta only after the final evidence job passes.**

  If one registry succeeds and the other fails, follow the existing publication-incident path. Do not overwrite a published version, retag a different commit, or claim a complete beta.

---

## 8. Parallel Delivery Lanes

```text
Lane A — Python gate
  Task 1

Lane B — TypeScript/PR correctness
  Task 2 -> Task 3

Lane C — Contract documentation
  Task 4

Lane D — Frozen-artifact execution
  Task 5 -> Task 6 -> Task 7 -> Task 8

Merge/freeze barrier
  Lanes A + B + C + D green
          |
          v
  Task 9 calibration + protected evidence
          |
          v
  explicit user authorization
          |
          v
  Task 10 publication
```

Tasks 1, 2, and 4 may run in parallel. Task 3 may run after or alongside Task 2 if one owner controls `release-security.test.ts`. Tasks 5-8 are sequential because they share artifact identity, workflow topology, and receipt schemas; assign one owner to the workflow files to avoid conflict. Task 9 starts only after all code/doc commits are merged.

---

## 9. Exit Checklists

### Internal test-ready

- [ ] Python type diagnostics: 0.
- [ ] Python Ruff and non-integration tests: pass.
- [ ] TypeScript clean build, typecheck, lint, declarations, and tests: pass.
- [ ] TypeScript live proof files use the default committer and preserve lifecycle assertions.
- [ ] PR workflow builds before TypeScript tests from a clean checkout.
- [ ] 67/67 parity scenarios pass.
- [ ] Beta contracts, integration schemas, registry copies, and ABI checks pass.
- [ ] 37/37 ast-grep guards pass.

### Beta release-candidate ready

- [ ] One verified wheel/sdist/npm artifact set is produced once for the frozen commit.
- [ ] Python 3.11/3.14 consume those exact artifacts and retain passing receipts.
- [ ] Node 22/24 consume the exact npm tarball and retain passing receipts.
- [ ] Calibrated full benchmark passes from installed artifacts on the pinned runner.
- [ ] 30-minute soak passes from installed artifacts on the pinned runner.
- [ ] Python/OpenAI, TypeScript/OpenAI, Python/Anthropic, and TypeScript/Anthropic installed-artifact proofs pass.
- [ ] Exactly five TTHW users cover macOS, Linux, Python, npm, and Bun.
- [ ] Every candidate receipt names the same candidate commit, manifest hash, and applicable artifact hash; the calibration baseline retains A provenance and matches B on the explicit applicability fingerprint.
- [ ] No tracked file changed after evidence collection.

### Published beta

- [ ] Explicit tag/publication approval recorded.
- [ ] Annotated signed tag points directly to the frozen commit and is verified.
- [ ] SBOM, provenance, and attestations pass.
- [ ] PyPI trusted publication and npm provenance publication pass.
- [ ] Published wheel, sdist, and npm tarball are byte-identical to the frozen artifacts.
- [ ] Final evidence bundle is attached and the prerelease is marked complete.

---

## 10. Failure Modes and Recovery

| Failure                                                                                             | Required response                                                                                     |
| --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| A type-only repair changes observable output or failure codes                                       | Revert the behavioral portion, write a regression test for existing behavior, and use narrower typing |
| A protected consumer resolves `kaji/src`, `kaji/ts/src`, `dist`, or a workspace link                | Fail with `source_runtime_detected`; do not accept timing/provider evidence                           |
| Artifact manifest, size, or hash differs in a consumer job                                          | Fail before installation; rebuild once in the producer and rerun all consumers                        |
| Runtime matrix rebuilds packages                                                                    | Fail the workflow contract; use consume-only commands and upstream artifacts                          |
| Benchmark/soak artifact identities differ                                                           | Mark both receipts failed and rerun both on the same artifact set                                     |
| Provider child receives unrelated secrets                                                           | Fail deterministic redaction tests before any live call; replace inherited environment with allowlist |
| One provider cell fails or a provider is unavailable                                                | Retain the failed row and rerun on the same immutable commit; no manual override                      |
| TTHW evidence has duplicate users, missing platform/installer coverage, old commit, or wrong hashes | Reject it and gather fresh receipts; do not edit validation output                                    |
| Any tracked change lands after calibration/evidence                                                 | Invalidate the evidence, recalibrate if performance-relevant, and rerun every affected protected gate |
| One registry publishes and the other fails                                                          | Enter the existing publication-incident workflow; do not mutate or reuse the published version        |

---

## 11. Final Verification Command Set

Run locally before presenting the release candidate:

```bash
uv run --project kaji --no-sync python kaji/scripts/check_types.py --output-format concise
uv run --project kaji --no-sync ruff check kaji/src kaji/tests
uv run --project kaji --no-sync python kaji/scripts/sync_beta_contracts.py --check
uv run --project kaji --no-sync python kaji/scripts/sync_integration_contracts.py --check
uv run --project kaji --no-sync python kaji/scripts/check_integration_abi.py --explain
uv run --project kaji --no-sync python kaji/scripts/check_sdk_parity.py
bun run audit:ast-grep
bun run --cwd kaji/ts build
bun run --cwd kaji/ts typecheck
bun run --cwd kaji/ts lint
uv run --project kaji --no-sync python kaji/scripts/beta_release_check.py --release
```

Expected final local line:

```text
PASS: offline release rehearsal; keyed/provider/publish readiness NOT claimed
```

The protected workflows, not a local shell, provide the remaining compatibility, performance, soak, provider, TTHW, signing, provenance, and publication evidence.
