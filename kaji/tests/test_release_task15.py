from __future__ import annotations

import base64
from email.message import Message
import importlib.util
import re
import subprocess
import sys
import hashlib
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import MutableMapping, cast
import textwrap
import urllib.request

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TYPESCRIPT_GITHUB_TOOLS = [
    "add_comment",
    "create_issue",
    "get_file",
    "get_issue",
    "list_issues",
    "search_code",
    "get_commit",
    "get_pull_request",
    "list_pull_request_files",
    "list_check_runs",
    "get_workflow_run",
    "list_workflow_jobs",
    "list_file_commits",
    "get_release",
    "list_deployments",
]
HOSTILE_TYPESCRIPT_CURRENT_VERSIONS = (
    ("leading-zero-core", "01.2.3"),
    ("leading-zero-prerelease", "1.2.3-01"),
    ("invalid-build-character", "1.2.3+!"),
    ("unicode-digits", "١.٢.٣"),
)


def _github_package_proof(runtime: str) -> dict[str, object]:
    if runtime == "python":
        return {
            "schemaVersion": 1,
            "evidenceClass": "offline_exact_artifact_smoke",
            "integration": "github",
            "runtime": "python",
            "network": "scripted",
            "liveProvider": False,
            "contractVersion": "1.0.0",
            "caseCount": 23,
            "toolCount": 6,
            "approvalDeniedBeforeCredentialAccess": True,
            "mutationRetries": 0,
            "unknownMutationPreserved": True,
            "sourceRuntimeDetected": False,
            "conclusion": "passed",
            "failureCode": None,
        }
    assert runtime == "typescript"
    read_tools = TYPESCRIPT_GITHUB_TOOLS[2:]
    return {
        "schemaVersion": 5,
        "evidenceClass": "offline_exact_artifact_smoke",
        "integration": "github",
        "runtime": "typescript",
        "network": "blocked",
        "liveProvider": False,
        "sharedAbiVersion": "1.0.0",
        "packageAbiSchemaVersion": "1.0.0",
        "packageCatalogVersion": "0.2.0",
        "apiFixtureVersion": "1.0.0",
        "sharedFixtureCaseCount": 23,
        "publicScenarioCount": 15,
        "packageCatalog": {
            "schemaVersion": "1.0.0",
            "catalogVersion": "0.2.0",
            "toolCount": 15,
            "readToolCount": 13,
            "tools": TYPESCRIPT_GITHUB_TOOLS,
            "readTools": read_tools,
            "providerAliases": [f"github_{tool}" for tool in TYPESCRIPT_GITHUB_TOOLS],
            "catalogNames": [f"github.{tool}" for tool in TYPESCRIPT_GITHUB_TOOLS],
        },
        "cliCopiedCatalog": {
            "manifestVersion": "0.1.0",
            "toolCount": 6,
            "readToolCount": 4,
            "tools": TYPESCRIPT_GITHUB_TOOLS[:6],
            "readTools": read_tools[:4],
        },
        "esmSharedAbiMatched": True,
        "cjsSharedAbiMatched": True,
        "esmPackageAbiMatched": True,
        "cjsPackageAbiMatched": True,
        "esmClassIdentityMatched": True,
        "cjsClassIdentityMatched": True,
        "esmFactoryIdentityMatched": True,
        "cjsFactoryIdentityMatched": True,
        "esmRuntimeExports": [
            "GitHubIntegration",
            "createGithubIntegration",
            "inspectIntegration",
        ],
        "cjsRuntimeExports": [
            "GitHubIntegration",
            "createGithubIntegration",
            "inspectIntegration",
        ],
        "esmDeclarationExports": [
            "CreateGitHubIntegrationOptions",
            "GitHubIntegration",
            "createGithubIntegration",
            "inspectIntegration",
        ],
        "cjsDeclarationExports": [
            "CreateGitHubIntegrationOptions",
            "GitHubIntegration",
            "createGithubIntegration",
            "inspectIntegration",
        ],
        "typescriptDeclarationChecks": {
            "compilerOptions": {
                "module": "NodeNext",
                "moduleResolution": "NodeNext",
                "skipLibCheck": False,
            },
            "typescript57": {
                "version": "5.7.3",
                "mtsImport": "passed",
                "ctsRequire": "passed",
            },
            "typescriptCurrent": {
                "version": "6.0.2",
                "mtsImport": "passed",
                "ctsRequire": "passed",
            },
        },
        "privateGitHubCompositionSourcesPacked": False,
        "privateGitHubCompositionSourceImportsRejected": True,
        "closedCallsDeniedBeforeCredentialAccess": True,
        "approvalDeniedBeforeCredentialAccess": True,
        "repositoryDeniedBeforeCredentialAccess": True,
        "githubCatalogEventsVerified": ["requested", "started", "failed"],
        "genericSyntheticCatalogEventsVerified": [
            "requested",
            "started",
            "completed",
        ],
        "githubFailureRecovery": {
            "error_code": "INTEGRATION_AUTH_REQUIRED",
            "reason_code": "github_token_missing",
            "recovery_code": "CONFIGURE_GITHUB_TOKEN",
            "doc_url": ("https://kaji.dev/docs/integrations/recovery-v1#github-token"),
        },
        "githubObservabilitySinksVerified": True,
        "unknownMutationPreserved": True,
        "mutationRetries": 0,
        "lifecycle": {
            "githubFailure": {
                "stages": ["requested", "started", "failed"],
                "providerAlias": "github_get_file",
                "catalogName": "github.get_file",
                "sameIdentityAtEveryStage": True,
            },
            "syntheticCompletion": {
                "stages": ["requested", "started", "completed"],
                "providerAlias": "synthetic_complete",
                "catalogName": "synthetic.complete",
                "sameIdentityAtEveryStage": True,
            },
        },
        "policyBeforeRequest": {
            "testFile": "kaji/ts/tests/github-registry.test.ts",
            "testName": "rejects approval for github_create_issue before token or HTTP",
            "tokenLookups": 0,
            "requestAttempts": 0,
        },
        "aliasCollisionRejected": True,
        "conclusion": "passed",
        "failureCode": None,
    }


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text()


def _normative_semver_pattern() -> str:
    schema = json.loads(
        _read("kaji/contracts/release/kaji-ts-consumer-handoff-v1.schema.json")
    )
    pattern = schema["$defs"]["semver"]["pattern"]
    assert isinstance(pattern, str)
    return pattern


def _load_root_script(name: str) -> ModuleType:
    path = REPO_ROOT / "kaji" / "scripts" / name
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_test_support(name: str) -> ModuleType:
    module_name = f"_release_support_{Path(name).stem}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _assert_external_actions_are_sha_pinned(workflow: str) -> None:
    references = re.findall(r"^\s*(?:-\s*)?uses: ([^\s#]+)", workflow, re.MULTILINE)
    external = [reference for reference in references if not reference.startswith("./")]
    assert external
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference) for reference in external)
    assert not any(
        re.search(r"@(main|master|release/|v\d)", reference) for reference in external
    )


def test_ci_uses_real_package_smokes_and_supported_runtime_matrix() -> None:
    python = _read(".github/workflows/python.test.yml")
    ts = _read(".github/workflows/ts.test.yml")
    lint = _read(".github/workflows/ts.lint.yml")

    assert "scripts/verify_archives.py" in python
    assert 'python-version: "3.11"' in python
    assert 'python-version: "3.14"' in python
    assert "scripts/smoke_package.mts" in ts
    assert 'node-version: ["22", "24"]' in ts
    for command in (
        "bun run format:check",
        "bun run lint",
        "bun run typecheck:registry",
        "bun run validate:registry",
        "bun run check:integrations",
    ):
        assert command in lint
    assert ts.count("timeout-minutes:") == 4


def test_release_workflows_bound_every_job() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")
    performance = _read(".github/workflows/kaji.performance.yml")

    assert rehearsal.count("timeout-minutes:") == 6
    assert publish.count("timeout-minutes:") == 14
    assert performance.count("timeout-minutes:") == 5
    assert "timeout-minutes: 90" in performance
    assert "timeout-minutes: 45" in publish


def test_performance_workflow_timeouts_cover_child_and_cleanup_budgets() -> None:
    performance = _read(".github/workflows/kaji.performance.yml")
    paired = performance.split("  paired-replica:", 1)[1].split(
        "  paired-aggregate:", 1
    )[0]
    aggregate = performance.split("  paired-aggregate:", 1)[1].split("  soak:", 1)[0]
    soak = performance.split("  soak:", 1)[1].split("  performance-evidence:", 1)[0]
    evidence = performance.split("  performance-evidence:", 1)[1]

    assert "twice the legacy single-subject measurements" in paired
    assert "timeout-minutes: 90" in paired
    assert "timeout-minutes: 15" in aggregate
    assert "timeout-minutes: 50" in soak
    assert "timeout-minutes: 15" in evidence


def test_protected_performance_jobs_use_only_macos_arm64_runner() -> None:
    benchmark = _read(".github/workflows/kaji.benchmark.yml")
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")
    performance = _read(".github/workflows/kaji.performance.yml")
    selector = "runs-on: macos-15"

    assert performance.count(selector) == 2
    assert benchmark.count(selector) == 0
    assert rehearsal.count(selector) == 0
    assert publish.count(selector) == 0
    assert "self-hosted" not in (benchmark + rehearsal + publish + performance)
    assert (
        "  release-artifacts:\n    name: release artifacts\n    runs-on: ubuntu-latest"
        in (benchmark)
    )
    assert (
        "  offline-release:\n    name: offline release\n    runs-on: ubuntu-latest"
        in (rehearsal)
    )


def test_release_gate_runs_package_metadata_and_supply_chain_checks() -> None:
    script = _read("kaji/scripts/beta_release_check.py")

    for expected in (
        "--release",
        '"ruff", "format", "--check", "src", "tests"',
        '"pip-audit",',
        '"--require-hashes",',
        '"openai",',
        '"anthropic",',
        '"build-requirements.txt",',
        '["bun", "audit", "--production"]',
        '("bun", "x", "publint")',
        '["bun", "x", "attw", "--pack", "."]',
        "verify_package_metadata.py",
        "verify_npm_package.py",
        "smoke_package.mts",
        "Reverify final Python artifacts",
        '"package:smoke"',
        '"typecheck:registry"',
        '"validate:registry"',
        '"check:integrations"',
    ):
        assert expected in script
    metadata_verifier = _read("kaji/scripts/verify_package_metadata.py")
    assert '"buildAudit": {' in metadata_verifier
    assert '"file": "kaji/build-requirements.txt"' in metadata_verifier
    assert '"sha256": sha256(build_audit)' in metadata_verifier
    assert "verify_npm_tarball(npm_tarball, repo)" in metadata_verifier
    assert 'PYTHON_PROJECT = "kaji-sdk"' in metadata_verifier
    assert "if python_project != PYTHON_PROJECT:" in metadata_verifier

    publish_workflow = _read(".github/workflows/kaji.publish.yml")
    assert publish_workflow.count("https://pypi.org/pypi/kaji-sdk/0.2.0b1/json") == 2
    assert "https://pypi.org/pypi/kaji/0.2.0b1/json" not in publish_workflow

    npm_verifier = _read("kaji/scripts/verify_npm_package.py")
    for expected in (
        "npm tarball member set differs from checkout",
        "npm tarball file differs from checkout",
        "npm packaged contracts differ from canonical shared contracts",
        "npm package target is missing or outside dist/",
        "npm registry manifest is missing",
    ):
        assert expected in npm_verifier

    package_smoke = _read("kaji/ts/scripts/smoke_package.mts")
    for expected in (
        '"openai@6.42.0"',
        '"@anthropic-ai/sdk@0.104.1"',
        '"audit", "--omit=dev", "--audit-level=high"',
    ):
        assert expected in package_smoke


def test_npm_lock_uses_patched_fast_uri() -> None:
    lockfile = _read("bun.lock")

    assert '"fast-uri": ["fast-uri@3.1.4"' in lockfile
    assert '"fast-uri": ["fast-uri@3.1.3"' not in lockfile
    for relative in (
        "kaji/scripts/installed-typescript-runtime/package-lock.json",
        "kaji/scripts/installed-typescript-runtime/package-lock.core.json",
    ):
        package_lock = json.loads(_read(relative))
        fast_uri = package_lock["packages"]["node_modules/fast-uri"]
        assert fast_uri == {
            "version": "3.1.4",
            "resolved": "https://registry.npmjs.org/fast-uri/-/fast-uri-3.1.4.tgz",
            "integrity": (
                "sha512-8JnbkQ4juDyvYs4mgFGQqg4yCYtFDtUtmp2QIQq11ZZe5CFQ5wcqm1rqDgAh/"
                "QdMySuBnPzMUiJUNZG5N/AiQw=="
            ),
            "funding": [
                {
                    "type": "github",
                    "url": "https://github.com/sponsors/fastify",
                },
                {
                    "type": "opencollective",
                    "url": "https://opencollective.com/fastify",
                },
            ],
            "license": "BSD-3-Clause",
        }


def test_protected_release_workflows_fail_closed_and_attach_provenance() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")

    assert "environment: kaji-beta" in rehearsal
    assert "OPENAI_API_KEY" in rehearsal
    assert "ANTHROPIC_API_KEY" in rehearsal
    assert "live_provider_proof.py" in rehearsal
    assert (
        "needs: [offline-release, performance, tthw-evidence, python-compat, node-compat]"
        in rehearsal
    )
    assert "needs.offline-release.result == 'success'" in rehearsal
    assert "needs.python-compat.result == 'success'" in rehearsal
    assert "needs.node-compat.result == 'success'" in rehearsal
    assert "needs.performance.result == 'success'" in rehearsal
    assert "group: kaji-beta-rehearsal-0.2.0-beta.2" in rehearsal
    assert "offline-gate-summary.json" in rehearsal
    assert "if: ${{ always() }}" in rehearsal
    rehearsal_keyed_steps = rehearsal.split("  keyed-proof:", 1)[1].split(
        "      - uses: actions/checkout@", 1
    )[0]
    assert "Initialize exact-commit provider evidence before setup" in (
        rehearsal_keyed_steps
    )
    assert "Retain initial not-run provider evidence before setup" in (
        rehearsal_keyed_steps
    )
    _assert_external_actions_are_sha_pinned(rehearsal)
    for expected in (
        "verification.verified",
        "environment: kaji-beta",
        "environment: kaji-beta-publish",
        "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b",
        "npm publish .artifacts/kaji-release/kaji-sdk-0.2.0-beta.2.tgz --provenance --access public --tag beta --registry=https://registry.npmjs.org/",
        "--provenance",
        "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be",
        "SHA256SUMS",
        "sbom",
        "live_provider_proof.py",
        "group: kaji-beta-publish-${{ github.ref_name }}",
        "KAJI_RELEASE_SIGNER_EMAIL",
        "context.payload.repository?.private !== false",
        "npm provenance requires the source repository to be public",
        "github.rest.repos.compareCommits",
        "comparison.data.merge_base_commit.sha !== releaseCommit",
        "signed beta tag commit must already be contained in the default branch",
        'verification.reason !== "valid"',
        "tag.data.tag !== tagName",
        "signed beta tagger is not repository-approved",
        'core.setOutput("tag-object", tagObject)',
        'core.setOutput("commit", releaseCommit)',
        "Revalidate downloaded filenames, sizes, hashes, and commit",
        "offline-gate-summary.json",
        "offline-gates.log",
        "steps.provenance.outputs.bundle-path",
        "steps.provenance.outputs.attestation-id",
        "steps.provenance.outputs.attestation-url",
        "provenance.bundle.jsonl",
        "provenance.json",
        "provider-evidence.json",
        "kaji-tthw-evidence",
        "validate_tthw_evidence.py",
        "tthw/tthw-evidence.json",
        "pypi-attestations==0.0.29",
        "npm@11.16.0",
        "--downloads-dir .artifacts/kaji-publication-status/downloaded",
        '--repository "$GITHUB_REPOSITORY"',
        "verify_published_packages.py state",
        "steps.classify.outputs.publication-state || steps.initial-status.outputs.publication-state",
        "needs.publication-status.outputs.state == 'byte_verified'",
        "installation recommendations remain withheld",
        "github.run_attempt == 1",
        "publisher-preflight:",
        "NPM_TOKEN is required",
        "npm access list packages",
        "npm view kaji-sdk name --json",
        "npm identity lacks write access to the existing kaji-sdk package",
        "Verified npm publisher identity for the first unscoped kaji-sdk publication.",
        "npm package ownership preflight was ambiguous",
        "verify_release_artifacts.py",
        "verify_npm_package.py",
        "verify_archives.py",
        "Rebuild and verify exact package contents against the clean checkout",
        "Reverify Python archive contents against the clean checkout",
        "Rebuild and verify npm archive contents against the clean checkout",
        "verify_published_packages.py",
        "--attempts 8 --initial-delay 2 --max-delay 20",
        "attach_release_assets.py",
        "registry-verification.json",
        "Initialize fail-closed publication status before setup",
        '--pypi-publish-result "$PYPI_PUBLISH_RESULT"',
        '--npm-publish-result "$NPM_PUBLISH_RESULT"',
        "status_classifier_unavailable",
        "Create or update fail-closed incident prerelease status",
        "Installation recommendation: WITHHELD",
        "Retained evidence:",
        "no publish job was attempted",
        "needs.publication-status.outputs.incident == 'true'",
    ):
        assert expected in publish
    publish_keyed_steps = publish.split("  keyed-proof:", 1)[1].split(
        "      - uses: actions/checkout@", 1
    )[0]
    assert "Initialize exact-commit provider evidence before setup" in (
        publish_keyed_steps
    )
    assert "Retain initial not-run provider evidence before setup" in (
        publish_keyed_steps
    )
    publication_status = publish.split("  publication-status:", 1)[1].split(
        "  publication-incident:", 1
    )[0]
    assert "    if: ${{ always() }}" in publication_status
    assert "      - name: Reduce monotonic publication state\n" in publication_status
    classifier = publication_status.split(
        "      - name: Reduce monotonic publication state\n", 1
    )[1].split("      - name: Preserve publication outcome", 1)[0]
    assert "        if: ${{ always() && github.run_attempt == 1 }}" in classifier
    assert "publication-status.json" in classifier
    assert "publication-status.md" in classifier
    incident_job = publish.split("  publication-incident:", 1)[1].split(
        "  release-evidence:", 1
    )[0]
    assert "permissions:\n      contents: write" in incident_job
    assert '--title "Kaji $EXPECTED_TAG"' in incident_job
    assert "--verify-tag --prerelease" in incident_job
    assert '.name == ("Kaji " + $tag)' in incident_job
    assert ".draft == false" in incident_job
    assert "HTTP_STATUS" in incident_job
    assert "github.run_attempt == 1" in incident_job
    assert "--clobber" not in incident_job
    assert (
        publish.count("Revalidate downloaded filenames, sizes, hashes, and commit") == 3
    )
    assert publish.count("uses: ./.github/actions/verify-kaji-beta-tag") == 3
    assert publish.count("environment: kaji-beta-publish") == 3
    assert (
        publish.count(
            "needs: [verify-tag, supply-chain, registry-preflight, publisher-preflight]"
        )
        == 2
    )
    assert (
        "needs: [verify-tag, tthw-evidence, supply-chain, publication-status]"
        in publish
    )
    assert "if-no-files-found: error" in publish
    assert "--clobber" not in publish
    for reverify, mutation in (
        (
            "Reverify signed tag immediately before PyPI publication",
            "Publish exact Python beta through trusted publishing",
        ),
        (
            "Reverify signed tag immediately before npm publication",
            "Publish exact npm beta with provenance",
        ),
        (
            "Reverify signed tag immediately before release attachment",
            "Create or verify prerelease and attach only missing digest-matched assets",
        ),
    ):
        between = publish.split(reverify, 1)[1].split(mutation, 1)[0]
        assert between.count("uses: ./.github/actions/verify-kaji-beta-tag") == 1
        assert between.count("      - name:") == 1
    assert (
        "needs: [verify-tag, offline-gates, performance, tthw-evidence, python-compat, node-compat]"
        in publish
    )
    assert (
        "needs: [verify-tag, offline-gates, performance, tthw-evidence, keyed-proof, python-compat, node-compat]"
        in publish
    )
    for dependency in (
        "verify-tag",
        "offline-gates",
        "performance",
        "tthw-evidence",
        "python-compat",
        "node-compat",
    ):
        assert f"needs.{dependency}.result == 'success'" in publish
    assert (
        "if: ${{ always() && needs.verify-tag.result == 'success' && needs.offline-gates.result == 'success' }}"
        in publish
    )
    assert "validate_release_evidence.py" in publish
    _assert_external_actions_are_sha_pinned(publish)

    attach = _read("kaji/scripts/attach_release_assets.py")
    assert "unexpected = set(existing) - set(desired)" in attach
    assert "set(final_assets) != set(desired)" in attach
    assert re.search(r'"gh",\s*"release",\s*"upload"', attach)
    assert "--clobber" not in attach
    assert "release asset digest mismatch" in attach
    assert 'prefix="kaji-release-final-"' in attach
    assert attach.count("verify_remote_asset(") >= 3

    registry = _read("kaji/scripts/verify_published_packages.py")
    assert "PyPI digest/size mismatch" in registry
    assert "downloaded npm tarball differs from manifest" in registry
    assert "downloaded npm tarball fails registry integrity" in registry
    assert "time.sleep(delay)" in registry
    assert "except VerificationMismatch as error" in registry
    assert '"pypi-attestations",' in registry
    assert (
        '["npm", "audit", "signatures", "--json", "--include-attestations"]' in registry
    )
    assert re.search(r'"gh",\s*"attestation",\s*"verify"', registry)
    assert '"status": "byte_verified"' in registry
    assert '"status": "verification_failed"' in registry
    for evidence_field in (
        '"manifestCommit"',
        '"packages"',
        '"filename"',
        '"sha256"',
        '"size"',
        '"integrity"',
    ):
        assert evidence_field in registry


@pytest.mark.parametrize(
    ("workflow_name", "expected_commit"),
    [
        (".github/workflows/kaji.rehearsal.yml", "${{ github.sha }}"),
        (
            ".github/workflows/kaji.publish.yml",
            "${{ needs.verify-tag.outputs.commit }}",
        ),
    ],
)
def test_performance_evidence_is_bound_before_retention(
    workflow_name: str, expected_commit: str
) -> None:
    workflow = _read(workflow_name)
    performance = workflow.split("  performance:", 1)[1].split("  python-compat:", 1)[0]

    upstream = "offline-release" if "rehearsal" in workflow_name else "offline-gates"
    assert "uses: ./.github/workflows/kaji.performance.yml" in performance
    assert f"candidate-commit: {expected_commit}" in performance
    assert (
        f"candidate-artifact-id: ${{{{ needs.{upstream}.outputs.artifact-id }}}}"
        in performance
    )
    assert (
        f"candidate-artifact-digest: "
        f"${{{{ needs.{upstream}.outputs.artifact-digest }}}}" in performance
    )
    assert "actions: read" in performance
    assert "run_beta_benchmarks.py" not in performance
    assert "baselineFingerprint" not in performance
    assert ".artifacts/kaji-evidence/performance-status.json" in workflow
    assert ".artifacts/kaji-evidence/paired-benchmark-results.json" in workflow
    if workflow_name.endswith("kaji.publish.yml"):
        assert (
            workflow.count(".artifacts/kaji-evidence/performance-imagedata.json") >= 3
        )
        for retained in (
            ".artifacts/kaji-evidence/raw/benchmarks/replica-1.json",
            ".artifacts/kaji-evidence/raw/benchmarks/replica-2.json",
            ".artifacts/kaji-evidence/raw/benchmarks/replica-3.json",
            ".artifacts/kaji-evidence/raw/soak/python.json",
            ".artifacts/kaji-evidence/raw/soak/typescript.json",
            ".artifacts/kaji-evidence/raw/soak/results.json",
        ):
            assert retained in workflow
    else:
        assert "name: kaji-release-candidate-evidence" in workflow
        assert "path: .artifacts/kaji-evidence" in workflow


@pytest.mark.parametrize(
    ("workflow_name", "upstream", "expected_commit"),
    [
        (
            ".github/workflows/kaji.rehearsal.yml",
            "offline-release",
            "${{ github.sha }}",
        ),
        (
            ".github/workflows/kaji.publish.yml",
            "[verify-tag, offline-gates]",
            "${{ needs.verify-tag.outputs.commit }}",
        ),
    ],
)
def test_tthw_gate_is_exact_commit_step_scoped_and_retained(
    workflow_name: str, upstream: str, expected_commit: str
) -> None:
    workflow = _read(workflow_name)
    remainder = workflow.split("  tthw-evidence:", 1)[1]
    next_job = re.search(r"\n  [a-z][a-z-]+:\n", remainder)
    job = remainder[: next_job.start()] if next_job is not None else remainder
    job_header, steps = job.split("    steps:", 1)
    validation = steps.split(
        "      - name: Validate protected exact-commit five-user TTHW evidence", 1
    )[1].split("      - name: Retain exact-commit TTHW evidence and status", 1)[0]

    assert f"needs: {upstream}" in job_header
    assert "environment: kaji-beta" in job_header
    assert f"KAJI_RELEASE_COMMIT: {expected_commit}" in job_header
    assert "secrets.KAJI_TTHW_EVIDENCE_JSON" not in job_header
    assert workflow.count("${{ secrets.KAJI_TTHW_EVIDENCE_JSON }}") == 1
    assert "KAJI_TTHW_EVIDENCE_JSON: ${{ secrets.KAJI_TTHW_EVIDENCE_JSON }}" in (
        validation
    )
    assert "validate_tthw_evidence.py" in validation
    assert "--release-manifest .artifacts/kaji-release/manifest.json" in validation
    assert "--artifacts-dir .artifacts/kaji-release" in validation
    assert (
        'if [ "$status" -eq 0 ]; then\n'
        '            cp "$raw_evidence" "$KAJI_TTHW_EVIDENCE_DIR/tthw-evidence.json"'
        in validation
    )
    assert steps.index(
        "Initialize exact-commit TTHW status before setup"
    ) < steps.index("actions/checkout@")
    assert "name: kaji-tthw-evidence-initial" in steps
    assert "if: ${{ always() }}" in steps
    assert "name: kaji-tthw-evidence" in steps
    assert "status.json" in steps
    assert "validation.log" in steps

    if workflow_name.endswith("kaji.publish.yml"):
        assert "github.run_attempt == 1" in job_header
        assert "name: kaji-tthw-evidence" in workflow
        assert ".artifacts/kaji-evidence/tthw/status.json" in workflow
        assert ".artifacts/kaji-evidence/tthw/validation.log" in workflow
        assert ".artifacts/kaji-evidence/tthw/tthw-evidence.json" in workflow

    docs = _read("docs/kaji/releasing.md")
    assert "KAJI_TTHW_EVIDENCE_JSON" in docs
    assert "Configuration alone does not claim that the cohort passed" in docs


@pytest.mark.parametrize(
    "workflow_name",
    [".github/workflows/kaji.rehearsal.yml", ".github/workflows/kaji.publish.yml"],
)
def test_keyed_proof_secrets_are_step_scoped_and_initial_evidence_precedes_setup(
    workflow_name: str,
) -> None:
    workflow = _read(workflow_name)
    keyed_remainder = workflow.split("  keyed-proof:", 1)[1]
    next_job = re.search(r"\n  [a-z][a-z-]+:\n", keyed_remainder)
    keyed = (
        keyed_remainder[: next_job.start()] if next_job is not None else keyed_remainder
    )
    job_environment = keyed.split("    steps:", 1)[0]
    proof_step = keyed.split("      - name: Run protected provider proof", 1)[1].split(
        "      - name: Retain exact-commit provider evidence", 1
    )[0]

    assert "secrets.OPENAI_API_KEY" not in job_environment
    assert "secrets.ANTHROPIC_API_KEY" not in job_environment
    assert keyed.count("secrets.OPENAI_API_KEY") == 1
    assert keyed.count("secrets.ANTHROPIC_API_KEY") == 1
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in proof_step
    assert "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}" in proof_step
    assert "uv run --project kaji --no-sync python" in proof_step
    assert "uses: oven-sh/setup-bun@0c5077e51419868618aeaa5fe8019c62421857d6" in keyed
    assert "uses: ./.github/actions/setup-bun-cache" not in keyed
    assert "sync-args: --frozen" in keyed
    assert "--extra openai" not in keyed
    assert "--extra anthropic" not in keyed
    assert "timeout-minutes: 30" in keyed
    assert "${{ runner.temp }}/provider-evidence.initial.json" in keyed
    assert keyed.index("kaji-provider-evidence-initial") < keyed.index(
        "actions/checkout@"
    )
    assert keyed.index("actions/checkout@") < keyed.index(
        "Restore not-run provider evidence after checkout"
    )
    assert keyed.index(
        "Restore not-run provider evidence after checkout"
    ) < keyed.index("Run protected provider proof")


def test_publication_reruns_are_guarded_before_queries_and_release_mutation() -> None:
    publish = _read(".github/workflows/kaji.publish.yml")
    status_job = publish.split("  publication-status:", 1)[1].split(
        "  publication-incident:", 1
    )[0]
    incident_job = publish.split("  publication-incident:", 1)[1].split(
        "  release-evidence:", 1
    )[0]

    assert status_job.index("kaji-publication-status-initial") < status_job.index(
        "Guard workflow reruns before registry classification"
    )
    assert "${{ runner.temp }}/kaji-publication-status-initial" in status_job
    assert status_job.index(
        "Guard workflow reruns before registry classification"
    ) < status_job.index("actions/checkout@")
    assert status_job.index("actions/checkout@") < status_job.index(
        "Restore fail-closed publication status after checkout"
    )
    assert "github.run_attempt != 1" in status_job
    assert status_job.count("github.run_attempt == 1") >= 7
    assert "--previous-state unpublished" in status_job
    assert "timeout --signal=TERM --kill-after=10s 15m" in status_job
    assert "timeout-minutes: 45" in status_job
    assert status_job.index("timeout --signal=TERM --kill-after=10s 15m") < (
        status_job.index("Reduce monotonic publication state")
    )
    assert status_job.index("Reduce monotonic publication state") < status_job.index(
        "Preserve publication outcome and recovery directions"
    )
    assert (
        "Workflow reruns cannot create a publication transition or edit the prerelease."
        in status_job
    )
    assert "github.run_attempt == 1" in incident_job
    assert "gh release edit" in incident_job
    assert "gh release create" in incident_job

    artifact_verifier = _read("kaji/scripts/verify_release_artifacts.py")
    assert 'EXPECTED_BUILD_AUDIT = "kaji/build-requirements.txt"' in artifact_verifier
    assert 'set(build_audit) != {"file", "sha256"}' in artifact_verifier

    tag_verifier = _read(".github/actions/verify-kaji-beta-tag/action.yml")
    assert "using: composite" in tag_verifier
    assert ".verification.verified == true" in tag_verifier
    assert '.verification.reason == "valid"' in tag_verifier
    assert ".tag == $tag" in tag_verifier
    assert ".tagger.email == $tagger" in tag_verifier
    assert "EXPECTED_TAGGER_EMAIL" in tag_verifier
    assert '.object.type == "commit" and .object.sha == $commit' in tag_verifier


@pytest.mark.parametrize(
    (
        "previous",
        "pypi",
        "npm",
        "verification",
        "pypi_publish",
        "npm_publish",
        "expected",
        "ready",
    ),
    [
        (
            "unpublished",
            "absent",
            "absent",
            "not_run",
            "skipped",
            "skipped",
            "unpublished",
            False,
        ),
        (
            "unpublished",
            "present",
            "absent",
            "not_run",
            "success",
            "failure",
            "pypi_only",
            False,
        ),
        (
            "unpublished",
            "absent",
            "present",
            "not_run",
            "failure",
            "success",
            "npm_only",
            False,
        ),
        (
            "pypi_only",
            "present",
            "present",
            "not_run",
            "success",
            "success",
            "both_published",
            False,
        ),
        (
            "both_published",
            "present",
            "present",
            "byte_verified",
            "success",
            "success",
            "byte_verified",
            True,
        ),
    ],
)
def test_publication_state_reducer_is_monotonic_and_byte_verified_is_sole_success(
    previous: str,
    pypi: str,
    npm: str,
    verification: str,
    pypi_publish: str,
    npm_publish: str,
    expected: str,
    ready: bool,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state=previous,
        pypi=pypi,
        npm=npm,
        registry_verification=verification,
        pypi_publish_result=pypi_publish,
        npm_publish_result=npm_publish,
    )

    assert decision.state == expected
    assert decision.release_ready is ready
    assert decision.install_recommendation is ready
    assert (decision.state == "byte_verified") is ready


@pytest.mark.parametrize(
    ("pypi", "npm", "verification", "incident"),
    [
        ("absent", "absent", "not_run", None),
        ("absent", "absent", "failed", "registry_verification_failed"),
        ("absent", "absent", "byte_verified", "verification_state_mismatch"),
        ("unknown", "absent", "not_run", "registry_state_unknown"),
        ("absent", "unknown", "not_run", "registry_state_unknown"),
        ("unknown", "unknown", "not_run", "registry_state_unknown"),
    ],
)
def test_only_exact_clean_no_attempt_state_avoids_an_incident(
    pypi: str, npm: str, verification: str, incident: str | None
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="unpublished",
        pypi=pypi,
        npm=npm,
        registry_verification=verification,
        pypi_publish_result="skipped",
        npm_publish_result="skipped",
    )

    assert decision.state == "unpublished"
    assert decision.incident_code == incident
    publish = _read(".github/workflows/kaji.publish.yml")
    status_job = publish.split("  publication-status:", 1)[1].split(
        "  publication-incident:", 1
    )[0]
    initial = status_job.split(
        "      - name: Initialize fail-closed publication status before setup", 1
    )[1].split("      - name: Retain initial fail-closed publication status", 1)[0]
    assert 'incident: {code: "classification_pending"' in initial
    assert 'echo "incident=true" >>"$GITHUB_OUTPUT"' in initial
    assert 'echo "incident=false" >>"$GITHUB_OUTPUT"' not in initial
    assert '[ "$PYPI_STATE" = absent ]' in status_job
    assert '[ "$NPM_STATE" = absent ]' in status_job
    assert '[ "$REGISTRY_VERIFICATION" = not_run ]' in status_job
    assert '[ "$PYPI_PUBLISH_RESULT" = skipped ]' in status_job
    assert '[ "$NPM_PUBLISH_RESULT" = skipped ]' in status_job
    assert "*) FALLBACK_STATE=unpublished ;;" in status_job


def test_byte_verified_observation_cannot_be_clean_when_registries_are_absent() -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="unpublished",
        pypi="absent",
        npm="absent",
        registry_verification="byte_verified",
        pypi_publish_result="skipped",
        npm_publish_result="skipped",
    )

    assert decision.state == "unpublished"
    assert decision.incident_code == "verification_state_mismatch"
    assert decision.release_ready is False


@pytest.mark.parametrize(
    (
        "previous",
        "pypi",
        "npm",
        "verification",
        "pypi_publish",
        "npm_publish",
        "incident",
    ),
    [
        (
            "pypi_only",
            "absent",
            "absent",
            "not_run",
            "failure",
            "skipped",
            "state_regression",
        ),
        (
            "npm_only",
            "present",
            "absent",
            "not_run",
            "success",
            "success",
            "state_branch_mismatch",
        ),
        (
            "both_published",
            "unknown",
            "present",
            "not_run",
            "success",
            "success",
            "registry_state_unknown",
        ),
        (
            "unpublished",
            "present",
            "absent",
            "byte_verified",
            "success",
            "failure",
            "verification_state_mismatch",
        ),
        (
            "both_published",
            "present",
            "present",
            "failed",
            "success",
            "success",
            "registry_verification_failed",
        ),
        (
            "unpublished",
            "absent",
            "absent",
            "not_run",
            "failure",
            "skipped",
            "publish_attempt_failed",
        ),
        (
            "unpublished",
            "absent",
            "absent",
            "not_run",
            "cancelled",
            "skipped",
            "publish_attempt_cancelled",
        ),
        (
            "unpublished",
            "absent",
            "absent",
            "not_run",
            "unknown",
            "skipped",
            "publish_outcome_unknown",
        ),
        (
            "unpublished",
            "absent",
            "absent",
            "not_run",
            "success",
            "success",
            "publish_success_registry_absent",
        ),
        (
            "unpublished",
            "unknown",
            "absent",
            "not_run",
            "success",
            "skipped",
            "registry_state_unknown",
        ),
        (
            "unpublished",
            "present",
            "absent",
            "not_run",
            "skipped",
            "skipped",
            "partial_publication",
        ),
    ],
)
def test_publication_state_reducer_turns_unknown_or_mismatch_into_incident(
    previous: str,
    pypi: str,
    npm: str,
    verification: str,
    pypi_publish: str,
    npm_publish: str,
    incident: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state=previous,
        pypi=pypi,
        npm=npm,
        registry_verification=verification,
        pypi_publish_result=pypi_publish,
        npm_publish_result=npm_publish,
    )

    assert decision.incident_code == incident
    assert decision.release_ready is False
    assert decision.install_recommendation is False
    assert decision.recovery == "fix_forward_next_beta"


def test_publication_state_cli_withholds_installation_and_writes_machine_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    output = tmp_path / "publication-status.json"
    markdown = tmp_path / "publication-status.md"
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    verifier.state_main(
        [
            "--previous-state",
            "unpublished",
            "--pypi",
            "present",
            "--npm",
            "unknown",
            "--registry-verification",
            "failed",
            "--pypi-publish-result",
            "success",
            "--npm-publish-result",
            "failure",
            "--commit",
            "a" * 40,
            "--workflow-run",
            "https://github.example/run/1",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
        ]
    )

    retained = json.loads(output.read_text())
    assert retained["state"] == "unpublished"
    assert retained["releaseReady"] is False
    assert retained["installRecommendation"] is False
    assert retained["incident"]["code"] == "registry_state_unknown"
    assert retained["publishJobs"] == {"pypi": "success", "npm": "failure"}
    assert "WITHHELD" in markdown.read_text()
    assert "https://github.example/run/1" in markdown.read_text()
    assert "publication-state=unpublished" in github_output.read_text()


def test_registry_verifier_retains_machine_failure_before_exiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.2"},
                "artifacts": [],
            }
        )
    )
    output = tmp_path / "registry-verification.json"
    monkeypatch.setattr(
        verifier,
        "verify_pypi",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            verifier.VerificationMismatch("fixture mismatch")
        ),
    )

    with pytest.raises(SystemExit, match="immutable registry verification mismatch"):
        verifier.verification_main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--repository",
                "alloy-org/alloy",
                "--attempts",
                "1",
            ]
        )

    retained = json.loads(output.read_text())
    assert retained["status"] == "verification_failed"
    assert retained["manifestCommit"] == "a" * 40
    assert retained["failureCode"] == "verification_mismatch"


def test_registry_verifier_retries_propagation_before_byte_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.2"},
                "artifacts": [],
            }
        )
    )
    output = tmp_path / "registry-verification.json"
    attempts = 0

    def verify_pypi(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise verifier.VerificationUnavailable("attestations not propagated")
        return {"files": []}

    monkeypatch.setattr(verifier, "verify_pypi", verify_pypi)
    monkeypatch.setattr(
        verifier, "verify_npm", lambda *_args, **_kwargs: {"byteVerified": True}
    )

    verifier.verification_main(
        [
            "--artifacts-dir",
            str(artifacts),
            "--output",
            str(output),
            "--repository",
            "alloy-org/alloy",
            "--attempts",
            "2",
            "--initial-delay",
            "0",
            "--max-delay",
            "0",
        ]
    )

    retained = json.loads(output.read_text())
    assert attempts == 2
    assert retained["status"] == "byte_verified"
    assert retained["attempt"] == 2


def test_malformed_registry_json_is_retained_as_typed_machine_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.2"},
                "artifacts": [
                    {
                        "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                        "package": "python",
                        "sha256": "0" * 64,
                        "size": 1,
                    }
                ],
            }
        )
    )
    output = tmp_path / "registry-verification.json"
    monkeypatch.setattr(verifier, "fetch", lambda *_args, **_kwargs: b"[]")

    with pytest.raises(SystemExit, match="immutable registry verification mismatch"):
        verifier.verification_main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--repository",
                "alloy-org/alloy",
                "--attempts",
                "1",
            ]
        )

    retained = json.loads(output.read_text())
    assert retained["status"] == "verification_failed"
    assert retained["failureCode"] == "verification_mismatch"
    assert retained["failureType"] == "VerificationMismatch"


def test_registry_shape_validation_rejects_empty_integrity_and_non_object_dist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    with pytest.raises(verifier.VerificationMismatch, match="empty integrity"):
        verifier.parse_integrity("")

    monkeypatch.setattr(
        verifier,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=b"[]", stderr=b""
        ),
    )
    with pytest.raises(verifier.VerificationMismatch, match="malformed dist metadata"):
        verifier.verify_npm(
            {},
            downloads_dir=tmp_path,
            repository="alloy-org/alloy",
            commit="a" * 40,
        )


@pytest.mark.parametrize(
    "redirect",
    ["https://attacker.example/package", "http://pypi.org/package"],
)
def test_registry_redirect_handler_rejects_cross_origin_before_following(
    redirect: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    handler = verifier._SameHostHTTPSRedirectHandler("pypi.org")
    request = urllib.request.Request("https://pypi.org/source")

    with pytest.raises(verifier.VerificationMismatch, match="redirect attempted"):
        handler.redirect_request(request, None, 302, "Found", Message(), redirect)


def test_registry_redirect_handler_allows_same_https_host() -> None:
    verifier = _load_root_script("verify_published_packages.py")
    handler = verifier._SameHostHTTPSRedirectHandler("pypi.org")
    request = urllib.request.Request("https://pypi.org/source")

    redirected = handler.redirect_request(
        request, None, 302, "Found", Message(), "https://pypi.org/target"
    )

    assert redirected is not None
    assert redirected.full_url == "https://pypi.org/target"


def test_registry_fetch_rejects_initial_cross_origin_before_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    monkeypatch.setattr(
        verifier.urllib.request,
        "build_opener",
        lambda *_args, **_kwargs: pytest.fail("untrusted URL reached the opener"),
    )

    with pytest.raises(
        verifier.VerificationMismatch, match="outside the expected host"
    ):
        verifier.fetch("https://attacker.example/package", allowed_host="pypi.org")


def test_registry_verifier_retains_invalid_input_failure(
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    artifacts = tmp_path / "missing-artifacts"
    artifacts.mkdir()
    output = tmp_path / "registry-verification.json"

    with pytest.raises(SystemExit, match="release manifest could not be loaded"):
        verifier.verification_main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--repository",
                "alloy-org/alloy",
            ]
        )

    retained = json.loads(output.read_text())
    assert retained["status"] == "verification_failed"
    assert retained["failureCode"] == "invalid_release_input"
    assert retained["manifestCommit"] is None


def test_registry_verifier_retains_invalid_encoding_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    output = tmp_path / "registry-verification.json"
    manifest = {"commit": "a" * 40, "packages": {}}
    monkeypatch.setattr(verifier, "manifest_data", lambda _path: (manifest, {}))
    monkeypatch.setattr(
        verifier,
        "verify_pypi",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        ),
    )

    with pytest.raises(SystemExit, match="did not converge"):
        verifier.verification_main(
            [
                "--artifacts-dir",
                str(tmp_path),
                "--output",
                str(output),
                "--repository",
                "alloy-org/alloy",
                "--attempts",
                "1",
            ]
        )

    retained = json.loads(output.read_text())
    assert retained["status"] == "verification_failed"
    assert retained["failureCode"] == "verification_unavailable"
    assert retained["failureType"] == "UnicodeDecodeError"


def test_pypi_verification_downloads_each_file_and_checks_both_attestation_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    payloads = {
        "kaji_sdk-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji_sdk-0.2.0b1.tar.gz": b"sdist",
    }
    entries = {
        name: {
            "file": name,
            "package": "python",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        for name, payload in payloads.items()
    }
    urls = [
        {
            "filename": name,
            "url": f"https://files.pythonhosted.org/packages/{name}",
            "digests": {"sha256": entry["sha256"]},
            "size": entry["size"],
        }
        for name, entry in entries.items()
    ]
    fetched: list[str] = []

    def fetch(url: str, **_kwargs: object) -> bytes:
        fetched.append(url)
        if url == verifier.PYPI_URL:
            return json.dumps(
                {
                    "info": {"name": "kaji-sdk", "version": "0.2.0b1"},
                    "urls": urls,
                }
            ).encode()
        if "/integrity/" in url:
            return json.dumps(
                {"attestation_bundles": [{"attestations": [{}]}]}
            ).encode()
        return payloads[url.rsplit("/", 1)[1]]

    commands: list[tuple[str, ...]] = []

    def run_checked(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(verifier, "fetch", fetch)
    monkeypatch.setattr(verifier, "run_checked", run_checked)

    evidence = verifier.verify_pypi(
        entries,
        downloads_dir=tmp_path,
        repository="alloy-org/alloy",
        commit="a" * 40,
    )

    assert len(evidence["files"]) == 2
    assert all(item["byteVerified"] for item in evidence["files"])
    assert sum("/integrity/kaji-sdk/0.2.0b1/" in url for url in fetched) == 2
    assert (
        sum(
            command[:3] == ("pypi-attestations", "verify", "pypi")
            for command in commands
        )
        == 2
    )
    assert (
        sum(command[:3] == ("gh", "attestation", "verify") for command in commands) == 2
    )
    assert all(
        command[command.index("--source-digest") + 1] == "a" * 40
        for command in commands
        if command[:3] == ("gh", "attestation", "verify")
    )
    retained = {path.name for path in tmp_path.iterdir()}
    assert {
        "registry-kaji_sdk-0.2.0b1-py3-none-any.whl",
        "registry-kaji_sdk-0.2.0b1.tar.gz",
    }.issubset(retained)
    assert sum(name.endswith(".provenance.json") for name in retained) == 2
    assert sum(name.endswith(".github-attestation.json") for name in retained) == 2


@pytest.mark.parametrize(
    ("published_names", "expected_error"),
    [
        (
            ["kaji_sdk-0.2.0b1-py3-none-any.whl"],
            "VerificationUnavailable",
        ),
        (
            [
                "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "kaji_sdk-0.2.0b1.tar.gz",
                "unexpected.zip",
            ],
            "VerificationMismatch",
        ),
    ],
)
def test_pypi_missing_files_are_retryable_but_unexpected_files_are_terminal(
    published_names: list[str],
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    entries = {
        name: {"file": name, "package": "python", "sha256": "0" * 64, "size": 1}
        for name in (
            "kaji_sdk-0.2.0b1-py3-none-any.whl",
            "kaji_sdk-0.2.0b1.tar.gz",
        )
    }
    metadata = {
        "info": {"name": "kaji-sdk", "version": "0.2.0b1"},
        "urls": [{"filename": name} for name in published_names],
    }
    monkeypatch.setattr(
        verifier,
        "fetch",
        lambda *_args, **_kwargs: json.dumps(metadata).encode(),
    )

    error_type = getattr(verifier, expected_error)
    with pytest.raises(error_type):
        verifier.verify_pypi(
            entries,
            downloads_dir=tmp_path,
            repository="alloy-org/alloy",
            commit="a" * 40,
        )


def test_pypi_verifier_rejects_a_different_project_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    metadata = {
        "info": {"name": "kaji", "version": "0.2.0b1"},
        "urls": [],
    }
    monkeypatch.setattr(
        verifier,
        "fetch",
        lambda *_args, **_kwargs: json.dumps(metadata).encode(),
    )

    with pytest.raises(verifier.VerificationMismatch, match="wrong project"):
        verifier.verify_pypi(
            {},
            downloads_dir=tmp_path,
            repository="alloy-org/alloy",
            commit="a" * 40,
        )


def test_npm_missing_target_is_retryable_propagation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    def run_checked(command: list[str], **_kwargs: object) -> SimpleNamespace:
        output = (
            json.dumps(
                {
                    "verified": [
                        {
                            "name": "transitive-dependency",
                            "version": "1.0.0",
                            "attestations": [{}],
                        }
                    ]
                }
            ).encode()
            if command[:3] == ["npm", "audit", "signatures"]
            else b"{}"
        )
        return SimpleNamespace(returncode=0, stdout=output, stderr=b"")

    monkeypatch.setattr(verifier, "run_checked", run_checked)

    with pytest.raises(
        verifier.VerificationUnavailable,
        match="has not propagated the beta package",
    ):
        verifier._verify_npm_audit(
            repository_dir=audit_dir,
            evidence_file=tmp_path / "npm-signature-audit.json",
        )


@pytest.mark.parametrize(
    ("audit", "expected_error"),
    [
        (
            {"missing": [{"name": "kaji-sdk", "version": "0.2.0-beta.2"}]},
            "VerificationUnavailable",
        ),
        (
            {"invalid": [{"name": "kaji-sdk", "version": "0.2.0-beta.2"}]},
            "VerificationMismatch",
        ),
    ],
)
def test_nonzero_npm_audit_distinguishes_propagation_from_invalid_signatures(
    audit: dict[str, object],
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    monkeypatch.setattr(
        verifier,
        "run_checked",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(audit).encode(),
            stderr=b"",
        ),
    )

    with pytest.raises(getattr(verifier, expected_error)):
        verifier._run_npm_registry_command(
            ["npm", "audit", "signatures", "--json", "--include-attestations"],
            cwd=tmp_path,
        )


def test_npm_verification_checks_downloaded_sri_audit_attestation_and_github_attestation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    payload = b"npm-tarball"
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode()
    entry = {
        "file": "kaji-sdk-0.2.0-beta.2.tgz",
        "package": "typescript",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
    commands: list[tuple[str, ...]] = []

    def run_checked(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(tuple(command))
        if command[:2] == ["npm", "view"]:
            stdout = json.dumps(
                {
                    "tarball": "https://registry.npmjs.org/kaji-sdk/-/sdk.tgz",
                    "integrity": integrity,
                    "shasum": hashlib.sha1(payload).hexdigest(),  # noqa: S324
                }
            ).encode()
        elif command[:3] == ["npm", "audit", "signatures"]:
            stdout = json.dumps(
                {
                    "verified": [
                        {
                            "name": "kaji-sdk",
                            "version": "0.2.0-beta.2",
                            "attestations": [{}],
                        }
                    ]
                }
            ).encode()
        else:
            stdout = b"{}"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(verifier, "run_checked", run_checked)
    monkeypatch.setattr(verifier, "fetch", lambda *_args, **_kwargs: payload)

    evidence = verifier.verify_npm(
        {entry["file"]: entry},
        downloads_dir=tmp_path,
        repository="alloy-org/alloy",
        commit="a" * 40,
    )

    assert evidence["byteVerified"] is True
    assert evidence["signatureAudit"]["packageVerified"] is True
    assert (tmp_path / "registry-kaji-sdk-0.2.0-beta.2.tgz").read_bytes() == payload
    assert (tmp_path / "npm-signature-audit.json").is_file()
    assert (
        "npm",
        "audit",
        "signatures",
        "--json",
        "--include-attestations",
    ) in commands
    github_command = next(
        command
        for command in commands
        if command[:3] == ("gh", "attestation", "verify")
    )
    assert github_command[github_command.index("--source-digest") + 1] == "a" * 40


def test_npm_audit_retries_dependency_attestation_when_kaji_entry_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    def run_checked(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[:3] == ["npm", "audit", "signatures"]:
            stdout = json.dumps(
                {
                    "verified": [
                        {"name": "kaji-sdk", "version": "0.2.0-beta.2"},
                        {
                            "name": "transitive-dependency",
                            "version": "1.0.0",
                            "attestations": [{}],
                        },
                    ]
                }
            ).encode()
        else:
            stdout = b"{}"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(verifier, "run_checked", run_checked)

    with pytest.raises(
        verifier.VerificationUnavailable,
        match="has not propagated the beta attestation bundle",
    ):
        verifier._verify_npm_audit(
            repository_dir=audit_dir,
            evidence_file=tmp_path / "npm-signature-audit.json",
        )


def test_release_composite_actions_are_sha_pinned() -> None:
    for relative in (
        ".github/actions/setup-python-uv/action.yml",
        ".github/actions/setup-bun-cache/action.yml",
    ):
        _assert_external_actions_are_sha_pinned(_read(relative))


def test_release_runbook_has_fail_closed_rollback_contract() -> None:
    runbook = _read("docs/kaji/releasing.md")

    for expected in (
        "signed beta tag",
        "protected `kaji-beta` environment",
        "yank",
        "npm deprecate",
        "preserve",
        "never reuse",
        "No keyed provider or publisher evidence is claimed",
        "`kaji-beta-publish`",
        "Protect `kaji-v*-beta.*` tags against update and deletion",
        "annotated tag object SHA",
        "never click **Re-run failed jobs**",
        "partial_or_ambiguous",
        "never reuse either old version",
        'git tag -s -a kaji-v0.2.0-beta.2 <approved-commit> -m "Kaji 0.2.0 beta 2"',
        "npm deprecate kaji-sdk@0.2.0-beta.2",
        "compares every existing asset's",
        "SHA-256 digest",
        "`KAJI_RELEASE_SIGNER_EMAIL`",
        "does not claim a separately",
        "pending trusted publisher",
        "project `kaji-sdk`",
        "workflow `kaji.publish.yml`",
        "Land the approved release commit on the default branch",
        "Never tag a feature-branch-only commit",
        "first unscoped publication requires a short-lived",
        "after the first release, configure npm trusted publishing",
        "npm exposes no non-mutating",
        "requires `KAJI_NPM_PUBLISHER` to match `npm whoami`",
        "verifies existing `kaji-sdk` write access",
        "unambiguous `E404`",
    ):
        assert expected in runbook


def test_release_metadata_rejects_non_commit_provenance() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "kaji/scripts/verify_package_metadata.py"),
            "--release",
            "--commit",
            "not-a-commit",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "exactly 40 hexadecimal characters" in result.stderr


def test_release_metadata_queries_and_records_actual_build_tool_versions() -> None:
    verifier = _read("kaji/scripts/verify_package_metadata.py")
    setup = _read(".github/actions/setup-python-uv/action.yml")

    assert 'version: "0.11.25"' in setup
    for command in ("bun", "node", "npm", "uv"):
        assert f'tool_version("{command}", "--version")' in verifier
        assert f'"{command}": actual_tools["{command}"]' in verifier
    assert 'BUN_VERSION = "1.3.11"' in verifier
    assert 'UV_VERSION = "0.11.25"' in verifier


def test_downloaded_release_artifact_verifier_fails_closed(tmp_path: Path) -> None:
    artifacts = tmp_path / "release"
    artifacts.mkdir()
    commit = "a" * 40
    payloads = {
        "kaji_sdk-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji_sdk-0.2.0b1.tar.gz": b"sdist",
        "kaji-sdk-0.2.0-beta.2.tgz": b"npm",
    }
    entries = []
    for name, payload in payloads.items():
        (artifacts / name).write_bytes(payload)
        package = "typescript" if name.endswith(".tgz") else "python"
        version = "0.2.0-beta.2" if package == "typescript" else "0.2.0b1"
        entries.append(
            {
                "commit": commit,
                "contractVersion": "1.0.0",
                "file": name,
                "package": package,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "version": version,
            }
        )
    manifest = {
        "schemaVersion": 1,
        "commit": commit,
        "buildTools": {
            "bun": "1.3.11",
            "editables": "0.6",
            "node": "24.4.1",
            "npm": "11.4.2",
            "setuptools": "83.0.0",
            "uv": "0.11.25",
        },
        "buildAudit": {
            "file": "kaji/build-requirements.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "kaji/build-requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "packages": {
            "contract": "1.0.0",
            "python": "0.2.0b1",
            "typescript": "0.2.0-beta.2",
        },
        "artifacts": entries,
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest))
    (artifacts / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in entries)
    )
    command = [
        sys.executable,
        str(REPO_ROOT / "kaji/scripts/verify_release_artifacts.py"),
        "--artifacts-dir",
        str(artifacts),
        "--expected-commit",
        commit,
    ]

    module = _load_root_script("verify_release_artifacts.py")
    verified = module.verify(artifacts, commit)
    assert verified.root == artifacts.resolve()
    assert verified.commit == commit
    assert (
        verified.manifest_sha256
        == hashlib.sha256((artifacts / "manifest.json").read_bytes()).hexdigest()
    )
    assert (
        verified.python_wheel
        == (artifacts / "kaji_sdk-0.2.0b1-py3-none-any.whl").resolve()
    )
    assert verified.python_sdist == (artifacts / "kaji_sdk-0.2.0b1.tar.gz").resolve()
    assert verified.npm_tarball == (artifacts / "kaji-sdk-0.2.0-beta.2.tgz").resolve()
    with pytest.raises(TypeError):
        cast(MutableMapping[str, str], verified.artifact_sha256)["extra"] = (
            "not immutable"
        )

    assert subprocess.run(command, check=False).returncode == 0
    (artifacts / "kaji-sdk-0.2.0-beta.2.tgz").write_bytes(b"tampered")
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "size/hash mismatch" in result.stderr

    (artifacts / "kaji-sdk-0.2.0-beta.2.tgz").write_bytes(
        payloads["kaji-sdk-0.2.0-beta.2.tgz"]
    )
    unexpected = artifacts / "unexpected.whl"
    unexpected.write_bytes(b"extra")
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "artifact file set mismatch" in result.stderr
    unexpected.unlink()

    wheel = artifacts / "kaji_sdk-0.2.0b1-py3-none-any.whl"
    wheel.unlink()
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "artifact file set mismatch" in result.stderr
    wheel.write_bytes(payloads[wheel.name])

    npm = artifacts / "kaji-sdk-0.2.0-beta.2.tgz"
    npm.unlink()
    npm.symlink_to(wheel)
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "non-regular file or symlink" in result.stderr


def test_compatibility_matrices_consume_and_retain_frozen_artifacts() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")
    rehearsal_python = rehearsal.split("  python-compat:", 1)[1].split(
        "  node-compat:", 1
    )[0]
    rehearsal_node = rehearsal.split("  node-compat:", 1)[1].split(
        "  tthw-evidence:", 1
    )[0]
    publish_python = publish.split("  python-compat:", 1)[1].split("  node-compat:", 1)[
        0
    ]
    publish_node = publish.split("  node-compat:", 1)[1].split("  tthw-evidence:", 1)[0]

    assert "needs: offline-release" in rehearsal_python
    assert "needs: offline-release" in rehearsal_node
    assert "needs: [verify-tag, offline-gates]" in publish_python
    assert "needs: [verify-tag, offline-gates]" in publish_node

    for job, smoke in (
        (rehearsal_python, "kaji/scripts/release_smoke.py"),
        (publish_python, "kaji/scripts/release_smoke.py"),
        (rehearsal_node, "kaji/ts/scripts/smoke_package.mts"),
        (publish_node, "kaji/ts/scripts/smoke_package.mts"),
    ):
        initialize = job.index("Initialize compatibility receipt before setup")
        initial_upload = job.index("Retain initial not-run compatibility receipt")
        checkout = job.index("actions/checkout@")
        normalize = job.index("Normalize compatibility receipt")
        final_upload = job.index("Retain final compatibility receipt")
        assert initialize < initial_upload < checkout
        assert (
            job.index("actions/download-artifact@")
            < job.index("verify_release_artifacts.py")
            < job.index(smoke)
            < normalize
            < final_upload
        )
        job_environment = job.split("    strategy:", 1)[0]
        assert "${{ runner." not in job_environment
        assert "name: kaji-beta-artifacts" in job
        assert "path: .artifacts/kaji-release" in job
        assert "--expected-commit" in job
        assert "--output" in job
        assert job.count("if: ${{ always() }}") == 2
        assert job.count("uses: actions/upload-artifact@") == 2
        assert "-initial" in job
        assert "compatibility-receipt.json" in job
        assert (
            '.conclusion == "passed" and (keys == passed_keys) and .failureCode == null'
        ) in job
        assert ".githubPackageProofs" in job
        assert ".timings" in job
        assert 'keys == ["sdist", "wheel"]' in job
        assert 'keys == ["bun", "npm"]' in job
        assert "9007199254740991" in job
        assert 'runtime: "python", network: "scripted"' in job
        assert 'schemaVersion: 5, evidenceClass: "offline_exact_artifact_smoke"' in job
        assert "publicScenarioCount: 15" in job
        assert 'reason_code: "github_token_missing"' in job
        assert "githubObservabilitySinksVerified: true" in job
        assert "unknownMutationPreserved: true, mutationRetries: 0" in job
        assert 'runtime: "typescript", network: "blocked"' in job
        assert "toolCount: 15" in job
        assert "readToolCount: 13" in job
        assert 'manifestVersion: "0.1.0", toolCount: 6, readToolCount: 4' in job
        assert 'providerAlias: "github_get_file"' in job
        assert 'catalogName: "synthetic.complete"' in job
        assert 'testFile: "kaji/ts/tests/github-registry.test.ts"' in job
        assert "tokenLookups: 0, requestAttempts: 0" in job
        assert "(.bun == .npm) and" in job
        assert ".releaseManifestSha256 | sha256" in job
        assert "all(.[]; sha256)" in job
        assert "compatibility_receipt_not_terminal" in job
        assert "uv build" not in job
        assert "npm pack" not in job
        assert "bun run package:smoke" not in job

    for job in (rehearsal_python, publish_python):
        assert "--artifacts-dir .artifacts/kaji-release" in job
    for job in (rehearsal_node, publish_node):
        assert "--release-manifest .artifacts/kaji-release/manifest.json" in job
        assert '--expected-commit "$EXPECTED_COMMIT"' in job

    timing_docs = _read("docs/kaji/tthw-evidence.md")
    for path in (
        "receipt.timings.wheel",
        "receipt.timings.sdist",
        "receipt.timings.npm",
        "receipt.timings.bun",
    ):
        assert path in timing_docs


def _compatibility_normalizer_script(workflow_name: str, job_name: str) -> str:
    workflow = _read(f".github/workflows/{workflow_name}")
    next_job = "node-compat" if job_name == "python-compat" else "tthw-evidence"
    job = workflow.split(f"  {job_name}:", 1)[1].split(f"  {next_job}:", 1)[0]
    step = job.split("      - name: Normalize compatibility receipt", 1)[1].split(
        "\n      - name:", 1
    )[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    (
        ("kaji.rehearsal.yml", "python-compat"),
        ("kaji.rehearsal.yml", "node-compat"),
        ("kaji.publish.yml", "python-compat"),
        ("kaji.publish.yml", "node-compat"),
    ),
)
def test_compatibility_normalizers_require_identical_typescript_installed_proofs(
    tmp_path: Path,
    workflow_name: str,
    job_name: str,
) -> None:
    script = _compatibility_normalizer_script(workflow_name, job_name)
    assert f"test({json.dumps(_normative_semver_pattern())})" in script
    commit = "a" * 40

    def run_case(
        name: str, receipt: dict[str, object]
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "compatibility-receipt.json"
        path.write_text(json.dumps(receipt) + "\n")
        completed = subprocess.run(
            ["/bin/bash", "-c", script],
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "EXPECTED_COMMIT": commit,
                "KAJI_COMPAT_RUNTIME_KIND": "node",
                "KAJI_COMPAT_RUNTIME_VERSION": "22",
                "KAJI_COMPAT_RECEIPT_DIR": str(directory),
                "GITHUB_SERVER_URL": "https://github.example",
                "GITHUB_REPOSITORY": "example/alloy",
                "GITHUB_RUN_ID": "1234",
                "GITHUB_RUN_ATTEMPT": "1",
                "CHECKOUT_OUTCOME": "success",
                "RUNTIME_SETUP_OUTCOME": "success",
                "DEPENDENCY_SETUP_OUTCOME": "success",
                "DOWNLOAD_OUTCOME": "success",
                "VERIFICATION_OUTCOME": "success",
                "SMOKE_OUTCOME": "success",
            },
            text=True,
        )
        return completed, json.loads(path.read_text())

    proof = _github_package_proof("typescript")
    matching: dict[str, object] = {
        "schemaVersion": 1,
        "commit": commit,
        "releaseManifestSha256": "b" * 64,
        "artifactSha256": {"kaji-sdk-0.2.0-beta.2.tgz": "c" * 64},
        "runtime": {"version": "v22.1.0"},
        "artifacts": {
            "tarball": "/artifacts/kaji-sdk-0.2.0-beta.2.tgz",
            "package": "/tmp/node_modules/kaji-sdk",
        },
        "githubPackageProofs": {
            "npm": proof,
            "bun": json.loads(json.dumps(proof)),
        },
        "timings": {
            "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
            "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
        },
        "conclusion": "passed",
        "failureCode": None,
    }
    accepted, accepted_receipt = run_case("matching", matching)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert accepted_receipt["conclusion"] == "passed"

    for label, version in HOSTILE_TYPESCRIPT_CURRENT_VERSIONS:
        invalid_semver = json.loads(json.dumps(matching))
        for installer in ("npm", "bun"):
            invalid_semver["githubPackageProofs"][installer][
                "typescriptDeclarationChecks"
            ]["typescriptCurrent"]["version"] = version
        rejected, rejected_receipt = run_case(label, invalid_semver)
        assert rejected.returncode != 0
        assert rejected_receipt["conclusion"] == "not_run"
        assert rejected_receipt["failureCode"] == "compatibility_receipt_not_terminal"

    for label, field, value in (
        ("current-version-divergence", "typescriptCurrent.version", "6.0.3"),
        ("nested-policy-divergence", "policyBeforeRequest.tokenLookups", 1),
    ):
        divergent = json.loads(json.dumps(matching))
        bun_proof = divergent["githubPackageProofs"]["bun"]
        if field == "typescriptCurrent.version":
            bun_proof["typescriptDeclarationChecks"]["typescriptCurrent"]["version"] = (
                value
            )
        else:
            bun_proof["policyBeforeRequest"]["tokenLookups"] = value
        rejected, rejected_receipt = run_case(label, divergent)
        assert rejected.returncode != 0
        assert rejected_receipt["conclusion"] == "not_run"
        assert rejected_receipt["failureCode"] == "compatibility_receipt_not_terminal"


@pytest.mark.parametrize(
    ("workflow_name", "job_name", "runtime_kind", "runtime_version"),
    (
        ("kaji.rehearsal.yml", "python-compat", "python", "3.11"),
        ("kaji.rehearsal.yml", "node-compat", "node", "22"),
        ("kaji.publish.yml", "python-compat", "python", "3.14"),
        ("kaji.publish.yml", "node-compat", "node", "24"),
    ),
)
def test_compatibility_normalizer_fails_closed_across_hostile_states(
    tmp_path: Path,
    workflow_name: str,
    job_name: str,
    runtime_kind: str,
    runtime_version: str,
) -> None:
    script = _compatibility_normalizer_script(workflow_name, job_name)
    commit = "a" * 40
    base_environment = {
        **os.environ,
        "EXPECTED_COMMIT": commit,
        "KAJI_COMPAT_RUNTIME_KIND": runtime_kind,
        "KAJI_COMPAT_RUNTIME_VERSION": runtime_version,
        "GITHUB_SERVER_URL": "https://github.example",
        "GITHUB_REPOSITORY": "example/alloy",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_RUN_ATTEMPT": "1",
    }

    def run_case(
        name: str,
        *,
        receipt: dict[str, object] | None,
        raw_receipt: str | None = None,
        outcomes: tuple[str, str, str, str, str, str],
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object], bytes | None]:
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "compatibility-receipt.json"
        original: bytes | None = None
        if receipt is not None:
            path.write_text(json.dumps(receipt) + "\n")
            original = path.read_bytes()
        elif raw_receipt is not None:
            path.write_text(raw_receipt + "\n")
            original = path.read_bytes()
        environment = {
            **base_environment,
            "KAJI_COMPAT_RECEIPT_DIR": str(directory),
            "CHECKOUT_OUTCOME": outcomes[0],
            "RUNTIME_SETUP_OUTCOME": outcomes[1],
            "DEPENDENCY_SETUP_OUTCOME": outcomes[2],
            "DOWNLOAD_OUTCOME": outcomes[3],
            "VERIFICATION_OUTCOME": outcomes[4],
            "SMOKE_OUTCOME": outcomes[5],
        }
        completed = subprocess.run(
            ["/bin/bash", "-c", script],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        return completed, json.loads(path.read_text()), original

    not_run: dict[str, object] = {
        "schemaVersion": 1,
        "commit": commit,
        "conclusion": "not_run",
        "failureCode": "compatibility_not_completed",
    }
    setup_failure, setup_receipt, _ = run_case(
        "setup-failure",
        receipt=not_run,
        outcomes=("success", "failure", "skipped", "skipped", "skipped", "skipped"),
    )
    assert setup_failure.returncode == 0
    assert setup_receipt["conclusion"] == "failed"
    assert setup_receipt["failureCode"] == "runtime_setup_not_completed"
    assert setup_receipt["failedPhase"] is None
    assert setup_receipt["failureKind"] == "unknown"

    verify_failure, verify_receipt, _ = run_case(
        "verify-failure",
        receipt=None,
        outcomes=("success", "success", "success", "success", "failure", "skipped"),
    )
    assert verify_failure.returncode == 0
    assert verify_receipt["conclusion"] == "failed"
    assert verify_receipt["failureCode"] == "artifact_verification_not_completed"
    assert verify_receipt["failedPhase"] is None
    assert verify_receipt["failureKind"] == "unknown"

    all_success: tuple[str, str, str, str, str, str] = (
        "success",
        "success",
        "success",
        "success",
        "success",
        "success",
    )
    nominal_missing, nominal_receipt, _ = run_case(
        "nominal-missing",
        receipt=not_run,
        outcomes=all_success,
    )
    assert nominal_missing.returncode != 0
    assert nominal_receipt["conclusion"] == "not_run"
    assert nominal_receipt["failureCode"] == "compatibility_receipt_not_terminal"

    identity_free_passed: dict[str, object] = {
        **not_run,
        "conclusion": "passed",
        "failureCode": None,
    }

    identity_free, identity_free_receipt, _ = run_case(
        "identity-free-passed",
        receipt=identity_free_passed,
        outcomes=all_success,
    )
    assert identity_free.returncode != 0
    assert identity_free_receipt["conclusion"] == "not_run"
    assert identity_free_receipt["failureCode"] == "compatibility_receipt_not_terminal"

    if runtime_kind == "python":
        passed: dict[str, object] = {
            **identity_free_passed,
            "releaseManifestSha256": "b" * 64,
            "artifactSha256": {
                "kaji_sdk-0.2.0b1-py3-none-any.whl": "c" * 64,
                "kaji_sdk-0.2.0b1.tar.gz": "d" * 64,
            },
            "runtime": {
                "implementation": "CPython",
                "version": f"{runtime_version}.9",
                "executable": "/opt/python/bin/python",
            },
            "artifacts": {
                "wheel": "/artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sdist": "/artifacts/kaji_sdk-0.2.0b1.tar.gz",
            },
            "githubPackageProofs": {
                "wheel": _github_package_proof("python"),
                "sdist": _github_package_proof("python"),
            },
            "timings": {
                "wheel": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                "sdist": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
            },
        }
    else:
        passed = {
            **identity_free_passed,
            "releaseManifestSha256": "b" * 64,
            "artifactSha256": {"kaji-sdk-0.2.0-beta.2.tgz": "c" * 64},
            "runtime": {"version": f"v{runtime_version}.1.0"},
            "artifacts": {
                "tarball": "/artifacts/kaji-sdk-0.2.0-beta.2.tgz",
                "package": "/tmp/node_modules/kaji-sdk",
            },
            "githubPackageProofs": {
                "npm": _github_package_proof("typescript"),
                "bun": _github_package_proof("typescript"),
            },
            "timings": {
                "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
            },
        }
    valid_hashes = passed["artifactSha256"]
    short_hashes = dict(valid_hashes)
    short_hashes[next(iter(short_hashes))] = "f" * 63
    for label, invalid_hashes in (
        ("extra-artifact-hash", {**valid_hashes, "unexpected.tgz": "f" * 64}),
        ("short-artifact-hash", short_hashes),
    ):
        invalid_identity, invalid_receipt, _ = run_case(
            label,
            receipt={**passed, "artifactSha256": invalid_hashes},
            outcomes=all_success,
        )
        assert invalid_identity.returncode != 0
        assert invalid_receipt["conclusion"] == "not_run"
        assert invalid_receipt["failureCode"] == "compatibility_receipt_not_terminal"

    invalid_proofs = dict(cast(dict[str, object], passed["githubPackageProofs"]))
    first_proof = next(iter(invalid_proofs))
    invalid_proofs[first_proof] = {
        **cast(dict[str, object], invalid_proofs[first_proof]),
        "liveProvider": True,
    }
    invalid_proof, invalid_proof_receipt, _ = run_case(
        "invalid-github-package-proof",
        receipt={**passed, "githubPackageProofs": invalid_proofs},
        outcomes=all_success,
    )
    assert invalid_proof.returncode != 0
    assert invalid_proof_receipt["conclusion"] == "not_run"
    assert invalid_proof_receipt["failureCode"] == "compatibility_receipt_not_terminal"

    valid_timings = cast(dict[str, object], passed["timings"])
    first_runtime = next(iter(valid_timings))
    for label, invalid_timings in (
        ("missing-runtime-timing", {first_runtime: valid_timings[first_runtime]}),
        (
            "extra-runtime-timing",
            {**valid_timings, "extra": valid_timings[first_runtime]},
        ),
        (
            "negative-timing",
            {
                **valid_timings,
                first_runtime: {
                    **cast(dict[str, object], valid_timings[first_runtime]),
                    "warmRunMs": -1,
                },
            },
        ),
        (
            "fractional-timing",
            {
                **valid_timings,
                first_runtime: {
                    **cast(dict[str, object], valid_timings[first_runtime]),
                    "warmRunMs": 1.5,
                },
            },
        ),
        (
            "extra-timing-field",
            {
                **valid_timings,
                first_runtime: {
                    **cast(dict[str, object], valid_timings[first_runtime]),
                    "githubProof": "DO_NOT_RETAIN_PROOF",
                },
            },
        ),
    ):
        invalid_timing, invalid_timing_receipt, _ = run_case(
            label,
            receipt={**passed, "timings": invalid_timings},
            outcomes=all_success,
        )
        assert invalid_timing.returncode != 0
        assert invalid_timing_receipt["conclusion"] == "not_run"
        assert (
            invalid_timing_receipt["failureCode"]
            == "compatibility_receipt_not_terminal"
        )
        assert "timings" not in invalid_timing_receipt

    if runtime_kind == "node":
        unsafe_timings = json.loads(json.dumps(valid_timings))
        unsafe_timings[first_runtime]["coldSetupToOutputMs"] = 9007199254740992
        unsafe_timing, unsafe_timing_receipt, _ = run_case(
            "unsafe-timing",
            receipt={**passed, "timings": unsafe_timings},
            outcomes=all_success,
        )
        assert unsafe_timing.returncode != 0
        assert unsafe_timing_receipt["conclusion"] == "not_run"
        assert (
            unsafe_timing_receipt["failureCode"] == "compatibility_receipt_not_terminal"
        )
        assert "timings" not in unsafe_timing_receipt

    for label, literal in (
        ("forged-fractional-timing", "9007199254740990.5"),
        ("overflow-timing", "9007199254740992"),
        ("nonfinite-ish-timing", "1e999"),
    ):
        raw_receipt = json.dumps(passed)
        assert '"warmRunMs": 2' in raw_receipt
        raw_receipt = raw_receipt.replace(
            '"warmRunMs": 2', f'"warmRunMs": {literal}', 1
        )
        invalid_timing, invalid_timing_receipt, _ = run_case(
            label,
            receipt=None,
            raw_receipt=raw_receipt,
            outcomes=all_success,
        )
        assert invalid_timing.returncode != 0
        assert invalid_timing_receipt["conclusion"] == "not_run"
        assert (
            invalid_timing_receipt["failureCode"]
            == "compatibility_receipt_not_terminal"
        )
        assert "timings" not in invalid_timing_receipt

    if runtime_kind == "node":
        for label in (
            "typescript-schema-1",
            "typescript-schema-3",
            "typescript-alias",
            "typescript-lifecycle",
            "typescript-counts",
        ):
            invalid = json.loads(json.dumps(passed))
            proof = invalid["githubPackageProofs"]["npm"]
            if label == "typescript-schema-1":
                proof["schemaVersion"] = 1
            elif label == "typescript-schema-3":
                proof["schemaVersion"] = 3
            elif label == "typescript-alias":
                proof["packageCatalog"]["providerAliases"][0] = "github_get_issue"
            elif label == "typescript-lifecycle":
                proof["lifecycle"]["githubFailure"]["catalogName"] = (
                    "synthetic.complete"
                )
            else:
                proof["packageCatalog"]["toolCount"] = 14
                proof["packageCatalog"]["readToolCount"] = 12
            rejected, rejected_receipt, _ = run_case(
                label,
                receipt=invalid,
                outcomes=all_success,
            )
            assert rejected.returncode != 0
            assert rejected_receipt["conclusion"] == "not_run"
            assert (
                rejected_receipt["failureCode"] == "compatibility_receipt_not_terminal"
            )

    failed: dict[str, object] = {
        "schemaVersion": 1,
        "commit": commit,
        "releaseManifestSha256": None,
        "artifactSha256": {"attacker": "DO_NOT_RETAIN_ARTIFACT"},
        "runtime": {"secret": "DO_NOT_RETAIN_RUNTIME"},
        "artifacts": {"secret": "DO_NOT_RETAIN_PATH"},
        "githubPackageProofs": {"secret": "DO_NOT_RETAIN_PROOF"},
        "conclusion": "failed",
        "failureCode": "node_smoke_failed",
        "failedPhase": "npm:package-install",
        "failureKind": "timeout",
    }
    classified_failure, classified_receipt, _ = run_case(
        "classified-failure",
        receipt=failed,
        outcomes=("success", "success", "success", "success", "success", "failure"),
    )
    assert classified_failure.returncode == 0
    assert classified_receipt["conclusion"] == "failed"
    assert classified_receipt["failureCode"] == "node_smoke_failed"
    assert classified_receipt["failedPhase"] == "npm:package-install"
    assert classified_receipt["failureKind"] == "timeout"
    assert classified_receipt["artifactSha256"] == {}
    assert classified_receipt["artifacts"] == {}
    assert classified_receipt["githubPackageProofs"] == {}
    assert "timings" not in classified_receipt
    assert classified_receipt["runtime"] == {
        "kind": runtime_kind,
        "requestedVersion": runtime_version,
    }
    assert "DO_NOT_RETAIN" not in json.dumps(classified_receipt)

    rejected_timing_failure, rejected_timing_failure_receipt, _ = run_case(
        "failed-with-partial-timing",
        receipt={
            **failed,
            "timings": {
                first_runtime: {
                    "coldSetupToOutputMs": 1,
                    "warmRunMs": 2,
                }
            },
        },
        outcomes=("success", "success", "success", "success", "success", "failure"),
    )
    assert rejected_timing_failure.returncode != 0
    assert rejected_timing_failure_receipt["conclusion"] == "not_run"
    assert "timings" not in rejected_timing_failure_receipt

    for label, override in (
        ("invalid-failure-phase", {"failedPhase": "handoff:attacker"}),
        ("invalid-failure-kind", {"failureKind": "attacker"}),
        ("extra-failure-field", {"secretCanary": "DO_NOT_RETAIN_CANARY"}),
    ):
        rejected_failure, rejected_receipt, _ = run_case(
            label,
            receipt={**failed, **override},
            outcomes=("success", "success", "success", "success", "success", "failure"),
        )
        assert rejected_failure.returncode != 0
        assert rejected_receipt["conclusion"] == "not_run"
        assert rejected_receipt["failureCode"] == "compatibility_receipt_not_terminal"
        assert "DO_NOT_RETAIN" not in json.dumps(rejected_receipt)

    interrupted_passed, interrupted_receipt, _ = run_case(
        "interrupted-passed",
        receipt=passed,
        outcomes=("success", "success", "success", "success", "success", "cancelled"),
    )
    assert interrupted_passed.returncode != 0
    assert interrupted_receipt["conclusion"] == "not_run"
    assert interrupted_receipt["failureCode"] == "compatibility_receipt_not_terminal"
    assert "timings" not in interrupted_receipt

    nominal_passed, passed_receipt, original = run_case(
        "nominal-passed",
        receipt=passed,
        outcomes=all_success,
    )
    assert nominal_passed.returncode == 0
    assert passed_receipt == {
        **passed,
        "workflowRun": "https://github.example/example/alloy/actions/runs/1234",
        "workflowRunAttempt": 1,
    }
    assert (
        tmp_path / "nominal-passed/compatibility-receipt.json"
    ).read_bytes() != original


def _write_release_evidence_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _release_evidence_fixture(tmp_path: Path) -> SimpleNamespace:
    commit = "a" * 40
    workflow_run = "https://github.com/kaji-dev/alloy/actions/runs/123"
    workflow_run_attempt = 1
    release_artifact_id = "456"
    release_artifact_digest = "b" * 64
    artifacts_dir = tmp_path / "release"
    artifacts_dir.mkdir()
    payloads = {
        "kaji_sdk-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji_sdk-0.2.0b1.tar.gz": b"sdist",
        "kaji-sdk-0.2.0-beta.2.tgz": b"npm",
    }
    entries: list[dict[str, object]] = []
    for name, payload in payloads.items():
        (artifacts_dir / name).write_bytes(payload)
        package = "typescript" if name.endswith(".tgz") else "python"
        entries.append(
            {
                "commit": commit,
                "contractVersion": "1.0.0",
                "file": name,
                "package": package,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "version": ("0.2.0-beta.2" if package == "typescript" else "0.2.0b1"),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "commit": commit,
        "buildTools": {
            "bun": "1.3.11",
            "editables": "0.6",
            "node": "24.4.1",
            "npm": "11.4.2",
            "setuptools": "83.0.0",
            "uv": "0.11.25",
        },
        "buildAudit": {
            "file": "kaji/build-requirements.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "kaji/build-requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "packages": {
            "contract": "1.0.0",
            "python": "0.2.0b1",
            "typescript": "0.2.0-beta.2",
        },
        "artifacts": entries,
    }
    _write_release_evidence_json(artifacts_dir / "manifest.json", manifest)
    (artifacts_dir / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in entries)
    )
    manifest_hash = hashlib.sha256(
        (artifacts_dir / "manifest.json").read_bytes()
    ).hexdigest()
    artifact_hashes = {str(entry["file"]): str(entry["sha256"]) for entry in entries}
    runtime_artifacts = {
        "python": {
            "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
            "sha256": artifact_hashes["kaji_sdk-0.2.0b1-py3-none-any.whl"],
        },
        "typescript": {
            "file": "kaji-sdk-0.2.0-beta.2.tgz",
            "sha256": artifact_hashes["kaji-sdk-0.2.0-beta.2.tgz"],
        },
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider_packages = {
        "python": "/opt/kaji-installed-release-provider/python/lib/python3.11/site-packages/kaji/__init__.py",
        "typescript": "/opt/kaji-installed-release-provider/typescript/node_modules/kaji-sdk",
    }
    soak_packages = {
        "python": "/opt/kaji-installed-release-soak/python/lib/python3.11/site-packages/kaji/__init__.py",
        "typescript": "/opt/kaji-installed-release-soak/typescript/node_modules/kaji-sdk",
    }
    run_identity = {
        "workflowRun": workflow_run,
        "workflowRunAttempt": workflow_run_attempt,
    }

    evidence_dir = tmp_path / "evidence"
    paths = {
        "compat-python-3.11": evidence_dir / "compat-python-3.11.json",
        "compat-python-3.14": evidence_dir / "compat-python-3.14.json",
        "compat-node-22": evidence_dir / "compat-node-22.json",
        "compat-node-24": evidence_dir / "compat-node-24.json",
        "performance-status": evidence_dir / "performance-status.json",
        "benchmark-results": evidence_dir / "paired-benchmark-results.json",
        "soak-results": evidence_dir / "soak-results.json",
        "performance-image-data": evidence_dir / "performance-imagedata.json",
        "provider-evidence": evidence_dir / "provider-evidence.json",
        "tthw-status": evidence_dir / "tthw/status.json",
        "tthw-evidence": evidence_dir / "tthw/tthw-evidence.json",
    }
    performance_image_data = (
        b'[{"detail":"macOS\\n15.7.7\\n24G720","group":"Operating System"},'
        b'{"detail":"Image: macos-15-arm64\\nVersion: 20260715.0234.1\\n'
        b"Included Software: https://github.com/actions/runner-images/blob/"
        b"macos-15-arm64/20260715.0234/images/macos/"
        b"macos-15-arm64-Readme.md\\nImage Release: https://github.com/actions/"
        b'runner-images/releases/tag/macos-15-arm64%2F20260715.0234",'
        b'"group":"Runner Image"}]\n'
    )
    paths["performance-image-data"].parent.mkdir(parents=True, exist_ok=True)
    paths["performance-image-data"].write_bytes(performance_image_data)
    performance_image_data_hash = hashlib.sha256(performance_image_data).hexdigest()
    paired_image_dir = evidence_dir / "raw" / "benchmarks"
    paired_image_dir.mkdir(parents=True)
    for replica in (1, 2, 3):
        (paired_image_dir / f"replica-{replica}-imagedata.json").write_bytes(
            performance_image_data
        )

    for version in ("3.11", "3.14"):
        _write_release_evidence_json(
            paths[f"compat-python-{version}"],
            {
                "schemaVersion": 1,
                "commit": commit,
                "releaseManifestSha256": manifest_hash,
                "artifactSha256": {
                    name: artifact_hashes[name]
                    for name in (
                        "kaji_sdk-0.2.0b1-py3-none-any.whl",
                        "kaji_sdk-0.2.0b1.tar.gz",
                    )
                },
                "runtime": {
                    "implementation": "CPython",
                    "version": f"{version}.9",
                    "executable": f"/opt/python/{version}/bin/python",
                },
                "artifacts": {
                    "wheel": "/artifacts/kaji_sdk-0.2.0b1-py3-none-any.whl",
                    "sdist": "/artifacts/kaji_sdk-0.2.0b1.tar.gz",
                },
                "githubPackageProofs": {
                    "wheel": _github_package_proof("python"),
                    "sdist": _github_package_proof("python"),
                },
                "timings": {
                    "wheel": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                    "sdist": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
                },
                "conclusion": "passed",
                "failureCode": None,
                **run_identity,
            },
        )
    for version in ("22", "24"):
        _write_release_evidence_json(
            paths[f"compat-node-{version}"],
            {
                "schemaVersion": 1,
                "commit": commit,
                "releaseManifestSha256": manifest_hash,
                "artifactSha256": {
                    "kaji-sdk-0.2.0-beta.2.tgz": artifact_hashes[
                        "kaji-sdk-0.2.0-beta.2.tgz"
                    ]
                },
                "runtime": {"version": f"v{version}.14.0"},
                "artifacts": {
                    "tarball": "/artifacts/kaji-sdk-0.2.0-beta.2.tgz",
                    "package": f"/opt/kaji-node-{version}/node_modules/kaji-sdk",
                },
                "githubPackageProofs": {
                    "npm": _github_package_proof("typescript"),
                    "bun": _github_package_proof("typescript"),
                },
                "timings": {
                    "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                    "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
                },
                "conclusion": "passed",
                "failureCode": None,
                **run_identity,
            },
        )

    fingerprint = {
        "runner": {
            "environment": "github-hosted",
            "os": "Darwin",
            "arch": "arm64",
            "platformVersion": "15.7.7",
            "imageOS": "macos15",
            "imageLabel": "macos-15-arm64",
            "imageVersion": "20260715.0234.1",
            "imageDataSha256": performance_image_data_hash,
        },
        "dependencyLockHash": "d" * 64,
        "sourceHash": "e" * 64,
    }
    pair = _load_root_script("paired_benchmark.py")
    reference_record = pair._load_reference()
    paired_artifacts = {
        "pythonWheel": runtime_artifacts["python"],
        "pythonSdist": {
            "file": "kaji_sdk-0.2.0b1.tar.gz",
            "sha256": artifact_hashes["kaji_sdk-0.2.0b1.tar.gz"],
        },
        "typescript": runtime_artifacts["typescript"],
    }
    candidate = {
        "commit": commit,
        "releaseManifestSha256": manifest_hash,
        "artifacts": paired_artifacts,
    }
    runner_evidence = {
        "runner": fingerprint["runner"],
        "versions": {
            "python": "3.11.9",
            "node": "v22.14.0",
            "bun": "1.3.11",
        },
        "dependencyLockHash": reference_record["dependencyLockHash"],
    }
    paired_support = _load_test_support("test_paired_benchmark.py")
    replica_receipts: dict[str, dict[str, object]] = {}
    for replica in (1, 2, 3):
        raw_replica = paired_support._complete_report(pair, replica=replica)
        raw_replica["candidate"] = candidate
        raw_replica["candidateReceiptSha256"] = pair._json_sha256(candidate)
        raw_replica["runnerEvidence"] = {
            **runner_evidence,
            "invocation": {
                "runId": 123,
                "runAttempt": workflow_run_attempt,
                "job": "paired-replica",
                "runnerName": "GitHub Actions",
                "workflowRef": (
                    "kaji-dev/alloy/.github/workflows/"
                    "kaji.performance.yml@refs/heads/main"
                ),
                "workflowSha": commit,
            },
        }
        raw_replica["reportReceiptSha256"] = pair._json_sha256(
            {
                key: value
                for key, value in raw_replica.items()
                if key != "reportReceiptSha256"
            }
        )
        pair._validate_replica_report(raw_replica)
        _write_release_evidence_json(
            paired_image_dir / f"replica-{replica}.json",
            raw_replica,
        )
        replica_receipts[str(replica)] = {
            "reportReceiptSha256": raw_replica["reportReceiptSha256"],
            "runnerEvidence": raw_replica["runnerEvidence"],
        }
    benchmark = {
        "schemaVersion": 1,
        "kind": "kaji-beta-paired-benchmark-aggregate",
        "generatedAt": "2026-07-24T00:00:00+00:00",
        "protocolHash": pair._protocol_hash(),
        "threshold": 1.2,
        "referenceRecordSha256": pair._file_sha256(pair.REFERENCE_PATH),
        "reference": pair._reference_identity(reference_record),
        "candidate": candidate,
        "referenceReceiptSha256": pair._json_sha256(
            pair._reference_identity(reference_record)
        ),
        "candidateReceiptSha256": pair._json_sha256(candidate),
        "replicas": replica_receipts,
        "cases": {
            runtime: {
                case: {
                    "durationRatios": [1.0, 1.0, 1.0],
                    "rssRatios": [1.0, 1.0, 1.0],
                    "durationVerdict": "pass",
                    "rssVerdict": "pass",
                    "verdict": "pass",
                }
                for case in pair.CASES
            }
            for runtime in pair.RUNTIMES
        },
        "failures": [],
        "passed": True,
    }
    benchmark["reportReceiptSha256"] = pair._json_sha256(benchmark)
    soak = {
        "schemaVersion": 1,
        "protected": True,
        "commit": commit,
        "fingerprint": fingerprint,
        "releaseManifestSha256": manifest_hash,
        "artifacts": runtime_artifacts,
        "resolvedPackages": soak_packages,
        "requestedMinutes": 30,
        "results": {
            runtime: {"resolvedPackage": package}
            for runtime, package in soak_packages.items()
        },
        "failures": [],
        "passed": True,
    }
    _write_release_evidence_json(paths["soak-results"], soak)
    _write_release_evidence_json(paths["benchmark-results"], benchmark)
    soak_receipt = hashlib.sha256(paths["soak-results"].read_bytes()).hexdigest()
    _write_release_evidence_json(
        paths["performance-status"],
        {
            "schemaVersion": 2,
            "kind": "kaji-beta-performance-status",
            "commit": commit,
            "conclusion": "passed",
            "failureCode": None,
            "benchmarkOutcome": "success",
            "soakOutcome": "success",
            "validationOutcome": "success",
            "releaseArtifactId": release_artifact_id,
            "releaseArtifactDigest": release_artifact_digest,
            "releaseManifestSha256": manifest_hash,
            "artifacts": paired_artifacts,
            "benchmarkReceiptSha256": benchmark["reportReceiptSha256"],
            "soakReceiptSha256": soak_receipt,
            **run_identity,
        },
    )

    proof_rows = []
    for sdk, provider in (
        ("python", "openai"),
        ("typescript", "openai"),
        ("python", "anthropic"),
        ("typescript", "anthropic"),
    ):
        artifact = runtime_artifacts[sdk]
        call_id = f"{sdk}-{provider}-call"
        proof_rows.append(
            {
                "sdk": sdk,
                "provider": provider,
                "proof": "real_normalized_tool_loop",
                "status": "passed",
                "model": f"{provider}-test-model",
                "artifactFile": artifact["file"],
                "artifactSha256": artifact["sha256"],
                "releaseManifestSha256": manifest_hash,
                "resolvedPackage": provider_packages[sdk],
                "requestedToolCalls": 1,
                "completedToolCalls": 1,
                "requestedToolCallIds": [call_id],
                "completedToolCallIds": [call_id],
                "echoResultMatched": True,
                "finalTextPresent": True,
                "forbiddenTerminalEvents": [],
            }
        )
    _write_release_evidence_json(
        paths["provider-evidence"],
        {
            "schemaVersion": 1,
            "commit": commit,
            "releaseManifestSha256": manifest_hash,
            "artifacts": runtime_artifacts,
            "conclusion": "passed",
            "failureCode": None,
            "proofs": proof_rows,
            "releaseArtifactId": release_artifact_id,
            "releaseArtifactDigest": release_artifact_digest,
            **run_identity,
        },
    )

    toolchain = {
        "python": "3.14.6",
        "uv": "0.11.25",
        "node": "24.4.1",
        "npm": "11.4.2",
        "bun": "1.3.11",
        "typescript": "5.7.3",
    }
    tthw_runs = []
    for index, path_name in enumerate(("python", "npm", "bun", "python", "npm"), 1):
        artifact_file = (
            "kaji_sdk-0.2.0b1-py3-none-any.whl"
            if path_name == "python"
            else "kaji-sdk-0.2.0-beta.2.tgz"
        )
        artifact_package = "python" if path_name == "python" else "typescript"
        artifact_version = "0.2.0b1" if path_name == "python" else "0.2.0-beta.2"
        tthw_runs.append(
            {
                "participantId": f"user-{index:03d}",
                "commit": commit,
                "releaseManifestSha256": manifest_hash,
                "artifact": {
                    "name": artifact_file,
                    "package": artifact_package,
                    "version": artifact_version,
                    "sha256": artifact_hashes[artifact_file],
                },
                "os": "macos",
                "architecture": "arm64",
                "platformVersion": "15.5",
                "path": path_name,
                "cleanEnvironment": True,
                "noSourceCheckout": True,
                "toolchain": toolchain,
                "steps": [
                    {"name": name, "durationMs": 10_000}
                    for name in (
                        "artifact-install",
                        "scaffold-init",
                        "no-key-run",
                        "echo-setup",
                        "echo-run",
                    )
                ],
                "noKeyTotalMs": 30_000,
                "echoTotalMs": 50_000,
                "assertions": {
                    "deterministicText": True,
                    "nonEmptyTurnId": True,
                    "positiveSequence": True,
                    "echoToolRequested": True,
                    "echoToolStarted": True,
                    "echoToolCompleted": True,
                    "echoResultObserved": True,
                },
                "confusion": [],
                "redacted": True,
                "owner": "kaji-maintainer",
                "reviewDate": "2026-07-13",
                "followUpDate": "2026-08-13",
            }
        )
    tthw = {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": manifest_hash,
        "artifacts": [
            {
                "name": entry["file"],
                "package": entry["package"],
                "version": entry["version"],
                "size": entry["size"],
                "sha256": entry["sha256"],
            }
            for entry in entries
        ],
        "automatedTimings": {
            name: {
                "coldSetupToOutputMs": 10_000,
                "warmRunMs": 500,
                "toolchain": toolchain,
            }
            for name in ("python", "npm", "bun")
        },
        "humanRuns": tthw_runs,
        "summary": {
            "noKeyMedianMs": 30_000,
            "noKeyMaxMs": 30_000,
            "echoMedianMs": 50_000,
            "echoMaxMs": 50_000,
        },
    }
    _write_release_evidence_json(paths["tthw-evidence"], tthw)
    _write_release_evidence_json(
        paths["tthw-status"],
        {
            "schemaVersion": 1,
            "commit": commit,
            "conclusion": "passed",
            "failureCode": None,
            "exitCode": 0,
            "releaseManifestSha256": manifest_hash,
            "artifactSha256": artifact_hashes,
            **run_identity,
        },
    )

    output = evidence_dir / "release-evidence-validation.json"
    command = [
        sys.executable,
        str(REPO_ROOT / "kaji/scripts/validate_release_evidence.py"),
        "--artifacts-dir",
        str(artifacts_dir),
        "--expected-commit",
        commit,
        "--workflow-run",
        workflow_run,
        "--workflow-run-attempt",
        str(workflow_run_attempt),
        "--release-artifact-id",
        release_artifact_id,
        "--release-artifact-digest",
        release_artifact_digest,
        "--python-compat-311",
        str(paths["compat-python-3.11"]),
        "--python-compat-314",
        str(paths["compat-python-3.14"]),
        "--node-compat-22",
        str(paths["compat-node-22"]),
        "--node-compat-24",
        str(paths["compat-node-24"]),
        "--performance-status",
        str(paths["performance-status"]),
        "--benchmark-results",
        str(paths["benchmark-results"]),
        "--soak-results",
        str(paths["soak-results"]),
        "--performance-image-data",
        str(paths["performance-image-data"]),
        "--provider-evidence",
        str(paths["provider-evidence"]),
        "--tthw-status",
        str(paths["tthw-status"]),
        "--tthw-evidence",
        str(paths["tthw-evidence"]),
        "--workspace",
        str(workspace),
        "--output",
        str(output),
    ]
    return SimpleNamespace(
        command=command,
        output=output,
        paths=paths,
        workspace=workspace,
        artifact_hashes=artifact_hashes,
        manifest_hash=manifest_hash,
    )


def test_release_evidence_validator_requires_identical_typescript_installed_proofs() -> (
    None
):
    validator = _load_root_script("validate_release_evidence.py")
    assert validator.SEMVER.pattern == _normative_semver_pattern()
    proof = _github_package_proof("typescript")
    matching = {
        "npm": proof,
        "bun": json.loads(json.dumps(proof)),
    }

    validator.validate_github_package_proofs(matching, "typescript")

    hostile_mutations = {
        "schema-v4": ("schemaVersion", 4),
        "scenario-count-14": ("publicScenarioCount", 14),
        "mutation-retry": ("mutationRetries", 1),
        "unknown-mutation-false": ("unknownMutationPreserved", False),
    }
    for label, (field, value) in hostile_mutations.items():
        invalid = json.loads(json.dumps(matching))
        for installer in ("npm", "bun"):
            invalid[installer][field] = value
        with pytest.raises(RuntimeError) as error:
            validator.validate_github_package_proofs(invalid, "typescript")
        assert str(error.value) == "github_package_proof_invalid", label

    for field in (
        "githubFailureRecovery",
        "githubObservabilitySinksVerified",
        "unknownMutationPreserved",
        "mutationRetries",
    ):
        missing = json.loads(json.dumps(matching))
        for installer in ("npm", "bun"):
            del missing[installer][field]
        with pytest.raises(RuntimeError) as error:
            validator.validate_github_package_proofs(missing, "typescript")
        assert str(error.value) == "github_package_proof_invalid", field

    extra = json.loads(json.dumps(matching))
    for installer in ("npm", "bun"):
        extra[installer]["secretCanary"] = "sk-proof-canary"
    with pytest.raises(RuntimeError) as extra_error:
        validator.validate_github_package_proofs(extra, "typescript")
    assert str(extra_error.value) == "github_package_proof_invalid"

    for _, version in HOSTILE_TYPESCRIPT_CURRENT_VERSIONS:
        invalid_semver = json.loads(json.dumps(matching))
        for installer in ("npm", "bun"):
            invalid_semver[installer]["typescriptDeclarationChecks"][
                "typescriptCurrent"
            ]["version"] = version
        with pytest.raises(RuntimeError) as semver_error:
            validator.validate_github_package_proofs(invalid_semver, "typescript")
        assert str(semver_error.value) == "github_package_proof_invalid"

    version_divergent = json.loads(json.dumps(matching))
    version_divergent["bun"]["typescriptDeclarationChecks"]["typescriptCurrent"][
        "version"
    ] = "6.0.3"
    with pytest.raises(RuntimeError) as version_error:
        validator.validate_github_package_proofs(version_divergent, "typescript")
    assert str(version_error.value) == "github_package_proof_invalid"

    nested_divergent = json.loads(json.dumps(matching))
    nested_divergent["bun"]["policyBeforeRequest"]["tokenLookups"] = 1
    with pytest.raises(RuntimeError) as nested_error:
        validator.validate_github_package_proofs(nested_divergent, "typescript")
    assert str(nested_error.value) == "github_package_proof_invalid"


def test_release_evidence_validator_accepts_one_canonical_current_run(
    tmp_path: Path,
) -> None:
    fixture = _release_evidence_fixture(tmp_path)

    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(fixture.output.read_text())
    assert summary["conclusion"] == "passed"
    assert summary["failureCode"] is None
    assert summary["failures"] == []
    assert summary["releaseManifestSha256"] == fixture.manifest_hash
    assert summary["artifactSha256"] == fixture.artifact_hashes
    assert summary["validatedEvidence"] == sorted(fixture.paths)
    for replica in (1, 2, 3):
        raw_replica = (
            fixture.paths["benchmark-results"].parent
            / f"raw/benchmarks/replica-{replica}.json"
        )
        assert summary["receiptSha256"][f"paired-replica-{replica}"] == (
            hashlib.sha256(raw_replica.read_bytes()).hexdigest()
        )
    first = fixture.output.read_bytes()
    repeated = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert repeated.returncode == 0
    assert fixture.output.read_bytes() == first
    assert repeated.stdout == completed.stdout


def test_release_evidence_fixture_uses_producer_valid_performance_image_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _release_evidence_fixture(tmp_path)
    module = _load_root_script("benchmark_platform.py")
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "macOS",
        "RUNNER_ARCH": "ARM64",
        "ImageOS": "macos15",
        "ImageVersion": "20260715.0234.1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        module.platform, "mac_ver", lambda: ("15.7.7", ("", "", ""), "")
    )

    runner = module.require_github_hosted_macos_arm64(
        protected=True,
        calibrating=False,
        image_data_path=fixture.paths["performance-image-data"],
    )

    soak = json.loads(fixture.paths["soak-results"].read_text())
    assert runner == soak["fingerprint"]["runner"]


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("missing_receipt", "evidence_missing"),
        ("not_run_receipt", "receipt_not_passed"),
        ("failed_receipt", "receipt_not_passed"),
        ("mixed_manifest", "manifest_hash_mismatch"),
        ("stale_workflow_run", "workflow_run_mismatch"),
        ("prior_artifact_id", "release_artifact_id_mismatch"),
        ("invalid_github_proof", "github_package_proof_invalid"),
        ("invalid_ts_schema_1", "github_package_proof_invalid"),
        ("invalid_ts_schema_3", "github_package_proof_invalid"),
        ("invalid_ts_alias", "github_package_proof_invalid"),
        ("invalid_ts_lifecycle", "github_package_proof_invalid"),
        ("invalid_ts_counts", "github_package_proof_invalid"),
        ("invalid_ts_proof_version_divergence", "github_package_proof_invalid"),
        ("source_path", "source_path_detected"),
        ("legacy_performance_runner", "performance_runner_invalid"),
        ("extra_performance_runner", "performance_runner_invalid"),
        ("linux_performance_runner", "performance_runner_invalid"),
        ("self_hosted_performance_runner", "performance_runner_invalid"),
        ("wrong_performance_image", "performance_runner_invalid"),
        ("wrong_performance_version", "performance_runner_invalid"),
        ("paired_protocol_mismatch", "paired_benchmark_protocol_mismatch"),
        ("paired_candidate_mismatch", "artifact_hash_mismatch"),
        ("paired_receipt_mismatch", "paired_benchmark_receipt_mismatch"),
        ("forged_paired_ratio", "performance_results_invalid"),
        ("stale_paired_run", "paired_benchmark_invocation_mismatch"),
        ("missing_performance_image_data", "evidence_missing"),
        (
            "tampered_performance_image_data",
            "performance_image_data_hash_mismatch",
        ),
        ("missing_paired_image_data", "evidence_missing"),
        ("tampered_paired_image_data", "paired_image_data_hash_mismatch"),
        ("missing_raw_paired_replica", "evidence_missing"),
        ("tampered_raw_paired_replica", "paired_raw_replica_mismatch"),
        ("missing_provider_cell", "provider_cells_mismatch"),
        ("mixed_tthw_status", "artifact_hash_mismatch"),
        ("invalid_tthw_raw", "tthw_evidence_invalid"),
    ),
)
def test_release_evidence_validator_rejects_hostile_retained_receipts(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    fixture = _release_evidence_fixture(tmp_path)
    if hostile_case == "missing_receipt":
        fixture.paths["compat-python-3.11"].unlink()
    elif hostile_case == "missing_performance_image_data":
        fixture.paths["performance-image-data"].unlink()
    elif hostile_case == "tampered_performance_image_data":
        fixture.paths["performance-image-data"].write_bytes(b"tampered\n")
    elif hostile_case == "missing_paired_image_data":
        (
            fixture.paths["benchmark-results"].parent
            / "raw/benchmarks/replica-2-imagedata.json"
        ).unlink()
    elif hostile_case == "tampered_paired_image_data":
        (
            fixture.paths["benchmark-results"].parent
            / "raw/benchmarks/replica-2-imagedata.json"
        ).write_bytes(b"tampered\n")
    elif hostile_case == "missing_raw_paired_replica":
        (
            fixture.paths["benchmark-results"].parent / "raw/benchmarks/replica-2.json"
        ).unlink()
    elif hostile_case == "tampered_raw_paired_replica":
        raw_replica_path = (
            fixture.paths["benchmark-results"].parent / "raw/benchmarks/replica-2.json"
        )
        raw_replica = json.loads(raw_replica_path.read_text())
        raw_replica["runnerEvidence"]["invocation"]["runnerName"] = "Tampered Runner"
        pair = _load_root_script("paired_benchmark.py")
        raw_replica["reportReceiptSha256"] = pair._json_sha256(
            {
                key: value
                for key, value in raw_replica.items()
                if key != "reportReceiptSha256"
            }
        )
        _write_release_evidence_json(raw_replica_path, raw_replica)
    else:
        target = {
            "not_run_receipt": "compat-python-3.11",
            "failed_receipt": "compat-node-22",
            "mixed_manifest": "soak-results",
            "stale_workflow_run": "performance-status",
            "prior_artifact_id": "provider-evidence",
            "invalid_github_proof": "compat-python-3.11",
            "invalid_ts_schema_1": "compat-node-22",
            "invalid_ts_schema_3": "compat-node-22",
            "invalid_ts_alias": "compat-node-22",
            "invalid_ts_lifecycle": "compat-node-22",
            "invalid_ts_counts": "compat-node-22",
            "invalid_ts_proof_version_divergence": "compat-node-22",
            "source_path": "soak-results",
            "legacy_performance_runner": "soak-results",
            "extra_performance_runner": "soak-results",
            "linux_performance_runner": "soak-results",
            "self_hosted_performance_runner": "soak-results",
            "wrong_performance_image": "soak-results",
            "wrong_performance_version": "soak-results",
            "paired_protocol_mismatch": "benchmark-results",
            "paired_candidate_mismatch": "benchmark-results",
            "paired_receipt_mismatch": "benchmark-results",
            "forged_paired_ratio": "benchmark-results",
            "stale_paired_run": "benchmark-results",
            "missing_provider_cell": "provider-evidence",
            "mixed_tthw_status": "tthw-status",
            "invalid_tthw_raw": "tthw-evidence",
        }[hostile_case]
        path = fixture.paths[target]
        document = json.loads(path.read_text())
        if hostile_case == "not_run_receipt":
            document["conclusion"] = "not_run"
            document["failureCode"] = "compatibility_not_completed"
        elif hostile_case == "failed_receipt":
            document["conclusion"] = "failed"
            document["failureCode"] = "compatibility_smoke_not_completed"
        elif hostile_case == "mixed_manifest":
            document["releaseManifestSha256"] = "0" * 64
        elif hostile_case == "stale_workflow_run":
            document["workflowRun"] = (
                "https://github.com/kaji-dev/alloy/actions/runs/122"
            )
        elif hostile_case == "prior_artifact_id":
            document["releaseArtifactId"] = "455"
        elif hostile_case == "invalid_github_proof":
            document["githubPackageProofs"]["wheel"]["liveProvider"] = True
        elif hostile_case == "invalid_ts_schema_1":
            document["githubPackageProofs"]["npm"]["schemaVersion"] = 1
        elif hostile_case == "invalid_ts_schema_3":
            document["githubPackageProofs"]["npm"]["schemaVersion"] = 3
        elif hostile_case == "invalid_ts_alias":
            document["githubPackageProofs"]["npm"]["packageCatalog"]["providerAliases"][
                0
            ] = "github_get_issue"
        elif hostile_case == "invalid_ts_lifecycle":
            document["githubPackageProofs"]["npm"]["lifecycle"]["githubFailure"][
                "catalogName"
            ] = "synthetic.complete"
        elif hostile_case == "invalid_ts_counts":
            document["githubPackageProofs"]["npm"]["packageCatalog"]["toolCount"] = 14
            document["githubPackageProofs"]["npm"]["packageCatalog"][
                "readToolCount"
            ] = 12
        elif hostile_case == "invalid_ts_proof_version_divergence":
            document["githubPackageProofs"]["bun"]["typescriptDeclarationChecks"][
                "typescriptCurrent"
            ]["version"] = "6.0.3"
        elif hostile_case == "source_path":
            document["resolvedPackages"]["typescript"] = str(
                fixture.workspace / "kaji/ts/dist/node_modules/kaji-sdk"
            )
        elif hostile_case == "legacy_performance_runner":
            document["fingerprint"]["runner"] = {"imageDigest": "sha256:" + "0" * 64}
        elif hostile_case == "extra_performance_runner":
            document["fingerprint"]["runner"]["extra"] = True
        elif hostile_case == "linux_performance_runner":
            document["fingerprint"]["runner"]["os"] = "Linux"
        elif hostile_case == "self_hosted_performance_runner":
            document["fingerprint"]["runner"]["environment"] = "self-hosted"
        elif hostile_case == "wrong_performance_image":
            document["fingerprint"]["runner"]["imageLabel"] = "macos-14-arm64"
        elif hostile_case == "wrong_performance_version":
            document["fingerprint"]["runner"]["imageVersion"] = "weekly"
        elif hostile_case == "paired_protocol_mismatch":
            document["protocolHash"] = "0" * 64
        elif hostile_case == "paired_candidate_mismatch":
            document["candidate"]["artifacts"]["typescript"]["sha256"] = "0" * 64
        elif hostile_case == "paired_receipt_mismatch":
            document["reportReceiptSha256"] = "0" * 64
        elif hostile_case == "forged_paired_ratio":
            document["cases"]["python"]["replay10k"]["durationRatios"][0] = 1.1
        elif hostile_case == "stale_paired_run":
            document["replicas"]["3"]["runnerEvidence"]["invocation"]["runId"] = 122
        elif hostile_case == "missing_provider_cell":
            document["proofs"].pop()
        elif hostile_case == "mixed_tthw_status":
            document["artifactSha256"]["kaji-sdk-0.2.0-beta.2.tgz"] = "0" * 64
        else:
            document["artifacts"][0]["sha256"] = "0" * 64
        if target == "benchmark-results" and hostile_case != "paired_receipt_mismatch":
            pair = _load_root_script("paired_benchmark.py")
            if hostile_case == "stale_paired_run":
                raw_replica_path = (
                    fixture.paths["benchmark-results"].parent
                    / "raw/benchmarks/replica-3.json"
                )
                raw_replica = json.loads(raw_replica_path.read_text())
                raw_replica["runnerEvidence"] = document["replicas"]["3"][
                    "runnerEvidence"
                ]
                raw_replica["reportReceiptSha256"] = pair._json_sha256(
                    {
                        key: value
                        for key, value in raw_replica.items()
                        if key != "reportReceiptSha256"
                    }
                )
                _write_release_evidence_json(raw_replica_path, raw_replica)
                document["replicas"]["3"]["reportReceiptSha256"] = raw_replica[
                    "reportReceiptSha256"
                ]
            document["reportReceiptSha256"] = pair._json_sha256(
                {
                    key: value
                    for key, value in document.items()
                    if key != "reportReceiptSha256"
                }
            )
        _write_release_evidence_json(path, document)
        if hostile_case == "forged_paired_ratio":
            status_path = fixture.paths["performance-status"]
            status = json.loads(status_path.read_text())
            status["benchmarkReceiptSha256"] = document["reportReceiptSha256"]
            _write_release_evidence_json(status_path, status)

    first = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert first.returncode != 0
    summary = json.loads(fixture.output.read_text())
    assert summary["conclusion"] == "failed"
    assert summary["failureCode"] == "release_evidence_validation_failed"
    assert expected_code in {failure["code"] for failure in summary["failures"]}
    first_output = fixture.output.read_bytes()
    repeated = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert repeated.returncode != 0
    assert fixture.output.read_bytes() == first_output
    assert repeated.stdout == first.stdout


def test_github_exact_artifact_proof_contract_and_operator_wiring() -> None:
    contract_checker = _load_root_script("check_beta_contract.py")
    assert "release/github-proof-v1.schema.json" in contract_checker.REQUIRED_JSON

    live = _read("kaji/scripts/live_github_proof.py")
    cleanup = _read("kaji/scripts/github_proof_cleanup.py")
    documentation = _read("docs/kaji/integration-manifests.md")
    release_matrix = _read("kaji/RELEASE_MATRIX.md")
    for option in (
        "--artifacts-dir",
        "--expected-commit",
        "--python-compat",
        "--typescript-compat",
        "--fixture",
        "--state",
        "--output",
    ):
        assert option in live
    assert "--state" in cleanup
    assert "--expected-commit" in cleanup
    assert "--confirm-absence" in cleanup
    assert "GitHub remains experimental" in documentation
    assert "GMAIL_RUNTIME_NOT_IN_REVIEWED_CHECKPOINT" in documentation
    assert "confirm-absence" in documentation
    assert "Exact-artifact GitHub proof" in release_matrix
