from __future__ import annotations

import base64
from email.message import Message
import importlib.util
from io import BytesIO
import re
import struct
import subprocess
import sys
import hashlib
import json
import os
from pathlib import Path
import tarfile
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, MutableMapping, NoReturn, cast
import textwrap
import urllib.request
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE_IDENTITY_ACTIVE_ROOTS = (".github", "apps", "docs", "kaji")
RELEASE_IDENTITY_ROOT_FILES = ("package.json", "bun.lock")
RELEASE_IDENTITY_IGNORED_DIRECTORIES = frozenset(
    {
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".turbo",
        ".venv",
        "__pycache__",
        "coverage",
        "node_modules",
    }
)
RELEASE_IDENTITY_ARCHIVED_PLANS = Path("docs/superpowers/plans")
BETA8_IDENTITY_BYTES = re.compile(rb"(?:kaji-v)?0\.2\.0-beta\.8")
BETA8_IDENTITY_TEXT = re.compile(r"(?:kaji-v)?0\.2\.0-beta\.8")
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
            "testFile": "kaji/packages/ts/tests/github-registry.test.ts",
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


def _raw_beta8_identity_files(repo_root: Path) -> dict[Path, bytes]:
    identity_paths = {repo_root / relative for relative in RELEASE_IDENTITY_ROOT_FILES}

    for relative_root in RELEASE_IDENTITY_ACTIVE_ROOTS:
        active_root = repo_root / relative_root
        assert active_root.is_dir(), active_root
        for path in active_root.rglob("*"):
            relative = path.relative_to(repo_root)
            if (
                not path.is_file()
                or RELEASE_IDENTITY_IGNORED_DIRECTORIES.intersection(
                    relative.parent.parts
                )
                or relative.is_relative_to(RELEASE_IDENTITY_ARCHIVED_PLANS)
            ):
                continue
            identity_paths.add(path)

    matches: dict[Path, bytes] = {}
    for path in sorted(identity_paths):
        assert path.is_file(), path
        source = path.read_bytes()
        if BETA8_IDENTITY_BYTES.search(source) is not None:
            matches[path.relative_to(repo_root)] = source
    return matches


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

    assert rehearsal.count("timeout-minutes:") == 7
    assert publish.count("timeout-minutes:") == 13
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
        (
            '"ruff",\n'
            '                "format",\n'
            '                "--check",\n'
            '                "packages/py/src",\n'
            '                "packages/py/tests",'
        ),
        '"pip-audit",',
        '"--require-hashes",',
        '"openai",',
        '"anthropic",',
        '"packages/py/build-requirements.txt",',
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
    assert '["bun", "audit", "--production"]' not in script
    package_smoke = _read("kaji/packages/ts/scripts/smoke_package.mts")
    assert '"bun:audit",' in package_smoke
    assert '["audit", "--production"]' in package_smoke
    metadata_verifier = _read("kaji/scripts/verify_package_metadata.py")
    assert '"buildAudit": {' in metadata_verifier
    assert '"file": "kaji/packages/py/build-requirements.txt"' in metadata_verifier
    assert '"sha256": sha256(build_audit)' in metadata_verifier
    assert "verify_npm_tarball(npm_tarball, repo)" in metadata_verifier
    assert 'PYTHON_PROJECT = "kaji"' in metadata_verifier
    assert "if python_project != PYTHON_PROJECT:" in metadata_verifier

    publish_workflow = _read(".github/workflows/kaji.publish.yml")
    assert publish_workflow.count("https://pypi.org/pypi/kaji/0.2.0b1/json") == 3
    assert "https://pypi.org/pypi/kaji-sdk/0.2.0b1/json" not in publish_workflow

    npm_verifier = _read("kaji/scripts/verify_npm_package.py")
    for expected in (
        "npm tarball member set differs from checkout",
        "npm tarball file differs from checkout",
        "npm packaged contracts differ from canonical shared contracts",
        "npm package target is missing or outside dist/",
        "npm registry manifest is missing",
    ):
        assert expected in npm_verifier

    package_smoke = _read("kaji/packages/ts/scripts/smoke_package.mts")
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
        "kaji/scripts/installed-typescript-runtime/package-lock.openai.json",
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


def test_publish_tag_guard_matches_typescript_package_version() -> None:
    version = json.loads(_read("kaji/packages/ts/package.json"))["version"]
    publish = _read(".github/workflows/kaji.publish.yml")
    expected_tag = f"kaji-v{version}"

    assert f'context.ref !== "refs/tags/{expected_tag}"' in publish
    assert f'const tagName = "{expected_tag}";' in publish


def test_beta10_is_the_only_active_identity_and_beta8_is_exact_history() -> None:
    allowed_beta8_sections = {
        Path("docs/kaji/releasing.md"): (
            "- Treat `kaji-v0.2.0-beta.8`",
            "- Preserve the existing beta.2",
            1,
        ),
        Path("kaji/packages/ts/CHANGELOG.md"): (
            "## [0.2.0-beta.8] - 2026-07-27",
            "## [0.2.0-beta.7]",
            2,
        ),
        Path("kaji/packages/py/tests/test_release_task15.py"): (
            "\ndef test_beta10_is_the_only_active_identity_and_beta8_is_exact_history() -> None:\n"
            "    allowed_beta8_sections = {",
            "\ndef test_protected_release_workflows_fail_closed_and_attach_provenance()"
            " -> None:\n",
            4,
        ),
        Path("kaji/packages/py/tests/test_beta_contract.py"): (
            "\ndef test_publisher_identity_schema_accepts_only_closed_fail_safe_states()"
            " -> None:\n",
            "\ndef test_typescript_handoff_policy_receipt_names_the_executed_regression()"
            " -> None:\n",
            1,
        ),
        Path("kaji/packages/ts/tests/release-security.test.ts"): (
            '  it("binds the current TypeScript candidate to beta.11 and preserves prior incident history"',
            '  it("smokes compatibility matrices only from verified producer artifacts"',
            5,
        ),
    }
    beta8_identity_files = _raw_beta8_identity_files(REPO_ROOT)
    assert set(beta8_identity_files) == set(allowed_beta8_sections)

    for relative, raw_source in beta8_identity_files.items():
        start_marker, end_marker, expected_occurrences = allowed_beta8_sections[
            relative
        ]
        source = raw_source.decode("utf-8")
        assert source.count(start_marker) == 1, relative
        assert source.count(end_marker) == 1, relative
        before, section_and_after = source.split(start_marker, 1)
        section, after = section_and_after.split(end_marker, 1)
        bounded_section = start_marker + section
        assert (
            len(BETA8_IDENTITY_TEXT.findall(bounded_section)) == expected_occurrences
        ), relative
        unbounded_source = before + end_marker + after
        assert BETA8_IDENTITY_TEXT.search(unbounded_source) is None, relative

    typescript_package = json.loads(_read("kaji/packages/ts/package.json"))
    assert typescript_package["version"] == "0.2.0-beta.11"
    assert (
        _read("kaji/packages/py/pyproject.toml").splitlines()[2]
        == 'version = "0.2.0b1"'
    )
    assert '__version__ = "0.2.0b1"' in _read("kaji/packages/py/src/__init__.py")
    onboarding_contract_name = "typescript-onboarding-evidence-v1.schema.json"
    legacy_contract_names = {
        "tthw-evidence-v1.schema.json",
        "tthw-participant.template.json",
    }
    release_contract_names = {
        "github-proof-v1.schema.json",
        "gmail-proof-v1.schema.json",
        "kaji-ts-consumer-handoff-v1.schema.json",
        "publisher-identity-receipt-v1.schema.json",
        onboarding_contract_name,
    }
    canonical_release_contract = (
        REPO_ROOT / "kaji/contracts/release" / onboarding_contract_name
    ).read_bytes()
    for contract_directory in (
        REPO_ROOT / "kaji/contracts/release",
        REPO_ROOT / "kaji/packages/py/src/contracts/release",
        REPO_ROOT / "kaji/packages/ts/contracts/release",
    ):
        assert {path.name for path in contract_directory.iterdir()} == (
            release_contract_names
        )
        assert (
            contract_directory / onboarding_contract_name
        ).read_bytes() == canonical_release_contract
        for legacy_contract_name in legacy_contract_names:
            assert not (contract_directory / legacy_contract_name).exists()

    typescript_dist = REPO_ROOT / "kaji/packages/ts/dist"
    if typescript_dist.exists():
        exported_identity_paths = {
            typescript_package["main"],
            typescript_package["module"],
            typescript_package["types"],
            typescript_package["exports"]["."]["require"]["types"],
        }
        assert len(exported_identity_paths) == 4
        for exported in exported_identity_paths:
            output = REPO_ROOT / "kaji/packages/ts" / exported
            assert output.is_file(), output
            version = re.search(
                r'(?:var|declare const) VERSION = "([^"]+)"',
                output.read_text(),
            )
            assert version is not None, output
            assert version[1] == "0.2.0-beta.11", output

    python_build = REPO_ROOT / "kaji/build"
    if python_build.exists():
        generated_init = python_build / "lib/kaji/__init__.py"
        generated_contract_directory = python_build / "lib/kaji/contracts/release"
        generated_contract = generated_contract_directory / onboarding_contract_name
        assert generated_init.is_file()
        assert '__version__ = "0.2.0b1"' in generated_init.read_text()
        assert {
            path.name for path in generated_contract_directory.iterdir()
        } == release_contract_names
        assert generated_contract.is_file()
        assert generated_contract.read_bytes() == canonical_release_contract
        for legacy_contract_name in legacy_contract_names:
            assert not (generated_contract_directory / legacy_contract_name).exists()

    python_dist = REPO_ROOT / "kaji/dist"
    if python_dist.exists():
        wheel_name = "kaji-0.2.0b1-py3-none-any.whl"
        sdist_name = "kaji-0.2.0b1.tar.gz"
        npm_name = "irogane-kaji-0.2.0-beta.11.tgz"
        assert {path.name for path in python_dist.glob("*.whl")} <= {wheel_name}
        assert {path.name for path in python_dist.glob("*.tar.gz")} <= {sdist_name}
        assert {path.name for path in python_dist.glob("*.tgz")} <= {npm_name}

        wheel = python_dist / wheel_name
        if wheel.exists():
            with zipfile.ZipFile(wheel) as archive:
                release_prefix = "kaji/contracts/release/"
                archive_names = set(archive.namelist())
                assert {
                    name.removeprefix(release_prefix)
                    for name in archive_names
                    if name.startswith(release_prefix)
                } == release_contract_names
                assert (
                    archive.read(release_prefix + onboarding_contract_name)
                    == canonical_release_contract
                )
                assert (
                    not {
                        release_prefix + legacy_contract_name
                        for legacy_contract_name in legacy_contract_names
                    }
                    & archive_names
                )
                assert b"Version: 0.2.0b1" in archive.read(
                    "kaji-0.2.0b1.dist-info/METADATA"
                )

        sdist = python_dist / sdist_name
        if sdist.exists():
            with tarfile.open(sdist, "r:gz") as archive:
                release_prefix = "kaji-0.2.0b1/src/contracts/release/"
                archive_names = set(archive.getnames())
                assert {
                    name.removeprefix(release_prefix)
                    for name in archive_names
                    if name.startswith(release_prefix) and name != release_prefix
                } == release_contract_names
                contract = archive.extractfile(
                    release_prefix + onboarding_contract_name
                )
                metadata = archive.extractfile("kaji-0.2.0b1/PKG-INFO")
                assert contract is not None
                assert contract.read() == canonical_release_contract
                assert (
                    not {
                        release_prefix + legacy_contract_name
                        for legacy_contract_name in legacy_contract_names
                    }
                    & archive_names
                )
                assert metadata is not None
                assert b"Version: 0.2.0b1" in metadata.read()

        npm = python_dist / npm_name
        if npm.exists():
            with tarfile.open(npm, "r:gz") as archive:
                release_prefix = "package/contracts/release/"
                archive_names = set(archive.getnames())
                assert {
                    name.removeprefix(release_prefix)
                    for name in archive_names
                    if name.startswith(release_prefix) and name != release_prefix
                } == release_contract_names
                contract = archive.extractfile(
                    release_prefix + onboarding_contract_name
                )
                assert contract is not None
                assert contract.read() == canonical_release_contract
                assert (
                    not {
                        release_prefix + legacy_contract_name
                        for legacy_contract_name in legacy_contract_names
                    }
                    & archive_names
                )

    for workflow_name in ("kaji.rehearsal.yml", "kaji.publish.yml"):
        workflow = _read(f".github/workflows/{workflow_name}")
        assert "0.2.0-beta.11" in workflow
        assert "0.2.0-beta.8" not in workflow

    historical = " ".join(
        _read("docs/kaji/releasing.md")
        .split("- Treat `kaji-v0.2.0-beta.8`", 1)[1]
        .split("- Preserve the existing beta.2", 1)[0]
        .split()
    )
    for evidence in (
        "as a burned, immutable TTHW-input attempt",
        "Protected run `30296132900`",
        "`4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e`",
        "`KAJI_TTHW_EVIDENCE_JSON` was empty",
        "Provider proof, registry and publisher preflight, and npm publication were skipped",
        "npm and PyPI remained absent",
        "Never move, retry, approve, or add evidence",
        "recovery requires the new beta.9 attempt",
        "rehearsal `30291287818` is terminal cancelled",
        "cannot be reused as beta.9 evidence",
    ):
        assert evidence in historical


def test_beta8_identity_inventory_detects_a_hostile_mdx_temporary_copy(
    tmp_path: Path,
) -> None:
    for relative_root in RELEASE_IDENTITY_ACTIVE_ROOTS:
        (tmp_path / relative_root).mkdir()
    for relative in RELEASE_IDENTITY_ROOT_FILES:
        (tmp_path / relative).write_bytes((REPO_ROOT / relative).read_bytes())

    hostile_relative = Path("apps/docs/content/install.mdx")
    hostile_copy = tmp_path / hostile_relative
    hostile_copy.parent.mkdir(parents=True)
    hostile_copy.write_bytes(
        (REPO_ROOT / hostile_relative).read_bytes()
        + b"\nHostile stale identity: "
        + b"0.2.0-beta."
        + b"8\n"
    )

    matches = _raw_beta8_identity_files(tmp_path)
    assert matches == {hostile_relative: hostile_copy.read_bytes()}


def test_protected_release_workflows_fail_closed_and_attach_provenance() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")

    assert "environment: kaji-release" in rehearsal
    assert "OPENAI_API_KEY" in rehearsal
    assert "ANTHROPIC_API_KEY" not in rehearsal
    assert "live_provider_proof.py" in rehearsal
    assert rehearsal.count("environment: kaji-onboarding") == 1
    assert rehearsal.count("environment: kaji-release\n") == 1
    assert "environment: kaji-publish" not in rehearsal
    assert publish.count("environment: kaji-onboarding") == 1
    assert publish.count("environment: kaji-release\n") == 1
    assert publish.count("environment: kaji-publish") == 1
    assert (
        "needs: [offline-release, performance, typescript-onboarding-evidence, "
        "python-compat, node-compat]" in rehearsal
    )
    assert "needs.offline-release.result == 'success'" in rehearsal
    assert "needs.python-compat.result == 'success'" in rehearsal
    assert "needs.node-compat.result == 'success'" in rehearsal
    assert "needs.performance.result == 'success'" in rehearsal
    assert "group: kaji-rehearsal-0.2.0-beta.11" in rehearsal
    assert "0.2.0-beta.5" not in rehearsal
    assert "0.2.0-beta.5" not in publish
    assert "0.2.0-beta.2" not in rehearsal
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
        "environment: kaji-release",
        "environment: kaji-publish",
        "npm publish .artifacts/kaji-release/irogane-kaji-0.2.0-beta.11.tgz --provenance --access public --tag beta --registry=https://registry.npmjs.org/",
        "--provenance",
        "actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be",
        "SHA256SUMS",
        "sbom",
        "live_provider_proof.py",
        "group: kaji-publish-${{ github.ref_name }}",
        "KAJI_RELEASE_SIGNER_EMAIL",
        "context.payload.repository?.private !== false",
        "npm provenance requires the source repository to remain public",
        "github.rest.repos.compareCommits",
        "comparison.data.merge_base_commit.sha !== releaseCommit",
        'verification.reason !== "valid"',
        "tag.data.tag !== tagName",
        'scalarOutput("tag-object", tagObject',
        'scalarOutput("commit", releaseCommit',
        "Revalidate downloaded filenames, sizes, hashes, and commit",
        "offline-gate-summary.json",
        "offline-gates.log",
        "steps.provenance.outputs.bundle-path",
        "steps.provenance.outputs.attestation-id",
        "steps.provenance.outputs.attestation-url",
        "provenance.bundle.jsonl",
        "provenance.json",
        "provider-evidence.json",
        "kaji-typescript-onboarding-evidence",
        "validate_typescript_onboarding_evidence.py",
        "typescript-onboarding/typescript-onboarding-evidence.json",
        "npm@11.16.0",
        "--downloads-dir .artifacts/kaji-publication-status/downloaded",
        '--repository "$GITHUB_REPOSITORY"',
        "verify_published_packages.py state",
        "steps.classify.outputs.publication-state || steps.initial-status.outputs.publication-state",
        "needs.publication-status.outputs.state == 'npm_byte_verified'",
        "installation recommendations remain withheld",
        "github.run_attempt == 1",
        "NPM_TOKEN is required",
        "npm whoami --registry=https://registry.npmjs.org/",
        "npm identity does not match KAJI_NPM_PUBLISHER",
        "KAJI_NPM_PUBLISHER must name the approved npm identity",
        "verify_release_artifacts.py",
        "verify_npm_package.py",
        "verify_archives.py",
        "Rebuild and verify exact package contents against the clean checkout",
        "Rebuild and verify npm archive contents against the clean checkout",
        "verify_published_packages.py",
        "--attempts 45 --initial-delay 2 --max-delay 20",
        "attach_release_assets.py",
        "registry-verification.json",
        "Initialize fail-closed publication status before setup",
        "--target npm",
        "--pypi-publish-result skipped",
        '--npm-publish-result "$NPM_PUBLISH_RESULT"',
        "status_classifier_unavailable",
        "Create or update fail-closed incident prerelease status",
        "Installation recommendation: WITHHELD",
        "Retained evidence:",
        "no publish job was attempted",
        "needs.publication-status.outputs.incident == 'true'",
    ):
        assert expected in publish
    assert "pypa/gh-action-pypi-publish" not in publish
    assert "pypi-attestations" not in publish
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
    assert (
        publication_status.count("uv run --project kaji/packages/py --no-sync python")
        == 2
    )
    assert "python3 kaji/scripts/verify_published_packages.py" not in publication_status
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
        publish.count("Revalidate downloaded filenames, sizes, hashes, and commit") == 2
    )
    assert publish.count("uses: ./.github/actions/verify-kaji-tag") == 2
    assert publish.count("environment: kaji-publish") == 1
    assert publish.count("needs: [verify-tag, supply-chain, registry-preflight]") == 1
    assert (
        "needs: [verify-tag, typescript-onboarding-evidence, supply-chain, "
        "publication-status]" in publish
    )
    assert "if-no-files-found: error" in publish
    assert "--clobber" not in publish
    for reverify, mutation, required_intermediate_steps in (
        (
            "Reverify signed tag immediately before npm publication",
            "Publish exact npm beta with provenance",
            ("Recheck exact registry absence immediately before npm publication",),
        ),
        (
            "Reverify signed tag immediately before release attachment",
            "Create or verify prerelease and attach only missing digest-matched assets",
            (),
        ),
    ):
        between = publish.split(reverify, 1)[1].split(mutation, 1)[0]
        assert between.count("uses: ./.github/actions/verify-kaji-tag") == 1
        assert between.count("      - name:") == 1 + len(required_intermediate_steps)
        for required_intermediate_step in required_intermediate_steps:
            assert required_intermediate_step in between
    assert (
        "needs: [verify-tag, offline-gates, performance, "
        "typescript-onboarding-evidence, python-compat, node-compat]" in publish
    )
    assert (
        "needs: [verify-tag, offline-gates, performance, "
        "typescript-onboarding-evidence, keyed-proof, python-compat, node-compat]"
        in publish
    )
    for dependency in (
        "verify-tag",
        "offline-gates",
        "performance",
        "typescript-onboarding-evidence",
        "python-compat",
        "node-compat",
    ):
        assert f"needs.{dependency}.result == 'success'" in publish
    assert (
        "if: ${{ always() && needs.verify-tag.result == 'success' && "
        "needs.supply-chain.result == 'success' }}" in publish
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
    assert re.search(
        r'"status":\s*\(\s*"npm_byte_verified"\s+if args\.target == "npm"'
        r'\s+else "byte_verified"',
        registry,
    )
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


def test_clean_checkout_rebuilds_use_supported_bun_cwd_syntax() -> None:
    publish = _read(".github/workflows/kaji.publish.yml")
    rebuild_steps = (
        "Rebuild and verify exact package contents against the clean checkout",
        "Rebuild and verify npm archive contents against the clean checkout",
    )

    for name in rebuild_steps:
        step = publish.split(f"      - name: {name}", 1)[1].split("      - ", 1)[0]
        assert "bun run --cwd kaji/packages/ts build" in step
    assert "bun --cwd kaji/packages/ts run build" not in publish


@pytest.mark.parametrize(
    ("workflow_name", "expected_commit"),
    [
        (".github/workflows/kaji.rehearsal.yml", "${{ inputs.expected-commit }}"),
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
            "[offline-release, node-compat]",
            "${{ inputs.expected-commit }}",
        ),
        (
            ".github/workflows/kaji.publish.yml",
            "[verify-tag, offline-gates, node-compat]",
            "${{ needs.verify-tag.outputs.commit }}",
        ),
    ],
)
def test_typescript_onboarding_gate_authenticates_archives_before_protected_use(
    workflow_name: str, upstream: str, expected_commit: str
) -> None:
    workflow = _read(workflow_name)
    calibration = workflow.split("  typescript-onboarding-archive-calibration:", 1)[
        1
    ].split("  typescript-onboarding-evidence:", 1)[0]
    onboarding = workflow.split("  typescript-onboarding-evidence:", 1)[1].split(
        "  keyed-proof:", 1
    )[0]

    assert f"needs: {upstream}" in calibration
    assert "runs-on: ubuntu-24.04" in calibration
    assert "environment:" not in calibration.split("    steps:", 1)[0]
    assert f"EXPECTED_COMMIT: {expected_commit}" in calibration
    assert "Resolve exact current-run onboarding archives" in calibration
    assert (
        calibration.count("kaji/scripts/validate_typescript_onboarding_evidence.py")
        == 1
    )
    assert "Independently validate and recompute calibration aggregate" in calibration
    assert "name: kaji-typescript-onboarding-archive-calibration" in calibration
    assert "name: kaji-typescript-onboarding-archive-calibration-initial" in calibration

    import_fragment = (
        'scripts_dir = Path("kaji/scripts").resolve(strict=True)\n'
        "          sys.path.insert(0, str(scripts_dir))\n"
        "          from validate_typescript_onboarding_evidence import ("
    )
    assert import_fragment in calibration
    assert import_fragment in onboarding

    assert "environment: kaji-onboarding" in onboarding
    assert "runs-on: ubuntu-24.04" in onboarding
    assert "needs.typescript-onboarding-archive-calibration.result == 'success'" in (
        onboarding
    )
    assert f"EXPECTED_COMMIT: {expected_commit}" in onboarding
    assert "Resolve exact current-run onboarding archives independently" in onboarding
    assert (
        "Authenticate archives and compose protected onboarding evidence" in onboarding
    )
    assert "Independently validate and recompute protected onboarding evidence" in (
        onboarding
    )
    assert "Normalize terminal onboarding evidence" in onboarding
    assert "name: kaji-typescript-onboarding-evidence-initial" in onboarding
    assert "name: kaji-typescript-onboarding-evidence" in onboarding
    for binding in (
        "--producer-archive",
        "--producer-artifact-id",
        "--producer-artifact-digest",
        "--node22-archive",
        "--node22-source-artifact-id",
        "--node22-source-artifact-digest",
        "--node24-archive",
        "--node24-source-artifact-id",
        "--node24-source-artifact-digest",
        "--expected-run-id",
        "--expected-workflow-run",
        "--expected-workflow-ref",
        "--expected-workflow-sha",
    ):
        assert binding in calibration
        assert binding in onboarding
    assert "KAJI_TTHW_EVIDENCE_JSON" not in workflow
    assert "validate_tthw_evidence.py" not in workflow


def test_typescript_onboarding_inline_validator_imports_from_repo_root() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                'scripts_dir = Path("kaji/scripts").resolve(strict=True); '
                "sys.path.insert(0, str(scripts_dir)); "
                "from validate_typescript_onboarding_evidence import "
                "load_authenticated_archive, recompute_and_compare, validate_document"
            ),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_release_runbook_orders_archive_onboarding_tag_and_publisher_approvals() -> (
    None
):
    runbook_source = _read("docs/kaji/releasing.md")
    runbook = " ".join(runbook_source.split())
    ordered_steps = (
        "audit all three protected environments",
        "Dispatch the rehearsal at ref `main`; never dispatch a raw SHA",
        "Resolve exactly one unexpired `kaji-artifacts`",
        "Run the approved helper first without `--approve`",
        "Only after that command succeeds, rerun the identical command with "
        "`--approve` appended",
        "Wait for terminal-green candidate evidence",
        "Stop here until the operator explicitly confirms a fresh `NPM_TOKEN`",
        'git tag -s --cleanup=verbatim -F "$AUTHORIZATION_FILE"',
        'git verify-tag "$TAG"',
        'git push origin "refs/tags/$TAG"',
        "Run the same helper without `--approve`, now with `--mode publish`",
        "Approve the sole `kaji-publish` deployment",
    )
    missing_steps = [step for step in ordered_steps if step not in runbook]
    assert not missing_steps, f"missing release runbook steps: {missing_steps}"
    positions = [runbook.index(step) for step in ordered_steps]

    assert positions == sorted(positions)
    protected_release = runbook_source.split("## Protected release", 1)[1].split(
        "## Partial or ambiguous publication", 1
    )[0]
    assert "KAJI_TTHW_EVIDENCE_JSON" not in protected_release
    assert "approve_tthw_gate.py" not in protected_release
    assert "explicitly confirm that a fresh `NPM_TOKEN`" in runbook
    assert "Do not inspect, copy, or test the secret locally" in runbook
    assert "Do not run a local credential preflight" in runbook
    assert "Do not approve onboarding manually in the Actions UI" in runbook
    assert "A failure after the approval POST is ambiguous" in runbook
    assert "recursively lexicographically sorted keys" in runbook
    assert "exactly one terminal LF" in runbook
    assert "Never use a broad free-form `-m` tag message" in runbook

    helper_prefix = (
        "uv run --project kaji/packages/py --no-sync python \\\n     "
        "kaji/scripts/approve_typescript_onboarding_gate.py gate"
    )
    assert runbook_source.count(helper_prefix) == 2
    for mode, run_id, root in (
        ("rehearsal", "$REHEARSAL_RUN_ID", "$EVIDENCE_ROOT"),
        ("publish", "$PUBLISH_RUN_ID", "$PUBLISH_EVIDENCE_ROOT"),
    ):
        helper = runbook_source.split(f"{helper_prefix} \\\n     --mode {mode}", 1)[
            1
        ].split("```", 1)[0]
        for argument in (
            f'--run-id "{run_id}"',
            '--expected-commit "$REVIEWED_COMMIT"',
            f'--producer-archive "{root}/producer.zip"',
            "--producer-artifact-id",
            "--producer-artifact-digest",
            f'--node22-archive "{root}/node22.zip"',
            "--node22-artifact-id",
            "--node22-artifact-digest",
            f'--node24-archive "{root}/node24.zip"',
            "--node24-artifact-id",
            "--node24-artifact-digest",
        ):
            assert argument in helper


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
    assert "secrets.ANTHROPIC_API_KEY" not in keyed
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in proof_step
    assert "ANTHROPIC_API_KEY" not in proof_step
    assert keyed.count('provider: "openai"') == 2
    assert 'provider: "anthropic"' not in keyed
    assert ".proofs | length == 2" in keyed
    normalized_keyed = re.sub(r"\s+", " ", keyed)
    assert (
        'map(.sdk + "/" + .provider) | sort == ["python/openai", "typescript/openai"]'
    ) in normalized_keyed
    assert "uv run --project kaji/packages/py --no-sync python" in proof_step
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
    assert "timeout --signal=TERM --kill-after=10s 20m" in status_job
    assert "timeout-minutes: 45" in status_job
    retry = re.search(
        r"--attempts (\d+) --initial-delay (\d+) --max-delay (\d+)", status_job
    )
    assert retry is not None
    attempts, initial_delay, max_delay = map(int, retry.groups())
    backoff_seconds = sum(
        min(initial_delay * 2**retry_number, max_delay)
        for retry_number in range(attempts - 1)
    )
    assert backoff_seconds >= 780
    assert backoff_seconds + 300 <= 1200
    assert backoff_seconds < 900
    assert status_job.index("timeout --signal=TERM --kill-after=10s 20m") < (
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
    assert (
        'EXPECTED_BUILD_AUDIT = "kaji/packages/py/build-requirements.txt"'
        in artifact_verifier
    )
    assert 'set(build_audit) != {"file", "sha256"}' in artifact_verifier

    tag_verifier = _read(".github/actions/verify-kaji-tag/action.yml")
    assert "using: composite" in tag_verifier
    assert '"X-GitHub-Api-Version: 2026-03-10"' in tag_verifier
    assert "verification.verified !== true" in tag_verifier
    assert 'verification.reason !== "valid"' in tag_verifier
    assert "tag.tag !== expectedTag" in tag_verifier
    assert "tag.tagger?.email !== expectedTaggerEmail" in tag_verifier
    assert "EXPECTED_TAGGER_EMAIL" in tag_verifier
    assert 'tag.object?.type !== "commit"' in tag_verifier
    assert "tag.object?.sha !== expectedCommit" in tag_verifier


def test_npm_propagation_budget_is_bounded_within_job_timeout() -> None:
    publish = _read(".github/workflows/kaji.publish.yml")
    status_job = publish.split("  publication-status:", 1)[1].split(
        "  publication-incident:", 1
    )[0]
    retry = re.search(
        r"--attempts (\d+) --initial-delay (\d+) --max-delay (\d+)", status_job
    )
    timeout = re.search(r"timeout --signal=TERM --kill-after=10s (\d+)m", status_job)
    assert retry is not None
    assert timeout is not None
    attempts, initial_delay, max_delay = map(int, retry.groups())
    backoff_seconds = sum(
        min(initial_delay * 2**retry_number, max_delay)
        for retry_number in range(attempts - 1)
    )
    assert (attempts, initial_delay, max_delay) == (45, 2, 20)
    assert backoff_seconds == 830
    assert timeout.group(1) == "20"
    assert backoff_seconds < int(timeout.group(1)) * 60
    assert "timeout-minutes: 45" in status_job


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


def test_npm_target_has_a_distinct_byte_verified_terminal() -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="unpublished",
        pypi="absent",
        npm="present",
        registry_verification="npm_byte_verified",
        pypi_publish_result="skipped",
        npm_publish_result="success",
        target="npm",
    )

    assert decision.state == "npm_byte_verified"
    assert decision.release_ready is True
    assert decision.install_recommendation is True
    assert decision.incident_code is None


def test_dual_target_retains_npm_only_as_a_partial_publication_incident() -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="unpublished",
        pypi="absent",
        npm="present",
        registry_verification="not_run",
        pypi_publish_result="skipped",
        npm_publish_result="success",
        target="dual",
    )

    assert decision.state == "npm_only"
    assert decision.incident_code == "partial_publication"
    assert decision.release_ready is False


def test_npm_target_keeps_a_clean_preflight_stop_unpublished() -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="unpublished",
        pypi="absent",
        npm="absent",
        registry_verification="not_run",
        pypi_publish_result="skipped",
        npm_publish_result="skipped",
        target="npm",
    )

    assert decision == verifier.PublicationDecision("unpublished", False, False)


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
            "unpublished",
            "present",
            "present",
            "npm_byte_verified",
            "skipped",
            "success",
            "publication_target_mismatch",
        ),
        (
            "unpublished",
            "unknown",
            "present",
            "npm_byte_verified",
            "skipped",
            "success",
            "verification_state_mismatch",
        ),
        (
            "unpublished",
            "absent",
            "present",
            "npm_byte_verified",
            "success",
            "success",
            "publish_target_mismatch",
        ),
        (
            "unpublished",
            "absent",
            "absent",
            "npm_byte_verified",
            "skipped",
            "success",
            "verification_state_mismatch",
        ),
        (
            "unpublished",
            "absent",
            "unknown",
            "not_run",
            "skipped",
            "unknown",
            "registry_state_unknown",
        ),
        (
            "unpublished",
            "absent",
            "present",
            "not_run",
            "skipped",
            "success",
            "verification_incomplete",
        ),
        (
            "unpublished",
            "absent",
            "present",
            "failed",
            "skipped",
            "success",
            "registry_verification_failed",
        ),
        (
            "unpublished",
            "absent",
            "present",
            "byte_verified",
            "skipped",
            "success",
            "verification_state_mismatch",
        ),
        (
            "unpublished",
            "absent",
            "present",
            "npm_byte_verified",
            "skipped",
            "skipped",
            "publish_target_mismatch",
        ),
        (
            "npm_byte_verified",
            "absent",
            "absent",
            "not_run",
            "skipped",
            "skipped",
            "state_regression",
        ),
    ],
)
def test_npm_target_fails_closed_on_unknown_mismatch_or_regression(
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
        target="npm",
    )

    assert decision.incident_code == incident
    assert decision.release_ready is False
    assert decision.install_recommendation is False


def test_npm_target_retains_its_verified_terminal_only_with_exact_evidence() -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="npm_byte_verified",
        pypi="absent",
        npm="present",
        registry_verification="npm_byte_verified",
        pypi_publish_result="skipped",
        npm_publish_result="success",
        target="npm",
    )

    assert decision == verifier.PublicationDecision("npm_byte_verified", True, True)


@pytest.mark.parametrize(
    ("verification", "incident"),
    [
        ("not_run", "verification_incomplete"),
        ("failed", "registry_verification_failed"),
    ],
)
def test_npm_target_withholds_but_retains_its_previous_terminal(
    verification: str, incident: str
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    decision = verifier.reduce_publication_state(
        previous_state="npm_byte_verified",
        pypi="absent",
        npm="present",
        registry_verification=verification,
        pypi_publish_result="skipped",
        npm_publish_result="success",
        target="npm",
    )

    assert decision.state == "npm_byte_verified"
    assert decision.incident_code == incident
    assert decision.release_ready is False
    assert decision.install_recommendation is False


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
    assert "--target npm" in status_job
    assert "--pypi-publish-result skipped" in status_job
    assert 'publishJobs: {pypi: "skipped", npm: $npmPublish}' in status_job
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


def _task7_publisher_receipt(
    path: Path,
    *,
    conclusion: str = "passed",
    failure_code: str | None = None,
    expected_publisher: str | None = "enkyuan",
    actual_publisher: str | None = "enkyuan",
    exit_code: int | None = 0,
    commit: str = "a" * 40,
    tag: str = "kaji-v0.2.0-beta.11",
    workflow_run: str = "https://github.com/enkyuan/alloy/actions/runs/123",
    workflow_run_attempt: int = 1,
    workflow_path: str = ".github/workflows/kaji.publish.yml",
    workflow_sha: str = "a" * 40,
) -> dict[str, object]:
    receipt = {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "tag": tag,
        "workflowRun": workflow_run,
        "workflowRunAttempt": workflow_run_attempt,
        "workflowPath": workflow_path,
        "workflowSha": workflow_sha,
        "expectedPublisher": expected_publisher,
        "actualPublisher": actual_publisher,
        "conclusion": conclusion,
        "exitCode": exit_code,
        "failureCode": failure_code,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


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
            "skipped",
            "--commit",
            "a" * 40,
            "--tag",
            "kaji-v0.2.0-beta.11",
            "--workflow-run",
            "https://github.com/enkyuan/alloy/actions/runs/123",
            "--workflow-run-attempt",
            "1",
            "--workflow-path",
            ".github/workflows/kaji.publish.yml",
            "--workflow-sha",
            "a" * 40,
            "--publisher-no-receipt-reason",
            "publish_job_not_started",
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
    assert retained["publishJobs"] == {"pypi": "success", "npm": "skipped"}
    assert retained["publisherIdentity"] == {
        "conclusion": "not_run",
        "reason": "publish_job_not_started",
        "artifact": None,
        "receiptSha256": None,
        "identity": None,
    }
    assert "WITHHELD" in markdown.read_text()
    assert "https://github.com/enkyuan/alloy/actions/runs/123" in markdown.read_text()
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
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.11"},
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
                "--tag",
                "kaji-v0.2.0-beta.11",
                "--workflow-path",
                ".github/workflows/kaji.publish.yml",
                "--workflow-sha",
                "a" * 40,
                "--workflow-run-id",
                "123",
                "--workflow-run-attempt",
                "1",
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
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.11"},
                "artifacts": [],
            }
        )
    )
    output = tmp_path / "registry-verification.json"
    attempts = 0
    sleep_delays: list[float] = []

    def verify_pypi(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts < 5:
            raise verifier.VerificationUnavailable("attestations not propagated")
        return {"files": []}

    monkeypatch.setattr(verifier, "verify_pypi", verify_pypi)
    monkeypatch.setattr(
        verifier, "verify_npm", lambda *_args, **_kwargs: {"byteVerified": True}
    )
    monkeypatch.setattr(verifier.time, "sleep", sleep_delays.append)

    verifier.verification_main(
        [
            "--artifacts-dir",
            str(artifacts),
            "--output",
            str(output),
            "--repository",
            "alloy-org/alloy",
            "--tag",
            "kaji-v0.2.0-beta.11",
            "--workflow-path",
            ".github/workflows/kaji.publish.yml",
            "--workflow-sha",
            "a" * 40,
            "--workflow-run-id",
            "123",
            "--workflow-run-attempt",
            "1",
            "--attempts",
            "5",
            "--initial-delay",
            "2",
            "--max-delay",
            "5",
        ]
    )

    retained = json.loads(output.read_text())
    assert attempts == 5
    assert sleep_delays == [2.0, 4.0, 5.0, 5.0]
    assert retained["status"] == "byte_verified"
    assert retained["attempt"] == 5


def test_npm_target_verifier_skips_pypi_and_records_the_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text(
        json.dumps(
            {
                "commit": "a" * 40,
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.11"},
                "artifacts": [
                    {
                        "file": "kaji-0.2.0b1-py3-none-any.whl",
                        "package": "python",
                        "sha256": "0" * 64,
                        "size": 1,
                    },
                    {
                        "file": "irogane-kaji-0.2.0-beta.11.tgz",
                        "package": "typescript",
                        "sha256": "1" * 64,
                        "size": 1,
                    },
                ],
            }
        )
    )
    output = tmp_path / "registry-verification.json"
    monkeypatch.setattr(
        verifier,
        "verify_pypi",
        lambda *_args, **_kwargs: pytest.fail("npm target called verify_pypi"),
    )
    npm_calls = 0

    def verify_npm(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal npm_calls
        npm_calls += 1
        return {"byteVerified": True}

    monkeypatch.setattr(verifier, "verify_npm", verify_npm)

    verifier.verification_main(
        [
            "--artifacts-dir",
            str(artifacts),
            "--output",
            str(output),
            "--repository",
            "alloy-org/alloy",
            "--tag",
            "kaji-v0.2.0-beta.11",
            "--workflow-path",
            ".github/workflows/kaji.publish.yml",
            "--workflow-sha",
            "a" * 40,
            "--workflow-run-id",
            "123",
            "--workflow-run-attempt",
            "1",
            "--target",
            "npm",
            "--attempts",
            "1",
        ]
    )

    retained = json.loads(output.read_text())
    assert npm_calls == 1
    assert retained["target"] == "npm"
    assert retained["status"] == "npm_byte_verified"
    assert retained["pypi"] == {"status": "not_targeted"}
    assert retained["npm"] == {"byteVerified": True}
    assert retained["packages"] == {
        "python": "0.2.0b1",
        "typescript": "0.2.0-beta.11",
    }


def test_npm_target_state_cli_persists_target_and_terminal(
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    output = tmp_path / "publication-status.json"
    markdown = tmp_path / "publication-status.md"
    receipt_path = tmp_path / "publisher-identity-receipt.json"
    receipt = _task7_publisher_receipt(receipt_path)

    verifier.state_main(
        [
            "--target",
            "npm",
            "--previous-state",
            "unpublished",
            "--pypi",
            "absent",
            "--npm",
            "present",
            "--registry-verification",
            "npm_byte_verified",
            "--pypi-publish-result",
            "skipped",
            "--npm-publish-result",
            "success",
            "--commit",
            "a" * 40,
            "--tag",
            "kaji-v0.2.0-beta.11",
            "--workflow-run",
            "https://github.com/enkyuan/alloy/actions/runs/123",
            "--workflow-run-attempt",
            "1",
            "--workflow-path",
            ".github/workflows/kaji.publish.yml",
            "--workflow-sha",
            "a" * 40,
            "--expected-publisher",
            "enkyuan",
            "--publisher-receipt",
            str(receipt_path),
            "--publisher-artifact-name",
            "kaji-publisher-identity-123-1",
            "--publisher-artifact-id",
            "456",
            "--publisher-artifact-digest",
            "sha256:" + "b" * 64,
            "--output",
            str(output),
            "--markdown",
            str(markdown),
        ]
    )

    retained = json.loads(output.read_text())
    assert retained["target"] == "npm"
    assert retained["state"] == "npm_byte_verified"
    assert retained["releaseReady"] is True
    assert retained["installRecommendation"] is True
    assert retained["tag"] == "kaji-v0.2.0-beta.11"
    assert retained["workflowRunAttempt"] == 1
    assert retained["workflowPath"] == ".github/workflows/kaji.publish.yml"
    assert retained["workflowSha"] == "a" * 40
    assert retained["expectedPublisher"] == "enkyuan"
    assert retained["publisherIdentity"] == {
        "conclusion": "passed",
        "reason": None,
        "artifact": {
            "name": "kaji-publisher-identity-123-1",
            "id": 456,
            "digest": "sha256:" + "b" * 64,
        },
        "receiptSha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "identity": receipt,
    }
    assert "- Target: `npm`" in markdown.read_text()


def _task7_state_args(
    tmp_path: Path,
    *,
    receipt: Path | None = None,
    no_receipt_reason: str | None = None,
    expected_publisher: str | None = "enkyuan",
    npm_publish_result: str = "success",
) -> list[str]:
    command = [
        "--target",
        "npm",
        "--previous-state",
        "unpublished",
        "--pypi",
        "absent",
        "--npm",
        "present",
        "--registry-verification",
        "npm_byte_verified",
        "--pypi-publish-result",
        "skipped",
        "--npm-publish-result",
        npm_publish_result,
        "--commit",
        "a" * 40,
        "--tag",
        "kaji-v0.2.0-beta.11",
        "--workflow-run",
        "https://github.com/enkyuan/alloy/actions/runs/123",
        "--workflow-run-attempt",
        "1",
        "--workflow-path",
        ".github/workflows/kaji.publish.yml",
        "--workflow-sha",
        "a" * 40,
        "--output",
        str(tmp_path / "publication-status.json"),
        "--markdown",
        str(tmp_path / "publication-status.md"),
    ]
    if expected_publisher is not None:
        command.extend(["--expected-publisher", expected_publisher])
    if receipt is not None:
        command.extend(
            [
                "--publisher-receipt",
                str(receipt),
                "--publisher-artifact-name",
                "kaji-publisher-identity-123-1",
                "--publisher-artifact-id",
                "456",
                "--publisher-artifact-digest",
                "sha256:" + "b" * 64,
            ]
        )
    if no_receipt_reason is not None:
        command.extend(["--publisher-no-receipt-reason", no_receipt_reason])
    return command


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit", "b" * 40),
        ("tag", "kaji-v0.2.0-beta." + "8"),
        ("workflowRun", "https://github.com/enkyuan/alloy/actions/runs/999"),
        ("workflowRunAttempt", 2),
        ("workflowPath", ".github/workflows/attacker.yml"),
        ("workflowSha", "b" * 40),
        ("expectedPublisher", "attacker"),
        ("actualPublisher", "attacker"),
    ],
)
def test_publisher_receipt_rejects_schema_or_semantic_tuple_drift(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    path = tmp_path / "publisher.json"
    receipt = _task7_publisher_receipt(path)
    receipt[field] = value
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    with pytest.raises(verifier.PublisherIdentityError):
        verifier.validate_publisher_identity_receipt(
            path,
            expected_commit="a" * 40,
            expected_tag="kaji-v0.2.0-beta.11",
            expected_workflow_run="https://github.com/enkyuan/alloy/actions/runs/123",
            expected_workflow_run_attempt=1,
            expected_workflow_path=".github/workflows/kaji.publish.yml",
            expected_workflow_sha="a" * 40,
            expected_publisher="enkyuan",
        )


def test_publisher_mismatch_receipt_requires_distinct_identities(
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    path = tmp_path / "publisher.json"
    _task7_publisher_receipt(
        path,
        conclusion="failed",
        failure_code="publisher_mismatch",
        expected_publisher="enkyuan",
        actual_publisher="enkyuan",
        exit_code=1,
    )

    with pytest.raises(verifier.PublisherIdentityError):
        verifier.validate_publisher_identity_receipt(
            path,
            expected_commit="a" * 40,
            expected_tag="kaji-v0.2.0-beta.11",
            expected_workflow_run="https://github.com/enkyuan/alloy/actions/runs/123",
            expected_workflow_run_attempt=1,
            expected_workflow_path=".github/workflows/kaji.publish.yml",
            expected_workflow_sha="a" * 40,
            expected_publisher="enkyuan",
        )


@pytest.mark.parametrize(
    "kind", ["duplicate", "noncanonical", "oversize", "symlink", "hardlink"]
)
def test_publisher_receipt_loader_rejects_hostile_raw_files(
    tmp_path: Path,
    kind: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    path = tmp_path / "publisher.json"
    receipt = _task7_publisher_receipt(path)
    if kind == "duplicate":
        encoded = path.read_text().replace(
            '"schemaVersion": "1.0.0",',
            '"schemaVersion": "1.0.0",\n  "schemaVersion": "1.0.0",',
        )
        path.write_text(encoded)
    elif kind == "noncanonical":
        path.write_text(json.dumps(receipt) + "\n")
    elif kind == "oversize":
        path.write_bytes(b" " * (64 * 1024 + 1))
    elif kind == "symlink":
        target = tmp_path / "target.json"
        path.replace(target)
        path.symlink_to(target)
    else:
        os.link(path, tmp_path / "publisher-hardlink.json")

    with pytest.raises(verifier.PublisherIdentityError):
        verifier.validate_publisher_identity_receipt(
            path,
            expected_commit="a" * 40,
            expected_tag="kaji-v0.2.0-beta.11",
            expected_workflow_run="https://github.com/enkyuan/alloy/actions/runs/123",
            expected_workflow_run_attempt=1,
            expected_workflow_path=".github/workflows/kaji.publish.yml",
            expected_workflow_sha="a" * 40,
            expected_publisher="enkyuan",
        )


def test_publisher_receipt_loader_rejects_stable_read_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    path = tmp_path / "publisher.json"
    _task7_publisher_receipt(path)
    original = verifier._file_identity
    calls = 0

    def drifting_identity(value: os.stat_result) -> tuple[int, ...]:
        nonlocal calls
        calls += 1
        identity = original(value)
        if calls >= 3:
            return (*identity[:-1], identity[-1] + 1)
        return identity

    monkeypatch.setattr(verifier, "_file_identity", drifting_identity)
    with pytest.raises(verifier.PublisherIdentityError):
        verifier.validate_publisher_identity_receipt(
            path,
            expected_commit="a" * 40,
            expected_tag="kaji-v0.2.0-beta.11",
            expected_workflow_run="https://github.com/enkyuan/alloy/actions/runs/123",
            expected_workflow_run_attempt=1,
            expected_workflow_path=".github/workflows/kaji.publish.yml",
            expected_workflow_sha="a" * 40,
            expected_publisher="enkyuan",
        )


@pytest.mark.parametrize(
    ("failure_code", "expected_publisher", "actual_publisher", "exit_code"),
    [
        ("token_missing", "enkyuan", None, 1),
        ("npm_whoami_failed", "enkyuan", None, 73),
        ("publisher_mismatch", "enkyuan", "attacker", 1),
        ("expected_publisher_missing", None, None, 1),
    ],
)
def test_failed_publisher_identity_forces_a_nonterminal_incident(
    tmp_path: Path,
    failure_code: str,
    expected_publisher: str | None,
    actual_publisher: str | None,
    exit_code: int,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    _task7_publisher_receipt(
        receipt,
        conclusion="failed",
        failure_code=failure_code,
        expected_publisher=expected_publisher,
        actual_publisher=actual_publisher,
        exit_code=exit_code,
    )
    verifier.state_main(
        _task7_state_args(
            tmp_path,
            receipt=receipt,
            expected_publisher=expected_publisher,
        )
    )

    status = json.loads((tmp_path / "publication-status.json").read_text())
    assert status["state"] == "npm_only"
    assert status["releaseReady"] is False
    assert status["incident"]["code"] == "publisher_identity_not_verified"
    assert status["publisherIdentity"]["conclusion"] == "failed"
    assert status["publisherIdentity"]["reason"] == "identity_check_failed"
    assert status["publisherIdentity"]["identity"]["failureCode"] == failure_code
    assert re.fullmatch(r"[0-9a-f]{64}", status["publisherIdentity"]["receiptSha256"])


def test_malformed_publisher_receipt_is_retained_as_a_nonterminal_incident(
    tmp_path: Path,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    receipt.write_text('{"schemaVersion":"1.0.0","token":"npm_secret"}\n')

    verifier.state_main(_task7_state_args(tmp_path, receipt=receipt))

    status = json.loads((tmp_path / "publication-status.json").read_text())
    assert status["state"] == "npm_only"
    assert status["publisherIdentity"]["conclusion"] == "failed"
    assert status["publisherIdentity"]["reason"] == "receipt_invalid"
    assert status["publisherIdentity"]["identity"] is None
    assert re.fullmatch(r"[0-9a-f]{64}", status["publisherIdentity"]["receiptSha256"])
    assert "npm_secret" not in json.dumps(status)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tag", "kaji-v0.2.0-beta." + "8"),
        ("workflowSha", "b" * 40),
        ("expectedPublisher", "attacker"),
        ("actualPublisher", "attacker"),
    ],
)
def test_tuple_invalid_publisher_receipt_is_redacted_but_hash_retained(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    document = _task7_publisher_receipt(receipt)
    document[field] = value
    receipt.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    verifier.state_main(_task7_state_args(tmp_path, receipt=receipt))

    status = json.loads((tmp_path / "publication-status.json").read_text())
    assert status["state"] == "npm_only"
    assert status["publisherIdentity"]["conclusion"] == "failed"
    assert status["publisherIdentity"]["reason"] == "receipt_invalid"
    assert status["publisherIdentity"]["identity"] is None
    assert (
        status["publisherIdentity"]["receiptSha256"]
        == hashlib.sha256(receipt.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "remove",
    [
        "--publisher-artifact-name",
        "--publisher-artifact-id",
        "--publisher-artifact-digest",
    ],
)
def test_publisher_receipt_inputs_are_all_or_none(
    tmp_path: Path,
    remove: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    _task7_publisher_receipt(receipt)
    command = _task7_state_args(tmp_path, receipt=receipt)
    index = command.index(remove)
    del command[index : index + 2]

    with pytest.raises(SystemExit):
        verifier.state_main(command)
    assert not (tmp_path / "publication-status.json").exists()


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--publisher-artifact-name", "kaji-publisher-identity-999-1"),
        ("--publisher-artifact-id", "0"),
        ("--publisher-artifact-id", "9007199254740992"),
        ("--publisher-artifact-digest", "sha256:" + "A" * 64),
    ],
)
def test_publisher_receipt_rejects_noncanonical_artifact_identity(
    tmp_path: Path,
    flag: str,
    value: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    _task7_publisher_receipt(receipt)
    command = _task7_state_args(tmp_path, receipt=receipt)
    command[command.index(flag) + 1] = value

    with pytest.raises(SystemExit):
        verifier.state_main(command)
    assert not (tmp_path / "publication-status.json").exists()


@pytest.mark.parametrize(
    ("receipt_arm", "no_receipt_reason", "npm_publish_result"),
    [
        (False, "publish_job_not_started", "failure"),
        (False, "publish_job_not_started", "cancelled"),
        (False, "publish_job_not_started", "success"),
        (False, "publish_job_not_started", "unknown"),
        (False, "receipt_outputs_missing", "skipped"),
        (False, "receipt_artifact_metadata_mismatch", "skipped"),
        (False, "receipt_download_failed", "skipped"),
        (True, None, "skipped"),
    ],
)
def test_publisher_receipt_state_rejects_contradictory_job_outcomes(
    tmp_path: Path,
    receipt_arm: bool,
    no_receipt_reason: str | None,
    npm_publish_result: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    _task7_publisher_receipt(receipt)

    with pytest.raises(SystemExit):
        verifier.state_main(
            _task7_state_args(
                tmp_path,
                receipt=receipt if receipt_arm else None,
                no_receipt_reason=no_receipt_reason,
                npm_publish_result=npm_publish_result,
            )
        )
    assert not (tmp_path / "publication-status.json").exists()


def _task7_terminal_publication_status(tmp_path: Path) -> Path:
    verifier = _load_root_script("verify_published_packages.py")
    receipt = tmp_path / "publisher.json"
    _task7_publisher_receipt(receipt)
    verifier.state_main(_task7_state_args(tmp_path, receipt=receipt))
    return tmp_path / "publication-status.json"


def test_release_evidence_status_only_cli_accepts_exact_terminal_identity(
    tmp_path: Path,
) -> None:
    status = _task7_terminal_publication_status(tmp_path)
    output = tmp_path / "publication-status-validation.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "kaji/scripts/validate_release_evidence.py"),
            "publication-status",
            "--publication-status",
            str(status),
            "--expected-commit",
            "a" * 40,
            "--workflow-run",
            "https://github.com/enkyuan/alloy/actions/runs/123",
            "--workflow-run-attempt",
            "1",
            "--expected-tag",
            "kaji-v0.2.0-beta.11",
            "--expected-workflow-path",
            ".github/workflows/kaji.publish.yml",
            "--expected-workflow-sha",
            "a" * 40,
            "--expected-publisher",
            "enkyuan",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(output.read_text())
    assert summary["conclusion"] == "passed"
    assert summary["state"] == "npm_byte_verified"
    assert summary["publisherIdentity"]["conclusion"] == "passed"
    assert (
        summary["publicationStatusSha256"]
        == hashlib.sha256(status.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("target",), "dual"),
        (("state",), "npm_only"),
        (("previousState",), "npm_only"),
        (("releaseReady",), False),
        (("installRecommendation",), False),
        (("registries", "pypi"), "present"),
        (("publishJobs", "npm"), "failure"),
        (("registryVerification",), "failed"),
        (("incident",), {"code": "forged", "recovery": "forged"}),
        (("commit",), "b" * 40),
        (("tag",), "kaji-v0.2.0-beta." + "8"),
        (("workflowRun",), "https://github.com/enkyuan/alloy/actions/runs/999"),
        (("workflowRunAttempt",), 2),
        (("workflowPath",), ".github/workflows/attacker.yml"),
        (("workflowSha",), "b" * 40),
        (("expectedPublisher",), "attacker"),
        (("publisherIdentity", "conclusion"), "failed"),
        (("publisherIdentity", "receiptSha256"), None),
        (("publisherIdentity", "receiptSha256"), "0" * 64),
        (("publisherIdentity", "artifact", "name"), "kaji-publisher-identity-999-1"),
        (("publisherIdentity", "artifact", "id"), 0),
        (("publisherIdentity", "artifact", "digest"), "sha256:" + "A" * 64),
        (("publisherIdentity", "identity", "schemaVersion"), 1),
        (("publisherIdentity", "identity", "commit"), "b" * 40),
        (("publisherIdentity", "identity", "tag"), "kaji-v0.2.0-beta." + "8"),
        (
            ("publisherIdentity", "identity", "workflowRun"),
            "https://github.com/enkyuan/alloy/actions/runs/999",
        ),
        (("publisherIdentity", "identity", "workflowRunAttempt"), 2),
        (
            ("publisherIdentity", "identity", "workflowPath"),
            ".github/workflows/attacker.yml",
        ),
        (("publisherIdentity", "identity", "workflowSha"), "b" * 40),
        (("publisherIdentity", "identity", "expectedPublisher"), "attacker"),
        (
            ("publisherIdentity", "identity", "actualPublisher"),
            "attacker",
        ),
        (("publisherIdentity", "identity", "conclusion"), "failed"),
        (("publisherIdentity", "identity", "exitCode"), 1),
        (("publisherIdentity", "identity", "failureCode"), "publisher_mismatch"),
    ],
)
def test_release_evidence_status_only_validation_rejects_hostile_mutations(
    tmp_path: Path,
    path: tuple[str, ...],
    value: object,
) -> None:
    status = _task7_terminal_publication_status(tmp_path)
    document = json.loads(status.read_text())
    target = document
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    status.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    validator = _load_root_script("validate_release_evidence.py")

    with pytest.raises(validator.EvidenceValidationError):
        validator.validate_publication_status(
            status,
            expected_commit="a" * 40,
            workflow_run="https://github.com/enkyuan/alloy/actions/runs/123",
            workflow_run_attempt=1,
            expected_tag="kaji-v0.2.0-beta.11",
            expected_workflow_path=".github/workflows/kaji.publish.yml",
            expected_workflow_sha="a" * 40,
            expected_publisher="enkyuan",
        )


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
                "packages": {"python": "0.2.0b1", "typescript": "0.2.0-beta.11"},
                "artifacts": [
                    {
                        "file": "kaji-0.2.0b1-py3-none-any.whl",
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
                "--tag",
                "kaji-v0.2.0-beta.11",
                "--workflow-path",
                ".github/workflows/kaji.publish.yml",
                "--workflow-sha",
                "a" * 40,
                "--workflow-run-id",
                "123",
                "--workflow-run-attempt",
                "1",
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
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
        )


@pytest.mark.parametrize(
    "redirect",
    [
        "https://attacker.example/package",
        "http://pypi.org/package",
        "https://pypi.org:444/package",
        "https://user@pypi.org/package",
        "https://pypi.org:invalid/package",
    ],
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
                "--tag",
                "kaji-v0.2.0-beta.11",
                "--workflow-path",
                ".github/workflows/kaji.publish.yml",
                "--workflow-sha",
                "a" * 40,
                "--workflow-run-id",
                "123",
                "--workflow-run-attempt",
                "1",
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
                "--tag",
                "kaji-v0.2.0-beta.11",
                "--workflow-path",
                ".github/workflows/kaji.publish.yml",
                "--workflow-sha",
                "a" * 40,
                "--workflow-run-id",
                "123",
                "--workflow-run-attempt",
                "1",
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
        "kaji-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji-0.2.0b1.tar.gz": b"sdist",
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
                    "info": {"name": "kaji", "version": "0.2.0b1"},
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
    assert sum("/integrity/kaji/0.2.0b1/" in url for url in fetched) == 2
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
        "registry-kaji-0.2.0b1-py3-none-any.whl",
        "registry-kaji-0.2.0b1.tar.gz",
    }.issubset(retained)
    assert sum(name.endswith(".provenance.json") for name in retained) == 2
    assert sum(name.endswith(".github-attestation.json") for name in retained) == 2


@pytest.mark.parametrize(
    ("published_names", "expected_error"),
    [
        (
            ["kaji-0.2.0b1-py3-none-any.whl"],
            "VerificationUnavailable",
        ),
        (
            [
                "kaji-0.2.0b1-py3-none-any.whl",
                "kaji-0.2.0b1.tar.gz",
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
            "kaji-0.2.0b1-py3-none-any.whl",
            "kaji-0.2.0b1.tar.gz",
        )
    }
    metadata = {
        "info": {"name": "kaji", "version": "0.2.0b1"},
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
        "info": {"name": "kaji-sdk", "version": "0.2.0b1"},
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


def _task7_provenance_statement(
    payload: bytes,
    *,
    repository: str = "enkyuan/alloy",
    commit: str = "a" * 40,
    workflow_sha: str = "a" * 40,
    tag: str = "kaji-v0.2.0-beta.11",
    workflow_path: str = ".github/workflows/kaji.publish.yml",
    run_id: int = 123,
    run_attempt: int = 1,
    subject_name: str = "pkg:npm/%40irogane%2Fkaji@0.2.0-beta.11",
    digest_algorithm: str = "sha512",
) -> dict[str, object]:
    del workflow_sha  # The signed statement binds it through the peeled commit.
    ref = f"refs/tags/{tag}"
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": subject_name,
                "digest": {
                    digest_algorithm: hashlib.new(digest_algorithm, payload).hexdigest()
                },
            }
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": (
                    "https://slsa-framework.github.io/"
                    "github-actions-buildtypes/workflow/v1"
                ),
                "externalParameters": {
                    "workflow": {
                        "ref": ref,
                        "repository": f"https://github.com/{repository}",
                        "path": workflow_path,
                    }
                },
                "internalParameters": {
                    "github": {
                        "event_name": "push",
                        "repository_id": "1234",
                        "repository_owner_id": "5678",
                    }
                },
                "resolvedDependencies": [
                    {
                        "uri": f"git+https://github.com/{repository}@{ref}",
                        "digest": {"gitCommit": commit},
                    }
                ],
            },
            "runDetails": {
                "builder": {"id": "https://github.com/actions/runner/github-hosted"},
                "metadata": {
                    "invocationId": (
                        f"https://github.com/{repository}/actions/runs/"
                        f"{run_id}/attempts/{run_attempt}"
                    )
                },
            },
        },
    }


def _task7_sigstore_bundle(statement: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(statement, separators=(",", ":"), sort_keys=True).encode()
    return {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "dsseEnvelope": {
            "payloadType": "application/vnd.in-toto+json",
            "payload": base64.b64encode(encoded).decode(),
            "signatures": [{"sig": base64.b64encode(b"signature").decode()}],
        },
        "verificationMaterial": {
            "certificate": {"rawBytes": base64.b64encode(b"certificate").decode()},
            "tlogEntries": [],
        },
    }


def _task7_certificate(
    *,
    repository: str = "enkyuan/alloy",
    commit: str = "a" * 40,
    workflow_sha: str = "a" * 40,
    tag: str = "kaji-v0.2.0-beta.11",
    workflow_path: str = ".github/workflows/kaji.publish.yml",
    run_id: int = 123,
    run_attempt: int = 1,
) -> dict[str, object]:
    ref = f"refs/tags/{tag}"
    workflow_uri = f"https://github.com/{repository}/{workflow_path}@{ref}"
    return {
        "subjectAlternativeName": workflow_uri,
        "issuer": "https://token.actions.githubusercontent.com",
        "githubWorkflowSHA": workflow_sha,
        "githubWorkflowRepository": repository,
        "githubWorkflowRef": ref,
        "buildSignerURI": workflow_uri,
        "buildSignerDigest": workflow_sha,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{repository}",
        "sourceRepositoryDigest": commit,
        "sourceRepositoryRef": ref,
        "buildConfigURI": workflow_uri,
        "buildConfigDigest": workflow_sha,
        "runInvocationURI": (
            f"https://github.com/{repository}/actions/runs/"
            f"{run_id}/attempts/{run_attempt}"
        ),
        "sourceRepositoryVisibilityAtSigning": "public",
    }


def _task7_gh_output(
    statement: dict[str, object],
    *,
    repository: str = "enkyuan/alloy",
    commit: str = "a" * 40,
    workflow_sha: str = "a" * 40,
    tag: str = "kaji-v0.2.0-beta.11",
    workflow_path: str = ".github/workflows/kaji.publish.yml",
    run_id: int = 123,
    run_attempt: int = 1,
) -> bytes:
    return json.dumps(
        [
            {
                "attestation": {"bundle": "cryptographically-verified-by-gh"},
                "verificationResult": {
                    "statement": statement,
                    "signature": {
                        "certificate": _task7_certificate(
                            repository=repository,
                            commit=commit,
                            workflow_sha=workflow_sha,
                            tag=tag,
                            workflow_path=workflow_path,
                            run_id=run_id,
                            run_attempt=run_attempt,
                        )
                    },
                    "verifiedTimestamps": [{"type": "Tlog"}],
                },
            }
        ]
    ).encode()


def _task7_npm_audit(
    payload: bytes,
    *,
    repository: str = "enkyuan/alloy",
    commit: str = "a" * 40,
    workflow_sha: str = "a" * 40,
    tag: str = "kaji-v0.2.0-beta.11",
    workflow_path: str = ".github/workflows/kaji.publish.yml",
    run_id: int = 123,
    run_attempt: int = 1,
) -> dict[str, Any]:
    statement = _task7_provenance_statement(
        payload,
        repository=repository,
        commit=commit,
        workflow_sha=workflow_sha,
        tag=tag,
        workflow_path=workflow_path,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    return {
        "invalid": [],
        "missing": [],
        "verified": [
            {
                "name": "@irogane/kaji",
                "version": "0.2.0-beta.11",
                "location": "node_modules/@irogane/kaji",
                "registry": "https://registry.npmjs.org/",
                "attestations": {
                    "url": (
                        "https://registry.npmjs.org/-/npm/v1/attestations/"
                        "@irogane/kaji@0.2.0-beta.11"
                    ),
                    "provenance": {"predicateType": "https://slsa.dev/provenance/v1"},
                },
                "attestationBundles": [
                    {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "bundle": _task7_sigstore_bundle(statement),
                        "signedAccessSignatureUrl": "",
                    },
                    {
                        "predicateType": (
                            "https://github.com/npm/attestation/tree/main/"
                            "specs/publish/v0.1"
                        ),
                        "bundle": _task7_sigstore_bundle(
                            {
                                **statement,
                                "predicateType": (
                                    "https://github.com/npm/attestation/tree/main/"
                                    "specs/publish/v0.1"
                                ),
                            }
                        ),
                        "signedAccessSignatureUrl": "",
                    },
                ],
            }
        ],
    }


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
                    "invalid": [],
                    "missing": [],
                    "verified": [
                        {
                            "name": "transitive-dependency",
                            "version": "1.0.0",
                            "location": "node_modules/transitive-dependency",
                            "registry": "https://registry.npmjs.org/",
                            "attestations": {
                                "url": "https://registry.npmjs.org/a",
                                "provenance": {
                                    "predicateType": ("https://slsa.dev/provenance/v1")
                                },
                            },
                            "attestationBundles": [],
                        }
                    ],
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
            bundle_file=tmp_path / "npm-provenance.sigstore.json",
            payload=b"npm-tarball",
            repository="enkyuan/alloy",
            commit="a" * 40,
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
        )


@pytest.mark.parametrize(
    ("audit", "expected_error"),
    [
        (
            {"missing": [{"name": "@irogane/kaji", "version": "0.2.0-beta.11"}]},
            "VerificationUnavailable",
        ),
        (
            {"invalid": [{"name": "@irogane/kaji", "version": "0.2.0-beta.11"}]},
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
        "file": "irogane-kaji-0.2.0-beta.11.tgz",
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
                    "tarball": (
                        "https://registry.npmjs.org/@irogane%2Fkaji/-/irogane-kaji-0.2.0-beta.11.tgz"
                    ),
                    "integrity": integrity,
                    "shasum": hashlib.sha1(payload).hexdigest(),  # noqa: S324
                }
            ).encode()
        elif command[:3] == ["npm", "audit", "signatures"]:
            stdout = json.dumps(_task7_npm_audit(payload)).encode()
        elif command[:3] == ["gh", "attestation", "verify"]:
            digest_algorithm = command[command.index("--digest-alg") + 1]
            subject = (
                _task7_provenance_statement(payload)
                if digest_algorithm == "sha512"
                else _task7_provenance_statement(
                    payload,
                    subject_name=cast(str, entry["file"]),
                    digest_algorithm="sha256",
                )
            )
            stdout = _task7_gh_output(subject)
        else:
            stdout = b"{}"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(verifier, "run_checked", run_checked)
    monkeypatch.setattr(verifier, "fetch", lambda *_args, **_kwargs: payload)

    evidence = verifier.verify_npm(
        {entry["file"]: entry},
        downloads_dir=tmp_path,
        repository="enkyuan/alloy",
        commit="a" * 40,
        tag="kaji-v0.2.0-beta.11",
        workflow_path=".github/workflows/kaji.publish.yml",
        workflow_sha="a" * 40,
        workflow_run_id=123,
        workflow_run_attempt=1,
    )

    assert evidence["byteVerified"] is True
    assert evidence["integrity"] == integrity
    assert evidence["shasum"] == hashlib.sha1(payload).hexdigest()  # noqa: S324
    assert evidence["signatureAudit"]["packageVerified"] is True
    assert (
        tmp_path / "registry-irogane-kaji-0.2.0-beta.11.tgz"
    ).read_bytes() == payload
    assert (tmp_path / "npm-signature-audit.json").is_file()
    assert (
        "npm",
        "audit",
        "signatures",
        "--json",
        "--include-attestations",
    ) in commands
    github_commands = [
        command
        for command in commands
        if command[:3] == ("gh", "attestation", "verify")
    ]
    assert len(github_commands) == 2
    assert {
        command[command.index("--digest-alg") + 1] for command in github_commands
    } == {"sha256", "sha512"}
    assert all(
        command[command.index("--source-digest") + 1] == "a" * 40
        and command[command.index("--signer-digest") + 1] == "a" * 40
        and command[command.index("--source-ref") + 1]
        == "refs/tags/kaji-v0.2.0-beta.11"
        and "--deny-self-hosted-runners" in command
        for command in github_commands
    )


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
                    "invalid": [],
                    "missing": [],
                    "verified": [
                        {
                            "name": "@irogane/kaji",
                            "version": "0.2.0-beta.11",
                            "location": "node_modules/@irogane/kaji",
                            "registry": "https://registry.npmjs.org/",
                            "attestations": {
                                "url": (
                                    "https://registry.npmjs.org/-/npm/v1/"
                                    "attestations/@irogane/kaji@0.2.0-beta.11"
                                ),
                                "provenance": {
                                    "predicateType": ("https://slsa.dev/provenance/v1")
                                },
                            },
                            "attestationBundles": [],
                        },
                        {
                            "name": "transitive-dependency",
                            "version": "1.0.0",
                            "location": "node_modules/transitive-dependency",
                            "registry": "https://registry.npmjs.org/",
                            "attestations": {
                                "url": "https://registry.npmjs.org/a",
                                "provenance": {
                                    "predicateType": ("https://slsa.dev/provenance/v1")
                                },
                            },
                            "attestationBundles": [
                                {
                                    "predicateType": ("https://slsa.dev/provenance/v1"),
                                    "bundle": {},
                                }
                            ],
                        },
                    ],
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
            bundle_file=tmp_path / "npm-provenance.sigstore.json",
            payload=b"npm-tarball",
            repository="enkyuan/alloy",
            commit="a" * 40,
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
        )


@pytest.mark.parametrize(
    "integrity",
    [
        "",
        "sha256-" + base64.b64encode(b"x" * 32).decode(),
        "sha512-" + base64.b64encode(b"x" * 63).decode(),
        "sha512-" + base64.b64encode(b"x" * 64).decode() + " extra",
        "sha512-" + base64.b64encode(b"x" * 64).decode() + "\n",
        "sha512-" + base64.b64encode(b"x" * 64).decode() + "=",
    ],
)
def test_npm_integrity_is_exactly_one_canonical_sha512_token(
    integrity: str,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    with pytest.raises(verifier.VerificationMismatch):
        verifier.parse_integrity(integrity)


@pytest.mark.parametrize(
    "shasum",
    [None, "", "A" * 40, "a" * 39, "a" * 41, "g" * 40, "a" * 40 + " "],
)
def test_npm_shasum_is_mandatory_canonical_sha1(shasum: object) -> None:
    verifier = _load_root_script("verify_published_packages.py")

    with pytest.raises(verifier.VerificationMismatch):
        verifier.validate_shasum(shasum, b"npm-tarball")


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "subject-purl",
            lambda audit: audit["verified"][0]["attestationBundles"][0]["bundle"][
                "dsseEnvelope"
            ].update(
                {
                    "payload": base64.b64encode(
                        json.dumps(
                            {
                                **_task7_provenance_statement(b"npm-tarball"),
                                "subject": [
                                    {
                                        "name": "pkg:npm/dependency@1.0.0",
                                        "digest": {
                                            "sha512": hashlib.sha512(
                                                b"npm-tarball"
                                            ).hexdigest()
                                        },
                                    }
                                ],
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode()
                    ).decode()
                }
            ),
        ),
        (
            "duplicate-provenance",
            lambda audit: audit["verified"][0]["attestationBundles"].append(
                audit["verified"][0]["attestationBundles"][0]
            ),
        ),
        (
            "dependency-only",
            lambda audit: audit["verified"][0].update(
                {"name": "dependency", "version": "1.0.0"}
            ),
        ),
        (
            "wrong-location",
            lambda audit: audit["verified"][0].update(
                {"location": "node_modules/dependency"}
            ),
        ),
        (
            "wrong-registry",
            lambda audit: audit["verified"][0].update(
                {"registry": "https://attacker.example/"}
            ),
        ),
        (
            "attestation-url-attacker-prefix",
            lambda audit: audit["verified"][0]["attestations"].update(
                {
                    "url": (
                        "https://registry.npmjs.org/-/npm/v1/attestations/"
                        "attacker-kaji@0.2.0-beta.11"
                    )
                }
            ),
        ),
        (
            "attestation-url-attacker-suffix",
            lambda audit: audit["verified"][0]["attestations"].update(
                {
                    "url": (
                        "https://registry.npmjs.org/-/npm/v1/attestations/"
                        "kaji@0.2.0-beta.11.attacker"
                    )
                }
            ),
        ),
        (
            "attestation-provenance-missing",
            lambda audit: audit["verified"][0]["attestations"].pop("provenance"),
        ),
        (
            "attestation-provenance-extra-key",
            lambda audit: audit["verified"][0]["attestations"]["provenance"].update(
                {"unexpected": True}
            ),
        ),
        (
            "attestation-provenance-wrong-predicate",
            lambda audit: audit["verified"][0]["attestations"]["provenance"].update(
                {"predicateType": "https://attacker.example/provenance/v1"}
            ),
        ),
        (
            "attestation-root-extra-key",
            lambda audit: audit["verified"][0]["attestations"].update(
                {"unexpected": True}
            ),
        ),
        (
            "arbitrary-bundle",
            lambda audit: audit["verified"][0]["attestationBundles"][0].update(
                {"bundle": {"truthy": True}}
            ),
        ),
        (
            "nonempty-signed-access-signature-url",
            lambda audit: audit["verified"][0]["attestationBundles"][0].update(
                {"signedAccessSignatureUrl": "https://attacker.example/signature"}
            ),
        ),
    ],
)
def test_npm11_audit_contract_selects_only_the_exact_target_provenance(
    label: str,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    del label
    verifier = _load_root_script("verify_published_packages.py")
    payload = b"npm-tarball"
    audit = _task7_npm_audit(payload)
    mutate(audit)

    with pytest.raises(
        (verifier.VerificationMismatch, verifier.VerificationUnavailable)
    ):
        verifier.parse_npm_audit_output(
            json.dumps(audit).encode(),
            payload=payload,
            repository="enkyuan/alloy",
            commit="a" * 40,
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("subject", 0, "name"), "pkg:npm/dependency@1.0.0"),
        (("subject", 0, "digest", "sha512"), "b" * 128),
        (
            ("predicate", "buildDefinition", "buildType"),
            "https://attacker.example/workflow/v1",
        ),
        (
            (
                "predicate",
                "buildDefinition",
                "externalParameters",
                "workflow",
                "repository",
            ),
            "https://github.com/attacker/alloy",
        ),
        (
            (
                "predicate",
                "buildDefinition",
                "externalParameters",
                "workflow",
                "ref",
            ),
            "refs/tags/kaji-v0.2.0-beta." + "8",
        ),
        (
            (
                "predicate",
                "buildDefinition",
                "externalParameters",
                "workflow",
                "path",
            ),
            ".github/workflows/attacker.yml",
        ),
        (
            (
                "predicate",
                "buildDefinition",
                "resolvedDependencies",
                0,
                "digest",
                "gitCommit",
            ),
            "b" * 40,
        ),
        (
            ("predicate", "runDetails", "builder", "id"),
            "https://github.com/actions/runner/self-hosted",
        ),
        (
            ("predicate", "runDetails", "metadata", "invocationId"),
            "https://github.com/enkyuan/alloy/actions/runs/999/attempts/1",
        ),
    ],
)
def test_npm_dsse_statement_rejects_every_release_identity_mutation(
    path: tuple[object, ...],
    value: object,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    payload = b"npm-tarball"
    audit = _task7_npm_audit(payload)
    bundle = audit["verified"][0]["attestationBundles"][0]["bundle"]  # type: ignore[index]
    envelope = bundle["dsseEnvelope"]  # type: ignore[index]
    statement = json.loads(base64.b64decode(envelope["payload"]))  # type: ignore[index]
    target: Any = statement
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    envelope["payload"] = base64.b64encode(  # type: ignore[index]
        json.dumps(statement, separators=(",", ":"), sort_keys=True).encode()
    ).decode()

    with pytest.raises(verifier.VerificationMismatch):
        verifier.parse_npm_audit_output(
            json.dumps(audit).encode(),
            payload=payload,
            repository="enkyuan/alloy",
            commit="a" * 40,
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("statement", "subject", 0, "name"), "attacker.tgz"),
        (("statement", "subject", 0, "digest", "sha256"), "b" * 64),
        (
            ("signature", "certificate", "sourceRepositoryURI"),
            "https://github.com/attacker/alloy",
        ),
        (
            ("signature", "certificate", "sourceRepositoryRef"),
            "refs/tags/kaji-v0.2.0-beta." + "8",
        ),
        (("signature", "certificate", "sourceRepositoryDigest"), "b" * 40),
        (("signature", "certificate", "githubWorkflowSHA"), "b" * 40),
        (
            ("signature", "certificate", "buildSignerURI"),
            "https://github.com/attacker/alloy/.github/workflows/publish.yml@refs/tags/x",
        ),
        (
            ("signature", "certificate", "runnerEnvironment"),
            "self-hosted",
        ),
        (
            ("signature", "certificate", "runInvocationURI"),
            "https://github.com/enkyuan/alloy/actions/runs/123/attempts/2",
        ),
    ],
)
def test_zero_exit_gh_json_rejects_wrong_subject_or_certificate_identity(
    path: tuple[object, ...],
    value: object,
) -> None:
    verifier = _load_root_script("verify_published_packages.py")
    payload = b"npm-tarball"
    statement = _task7_provenance_statement(
        payload,
        subject_name="irogane-kaji-0.2.0-beta.11.tgz",
        digest_algorithm="sha256",
    )
    output = json.loads(_task7_gh_output(statement))
    result = output[0]["verificationResult"]
    target: Any = result
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(verifier.VerificationMismatch):
        verifier.validate_gh_attestation_output(
            json.dumps(output).encode(),
            payload=payload,
            subject_name="irogane-kaji-0.2.0-beta.11.tgz",
            digest_algorithm="sha256",
            repository="enkyuan/alloy",
            commit="a" * 40,
            tag="kaji-v0.2.0-beta.11",
            workflow_path=".github/workflows/kaji.publish.yml",
            workflow_sha="a" * 40,
            workflow_run_id=123,
            workflow_run_attempt=1,
            require_npm_statement=False,
        )


def test_gh_attestation_accepts_batch_statement_with_one_exact_target() -> None:
    verifier = _load_root_script("verify_published_packages.py")
    payload = b"npm-tarball"
    statement = _task7_provenance_statement(
        payload,
        subject_name="irogane-kaji-0.2.0-beta.11.tgz",
        digest_algorithm="sha256",
    )
    cast(list[dict[str, object]], statement["subject"]).append(
        {
            "name": "manifest.json",
            "digest": {"sha256": hashlib.sha256(b"manifest").hexdigest()},
        }
    )

    evidence = verifier.validate_gh_attestation_output(
        _task7_gh_output(statement),
        payload=payload,
        subject_name="irogane-kaji-0.2.0-beta.11.tgz",
        digest_algorithm="sha256",
        repository="enkyuan/alloy",
        commit="a" * 40,
        tag="kaji-v0.2.0-beta.11",
        workflow_path=".github/workflows/kaji.publish.yml",
        workflow_sha="a" * 40,
        workflow_run_id=123,
        workflow_run_attempt=1,
        require_npm_statement=False,
    )

    assert evidence["statement"]["name"] == "irogane-kaji-0.2.0-beta.11.tgz"
    assert evidence["statement"]["digest"] == hashlib.sha256(payload).hexdigest()


def test_release_composite_actions_are_sha_pinned() -> None:
    for relative in (
        ".github/actions/setup-python-uv/action.yml",
        ".github/actions/setup-bun-cache/action.yml",
    ):
        _assert_external_actions_are_sha_pinned(_read(relative))


def test_release_runbook_has_fail_closed_rollback_contract() -> None:
    runbook = _read("docs/kaji/releasing.md")
    protected_release = runbook.split("## Protected release", 1)[1].split(
        "## Partial or ambiguous publication", 1
    )[0]

    assert "TAG=kaji-v0.2.0-beta.11" in protected_release
    assert 'git tag -s --cleanup=verbatim -F "$AUTHORIZATION_FILE"' in (
        protected_release
    )
    assert '"$TAG" "$REVIEWED_COMMIT"' in protected_release
    assert 'git verify-tag "$TAG"' in protected_release
    assert 'git push origin "refs/tags/$TAG"' in protected_release
    assert "kaji-v0.2.0-beta.2" not in protected_release
    assert "kaji-v0.2.0-beta.4" not in protected_release
    assert "0.2.0-beta.4" not in _read(".github/workflows/kaji.rehearsal.yml")
    assert "burned, immutable pre-build attempt" in runbook
    assert "run `30190948860`" in runbook
    assert "burned, immutable TTHW attempt" in runbook
    assert "run `30206052570`" in runbook
    assert "paired benchmark aggregate" in runbook
    assert "burned, immutable signed attempt" in runbook
    assert "run `30215694650`" in runbook
    assert "`KAJI_TTHW_EVIDENCE_JSON` was unset" in runbook
    assert "the job received zero bytes" in runbook
    assert "never reached provider proof, publisher preflight" in " ".join(
        runbook.split()
    )
    assert "burned, immutable performance attempt" in runbook
    assert "run `30230234051`" in runbook
    assert "`1.2059658457`, `1.0034830060`, and `1.0137219363`" in runbook
    assert (
        "TTHW, provider proof, publisher preflight, and npm publication were skipped"
        in " ".join(runbook.split())
    )
    assert "run `30265105639`" in runbook
    assert "`0.9805314383`, `0.9756823917`," in runbook
    assert "and `1.2290586651`" in runbook
    assert "recovery requires the new beta.8 attempt" in runbook
    assert "run `30296132900`" in runbook
    assert "`4dd04a1cf74927c4b3de31a1bd1db54a7b7c7a4e`" in runbook
    assert "`KAJI_TTHW_EVIDENCE_JSON` was empty" in runbook
    assert "five-user TTHW validation did not start" in runbook
    assert "recovery requires the new beta.9 attempt" in runbook
    assert "Immutable beta.9 run `30726249929` failed closed" in runbook
    assert "setup-node's deprecated `always-auth=false` setting" in runbook
    assert "npm and PyPI remained absent" in runbook

    for expected in (
        "verified, signed, annotated beta tag",
        "`kaji-release` protects mandatory keyed OpenAI proof",
        "yank",
        "npm deprecate",
        "preserve",
        "Never reuse the",
        "No keyed provider or publisher evidence is claimed",
        "`kaji-publish`",
        "Protect `kaji-v*-beta.*` tags against update and deletion",
        "annotated tag object SHA",
        "never click **Re-run failed jobs**",
        "partial_or_ambiguous",
        'git tag -s -a kaji-v0.2.0-beta.2 <approved-commit> -m "Kaji 0.2.0 beta 2"',
        "npm deprecate kaji@0.2.0-beta.2",
        "compares every existing asset's",
        "SHA-256 digest",
        "`KAJI_RELEASE_SIGNER_EMAIL`",
        "does not claim a separately",
        "publication is deferred",
        "no Python publisher",
        "`npm_byte_verified`",
        "exact ordered 27 assets",
        "Land the approved release commit on the default branch",
        "Never tag a feature-branch-only commit",
        "fresh `NPM_TOKEN` is stored only in",
        "Do not run a local credential preflight",
        "exact `npm whoami` equality with `KAJI_NPM_PUBLISHER`",
        "stable `tiny-tarball@1.0.0` npm control",
        "`kaji` packument is an exact 404 JSON object",
        '`{"error":"Not found"}`',
        "exact beta.11 endpoint is an exact 404 JSON",
        'string `"Not Found"`',
        "infer absence from npm CLI error text or a substring match",
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
        "kaji-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji-0.2.0b1.tar.gz": b"sdist",
        "irogane-kaji-0.2.0-beta.11.tgz": b"npm",
    }
    entries = []
    for name, payload in payloads.items():
        (artifacts / name).write_bytes(payload)
        package = "typescript" if name.endswith(".tgz") else "python"
        version = "0.2.0-beta.11" if package == "typescript" else "0.2.0b1"
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
            "file": "kaji/packages/py/build-requirements.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "kaji/packages/py/build-requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "packages": {
            "contract": "1.0.0",
            "python": "0.2.0b1",
            "typescript": "0.2.0-beta.11",
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
        verified.python_wheel == (artifacts / "kaji-0.2.0b1-py3-none-any.whl").resolve()
    )
    assert verified.python_sdist == (artifacts / "kaji-0.2.0b1.tar.gz").resolve()
    assert (
        verified.npm_tarball == (artifacts / "irogane-kaji-0.2.0-beta.11.tgz").resolve()
    )
    with pytest.raises(TypeError):
        cast(MutableMapping[str, str], verified.artifact_sha256)["extra"] = (
            "not immutable"
        )
    member_bytes = {path.name: path.read_bytes() for path in artifacts.iterdir()}
    verified_bytes = module.verify_release_member_bytes(member_bytes, commit)
    assert verified_bytes.commit == commit
    assert verified_bytes.manifest_sha256 == verified.manifest_sha256
    assert verified_bytes.members["irogane-kaji-0.2.0-beta.11.tgz"] == b"npm"
    with pytest.raises(TypeError):
        cast(MutableMapping[str, bytes], verified_bytes.members)["extra"] = b"x"
    changed_members = {
        **member_bytes,
        "irogane-kaji-0.2.0-beta.11.tgz": b"tampered",
    }
    with pytest.raises(SystemExit, match="size/hash mismatch"):
        module.verify_release_member_bytes(changed_members, commit)
    boolean_schema_members = dict(member_bytes)
    boolean_schema_manifest = json.loads(boolean_schema_members["manifest.json"])
    boolean_schema_manifest["schemaVersion"] = True
    boolean_schema_members["manifest.json"] = json.dumps(
        boolean_schema_manifest
    ).encode()
    with pytest.raises(SystemExit, match="manifest schema or commit mismatch"):
        module.verify_release_member_bytes(boolean_schema_members, commit)

    assert subprocess.run(command, check=False).returncode == 0
    (artifacts / "irogane-kaji-0.2.0-beta.11.tgz").write_bytes(b"tampered")
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "size/hash mismatch" in result.stderr

    (artifacts / "irogane-kaji-0.2.0-beta.11.tgz").write_bytes(
        payloads["irogane-kaji-0.2.0-beta.11.tgz"]
    )
    unexpected = artifacts / "unexpected.whl"
    unexpected.write_bytes(b"extra")
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "artifact file set mismatch" in result.stderr
    unexpected.unlink()

    wheel = artifacts / "kaji-0.2.0b1-py3-none-any.whl"
    wheel.unlink()
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "artifact file set mismatch" in result.stderr
    wheel.write_bytes(payloads[wheel.name])

    npm = artifacts / "irogane-kaji-0.2.0-beta.11.tgz"
    npm.unlink()
    npm.symlink_to(wheel)
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    assert result.returncode != 0
    assert "non-regular file or symlink" in result.stderr


@pytest.mark.parametrize(
    ("selector", "expected_contract_name"),
    [
        ((), "BETA10_RELEASE_CONTRACT"),
        (
            ("--artifact-contract", "beta2-reference"),
            "BETA2_REFERENCE_RELEASE_CONTRACT",
        ),
    ],
)
def test_release_artifact_cli_selects_exact_allowlisted_contract(
    monkeypatch: pytest.MonkeyPatch,
    selector: tuple[str, ...],
    expected_contract_name: str,
) -> None:
    module = _load_root_script("verify_release_artifacts.py")
    selected: list[object] = []

    def capture_contract(
        _artifacts: Path,
        _expected_commit: str,
        *,
        artifact_contract: object,
    ) -> None:
        selected.append(artifact_contract)

    monkeypatch.setattr(module, "verify", capture_contract)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "--artifacts-dir",
            "artifacts",
            "--expected-commit",
            "a" * 40,
            *selector,
        ],
    )

    module.main()

    assert selected == [getattr(module, expected_contract_name)]


def test_release_artifact_cli_rejects_unsupported_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_root_script("verify_release_artifacts.py")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_release_artifacts.py",
            "--artifacts-dir",
            "artifacts",
            "--expected-commit",
            "a" * 40,
            "--artifact-contract",
            "beta1",
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        module.main()

    assert "invalid choice: 'beta1'" in capsys.readouterr().err


def test_compatibility_matrices_consume_and_retain_frozen_artifacts() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")
    rehearsal_python = rehearsal.split("  python-compat:", 1)[1].split(
        "  node-compat:", 1
    )[0]
    rehearsal_node = rehearsal.split("  node-compat:", 1)[1].split(
        "  typescript-onboarding-archive-calibration:", 1
    )[0]
    publish_python = publish.split("  python-compat:", 1)[1].split("  node-compat:", 1)[
        0
    ]
    publish_node = publish.split("  node-compat:", 1)[1].split(
        "  typescript-onboarding-archive-calibration:", 1
    )[0]

    assert "needs: offline-release" in rehearsal_python
    assert "needs: offline-release" in rehearsal_node
    assert "needs: [verify-tag, offline-gates]" in publish_python
    assert "needs: [verify-tag, offline-gates]" in publish_node

    for job, smoke in (
        (rehearsal_python, "kaji/scripts/release_smoke.py"),
        (publish_python, "kaji/scripts/release_smoke.py"),
        (rehearsal_node, "kaji/packages/ts/scripts/smoke_package.mts"),
        (publish_node, "kaji/packages/ts/scripts/smoke_package.mts"),
    ):
        initialize = job.index("Initialize compatibility receipt before setup")
        initial_upload = job.index("Retain initial not-run compatibility receipt")
        checkout = job.index("actions/checkout@")
        terminal_step_name = (
            "Finalize closed protected Node receipt"
            if smoke == "kaji/packages/ts/scripts/smoke_package.mts"
            else "Normalize compatibility receipt"
        )
        terminal = job.index(terminal_step_name)
        final_upload = job.index("Retain final compatibility receipt")
        assert initialize < initial_upload < checkout
        assert (
            job.index("actions/download-artifact@")
            < job.index("verify_release_artifacts.py")
            < job.index(smoke)
            < terminal
            < final_upload
        )
        job_environment = job.split("    strategy:", 1)[0]
        assert "${{ runner." not in job_environment
        assert "path: .artifacts/kaji-release" in job
        assert "--expected-commit" in job
        assert "--output" in job
        if smoke == "kaji/packages/ts/scripts/smoke_package.mts":
            assert "artifact-ids:" in job
            assert "Resolve exact producer artifact by ID" in job
            assert job.count("if: ${{ always() }}") == 2
            assert "Normalize compatibility receipt" not in job
            assert 'schemaVersion: 2, executionMode: "protected"' in job
            assert "--protected" in job
            assert "--expected-node-major" in job
            assert "--configured-runner-label" in job
            assert "--producer-artifact-id" in job
            assert "--producer-artifact-digest" in job
            assert "assertClosedOrdinaryReceipt" in job
            assert "assertProtectedOrdinaryReceiptForWorkflow" in job
            assert "node_smoke_failed" in job
            assert "onboardingProofs" in job
        else:
            assert "name: kaji-artifacts" in job
            assert job.count("if: ${{ always() }}") == 2
            assert "Normalize compatibility receipt" in job
            assert (
                '.conclusion == "passed" and (keys == passed_keys) and '
                ".failureCode == null" in job
            )
            assert ".githubPackageProofs" in job
            assert ".timings" in job
            assert 'keys == ["sdist", "wheel"]' in job
            assert "9007199254740991" in job
            assert 'runtime: "python", network: "scripted"' in job
            assert (
                'schemaVersion: 5, evidenceClass: "offline_exact_artifact_smoke"' in job
            )
            assert "publicScenarioCount: 15" in job
            assert 'reason_code: "github_token_missing"' in job
            assert "githubObservabilitySinksVerified: true" in job
            assert "unknownMutationPreserved: true, mutationRetries: 0" in job
            assert ".releaseManifestSha256 | sha256" in job
            assert "all(.[]; sha256)" in job
            assert "compatibility_receipt_not_terminal" in job
        assert job.count("uses: actions/upload-artifact@") == 2
        assert "-initial" in job
        assert "compatibility-receipt.json" in job
        assert "uv build" not in job
        assert "npm pack" not in job
        assert "bun run package:smoke" not in job

    for job in (rehearsal_python, publish_python):
        assert "--artifacts-dir .artifacts/kaji-release" in job
    for job in (rehearsal_node, publish_node):
        assert "--release-manifest .artifacts/kaji-release/manifest.json" in job
        assert '--expected-commit "$EXPECTED_COMMIT"' in job

    onboarding_guide = _read("docs/kaji/typescript-onboarding-evidence.md")
    node22_cell = "| Node 22 | `ubuntu-22.04` / `ubuntu22` | exact `v22.x.y` |"
    node24_cell = "| Node 24 | `ubuntu-24.04` / `ubuntu24` | exact `v24.x.y` |"
    assert onboarding_guide.index(node22_cell) < onboarding_guide.index(node24_cell)

    normalized_onboarding_guide = " ".join(onboarding_guide.split())
    for claim in (
        "exactly these GitHub-hosted Linux/x64 cells:",
        "two-cell aggregate recomputation",
        "passed `artifactInstall`, `scaffoldInit`, `noKeyRun`, `echoSetup`, "
        "`echoRun`, `coldRun`, and `warmRun` phases for npm and Bun;",
        "nonnegative observed cold-setup-to-output and warm-run durations. "
        "These are retained observations, not human timing thresholds or "
        "performance gates.",
    ):
        assert claim in normalized_onboarding_guide


def test_release_github_scripts_parse_the_explicit_run_attempt_input() -> None:
    rehearsal = _read(".github/workflows/kaji.rehearsal.yml")
    publish = _read(".github/workflows/kaji.publish.yml")
    rehearsal_node = rehearsal.split("  node-compat:", 1)[1].split(
        "  typescript-onboarding-archive-calibration:", 1
    )[0]
    publish_verify_tag = publish.split("  verify-tag:", 1)[1].split(
        "  offline-gates:", 1
    )[0]
    publish_node = publish.split("  node-compat:", 1)[1].split(
        "  typescript-onboarding-archive-calibration:", 1
    )[0]

    assert "context.runAttempt" not in rehearsal
    assert "context.runAttempt" not in publish
    for script_boundary in (rehearsal_node, publish_verify_tag, publish_node):
        assert "RUN_ATTEMPT: ${{ github.run_attempt }}" in script_boundary
        assert "const runAttempt = Number(process.env.RUN_ATTEMPT);" in script_boundary
        assert "!Number.isSafeInteger(runAttempt)" in script_boundary
        assert "runAttempt !== 1" in script_boundary


def _compatibility_normalizer_script(workflow_name: str, job_name: str) -> str:
    workflow = _read(f".github/workflows/{workflow_name}")
    next_job = "node-compat"
    job = workflow.split(f"  {job_name}:", 1)[1].split(f"  {next_job}:", 1)[0]
    step = job.split("      - name: Normalize compatibility receipt", 1)[1].split(
        "\n      - name:", 1
    )[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    (
        ("kaji.rehearsal.yml", "python-compat"),
        ("kaji.publish.yml", "python-compat"),
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
                "LOOKUP_OUTCOME": "success",
                "DOWNLOAD_OUTCOME": "success",
                "VERIFICATION_OUTCOME": "success",
                "SMOKE_OUTCOME": "success",
                "STAGE_OUTCOME": "success",
            },
            text=True,
        )
        return completed, json.loads(path.read_text())

    proof = _github_package_proof("typescript")
    matching: dict[str, object] = {
        "schemaVersion": 1,
        "commit": commit,
        "releaseManifestSha256": "b" * 64,
        "artifactSha256": {"irogane-kaji-0.2.0-beta.11.tgz": "c" * 64},
        "runtime": {"version": "v22.1.0"},
        "artifacts": {
            "tarball": "/artifacts/irogane-kaji-0.2.0-beta.11.tgz",
            "package": "/tmp/node_modules/@irogane/kaji",
        },
        "githubPackageProofs": {
            "npm": proof,
            "bun": json.loads(json.dumps(proof)),
        },
        "timings": {
            "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
            "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
        },
        "toolchain": {
            "python": "not-used",
            "uv": "not-used",
            "node": "v22.1.0",
            "npm": "11.4.2",
            "bun": "1.3.11",
            "typescript": "5.7.3 and 6.0.2",
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
        ("kaji.publish.yml", "python-compat", "python", "3.14"),
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
        "LOOKUP_OUTCOME": "success",
        "STAGE_OUTCOME": "success",
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
                "kaji-0.2.0b1-py3-none-any.whl": "c" * 64,
                "kaji-0.2.0b1.tar.gz": "d" * 64,
            },
            "runtime": {
                "implementation": "CPython",
                "version": f"{runtime_version}.9",
                "executable": "/opt/python/bin/python",
            },
            "artifacts": {
                "wheel": "/artifacts/kaji-0.2.0b1-py3-none-any.whl",
                "sdist": "/artifacts/kaji-0.2.0b1.tar.gz",
            },
            "githubPackageProofs": {
                "wheel": _github_package_proof("python"),
                "sdist": _github_package_proof("python"),
            },
            "timings": {
                "wheel": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                "sdist": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
            },
            "toolchain": {
                "python": f"{runtime_version}.9",
                "uv": "0.11.25",
                "node": "not-used",
                "npm": "not-used",
                "bun": "not-used",
                "typescript": "not-used",
            },
        }
    else:
        passed = {
            **identity_free_passed,
            "releaseManifestSha256": "b" * 64,
            "artifactSha256": {"irogane-kaji-0.2.0-beta.11.tgz": "c" * 64},
            "runtime": {"version": f"v{runtime_version}.1.0"},
            "artifacts": {
                "tarball": "/artifacts/irogane-kaji-0.2.0-beta.11.tgz",
                "package": "/tmp/node_modules/@irogane/kaji",
            },
            "githubPackageProofs": {
                "npm": _github_package_proof("typescript"),
                "bun": _github_package_proof("typescript"),
            },
            "timings": {
                "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
                "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
            },
            "toolchain": {
                "python": "not-used",
                "uv": "not-used",
                "node": f"v{runtime_version}.1.0",
                "npm": "11.4.2",
                "bun": "1.3.11",
                "typescript": "5.7.3 and 6.0.2",
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
        for label, field, value in (
            ("wrong-toolchain-node", "node", "v99.0.0"),
            ("wrong-toolchain-npm", "npm", "latest"),
            ("wrong-toolchain-bun", "bun", "1.3.12"),
            ("wrong-toolchain-typescript", "typescript", "5.7.3 and 6.0.3"),
        ):
            invalid_toolchain = json.loads(json.dumps(passed))
            invalid_toolchain["toolchain"][field] = value
            rejected, rejected_receipt, _ = run_case(
                label,
                receipt=invalid_toolchain,
                outcomes=all_success,
            )
            assert rejected.returncode != 0
            assert rejected_receipt["conclusion"] == "not_run"
            assert (
                rejected_receipt["failureCode"] == "compatibility_receipt_not_terminal"
            )

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


def _release_evidence_fixture(
    tmp_path: Path,
    *,
    workflow_run_id: int = 123,
    release_artifact_id_value: int = 456,
) -> SimpleNamespace:
    commit = "a" * 40
    workflow_run = f"https://github.com/enkyuan/alloy/actions/runs/{workflow_run_id}"
    workflow_run_attempt = 1
    release_artifact_id = str(release_artifact_id_value)
    release_artifact_digest = "b" * 64
    artifacts_dir = tmp_path / "release"
    artifacts_dir.mkdir()
    payloads = {
        "kaji-0.2.0b1-py3-none-any.whl": b"wheel",
        "kaji-0.2.0b1.tar.gz": b"sdist",
        "irogane-kaji-0.2.0-beta.11.tgz": b"npm",
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
                "version": ("0.2.0-beta.11" if package == "typescript" else "0.2.0b1"),
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
            "file": "kaji/packages/py/build-requirements.txt",
            "sha256": hashlib.sha256(
                (REPO_ROOT / "kaji/packages/py/build-requirements.txt").read_bytes()
            ).hexdigest(),
        },
        "packages": {
            "contract": "1.0.0",
            "python": "0.2.0b1",
            "typescript": "0.2.0-beta.11",
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
            "file": "kaji-0.2.0b1-py3-none-any.whl",
            "sha256": artifact_hashes["kaji-0.2.0b1-py3-none-any.whl"],
        },
        "typescript": {
            "file": "irogane-kaji-0.2.0-beta.11.tgz",
            "sha256": artifact_hashes["irogane-kaji-0.2.0-beta.11.tgz"],
        },
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider_packages = {
        "python": "/opt/kaji-installed-release-provider/python/lib/python3.11/site-packages/kaji/__init__.py",
        "typescript": "/opt/kaji-installed-release-provider/typescript/node_modules/@irogane/kaji",
    }
    soak_packages = {
        "python": "/opt/kaji-installed-release-soak/python/lib/python3.11/site-packages/kaji/__init__.py",
        "typescript": "/opt/kaji-installed-release-soak/typescript/node_modules/@irogane/kaji",
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
                        "kaji-0.2.0b1-py3-none-any.whl",
                        "kaji-0.2.0b1.tar.gz",
                    )
                },
                "runtime": {
                    "implementation": "CPython",
                    "version": f"{version}.9",
                    "executable": f"/opt/python/{version}/bin/python",
                },
                "artifacts": {
                    "wheel": "/artifacts/kaji-0.2.0b1-py3-none-any.whl",
                    "sdist": "/artifacts/kaji-0.2.0b1.tar.gz",
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
                "toolchain": {
                    "python": f"{version}.9",
                    "uv": "0.11.25",
                    "node": "not-used",
                    "npm": "not-used",
                    "bun": "not-used",
                    "typescript": "not-used",
                },
                **run_identity,
            },
        )
    for version in ("22", "24"):
        node_receipt = _load_test_support(
            "test_compatibility_receipts.py"
        ).node_v2_receipt(
            int(version),
            commit=commit,
            manifest_sha256=manifest_hash,
            tarball_sha256=artifact_hashes["irogane-kaji-0.2.0-beta.11.tgz"],
            tarball_size=len(payloads["irogane-kaji-0.2.0-beta.11.tgz"]),
            workflow_run=workflow_run,
            workflow_run_attempt=workflow_run_attempt,
            producer_artifact_id=int(release_artifact_id),
            producer_artifact_digest=f"sha256:{release_artifact_digest}",
        )
        node_receipt["artifacts"]["package"] = (
            f"/opt/kaji-node-{version}/node_modules/@irogane/kaji"
        )
        _write_release_evidence_json(
            paths[f"compat-node-{version}"],
            node_receipt,
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
            "file": "kaji-0.2.0b1.tar.gz",
            "sha256": artifact_hashes["kaji-0.2.0b1.tar.gz"],
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
        "dependencyLockHash": pair._lock_hash(),
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
                "runId": workflow_run_id,
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
        "kind": "kaji-paired-benchmark-aggregate",
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
            "kind": "kaji-performance-status",
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


def _command_argument(command: list[str], option: str) -> str:
    return command[command.index(option) + 1]


def _replace_command_argument(
    command: list[str],
    option: str,
    value: str,
) -> None:
    command[command.index(option) + 1] = value


def _remove_command_argument(command: list[str], option: str) -> None:
    index = command.index(option)
    del command[index : index + 2]


def _archive_native_release_evidence_fixture(
    tmp_path: Path,
    *,
    mode: str = "rehearsal",
    workflow_run_id: int = 123,
    producer_artifact_id: int = 456,
    node_source_ids: dict[int, int] | None = None,
) -> SimpleNamespace:
    fixture = _release_evidence_fixture(
        tmp_path,
        workflow_run_id=workflow_run_id,
        release_artifact_id_value=producer_artifact_id,
    )
    command = list(fixture.command)
    commit = _command_argument(command, "--expected-commit")
    workflow_run = _command_argument(command, "--workflow-run")
    run_id = int(workflow_run.rsplit("/", 1)[1])
    run_attempt = int(_command_argument(command, "--workflow-run-attempt"))
    producer_id = int(_command_argument(command, "--release-artifact-id"))
    artifacts_dir = Path(_command_argument(command, "--artifacts-dir"))
    workflow_ref = {
        "rehearsal": (
            "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
        ),
        "publish": (
            "enkyuan/alloy/.github/workflows/"
            "kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.11"
        ),
    }[mode]

    onboarding = _load_root_script("validate_typescript_onboarding_evidence.py")
    onboarding_support = _load_test_support("test_typescript_onboarding_evidence.py")
    producer_members = {
        path.name: path.read_bytes()
        for path in artifacts_dir.iterdir()
        if path.is_file()
    }
    producer_bytes = onboarding_support._zip_bytes(producer_members)
    producer_archive = tmp_path / "archives/kaji-artifacts.zip"
    producer_archive.parent.mkdir(parents=True)
    producer_archive.write_bytes(producer_bytes)
    producer_digest = "sha256:" + hashlib.sha256(producer_bytes).hexdigest()

    source_ids = node_source_ids or {22: 2201, 24: 2401}
    source_archives: dict[int, Path] = {}
    source_digests: dict[int, str] = {}
    for major in (22, 24):
        receipt_path = fixture.paths[f"compat-node-{major}"]
        receipt = json.loads(receipt_path.read_text())
        receipt["producerArtifact"]["digest"] = producer_digest
        receipt["producerArtifact"]["runId"] = run_id
        receipt["invocation"]["runId"] = run_id
        receipt["invocation"]["workflowRef"] = workflow_ref
        receipt_bytes = json.dumps(receipt, sort_keys=True).encode()
        receipt_path.write_bytes(receipt_bytes)
        archive_bytes = onboarding_support._zip_bytes(
            {"compatibility-receipt.json": receipt_bytes}
        )
        archive_path = tmp_path / f"archives/kaji-node-compat-{major}.zip"
        archive_path.write_bytes(archive_bytes)
        source_archives[major] = archive_path
        source_digests[major] = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()

    loaded_producer = onboarding.load_authenticated_archive(
        producer_archive,
        name="kaji-artifacts",
        artifact_id=producer_id,
        digest=producer_digest,
        run_id=run_id,
        run_attempt=run_attempt,
        head_sha=commit,
        expired=False,
    )
    loaded_sources = {
        major: onboarding.load_authenticated_archive(
            source_archives[major],
            name=f"kaji-node-compat-{major}",
            artifact_id=source_ids[major],
            digest=source_digests[major],
            run_id=run_id,
            run_attempt=run_attempt,
            head_sha=commit,
            expired=False,
        )
        for major in (22, 24)
    }
    aggregate = onboarding.compose_document(
        producer_archive=loaded_producer,
        node22_archive=loaded_sources[22],
        node24_archive=loaded_sources[24],
        expected_workflow_run=workflow_run,
        expected_workflow_ref=workflow_ref,
        expected_workflow_sha=commit,
    )
    aggregate_bytes = json.dumps(aggregate, indent=2, sort_keys=True).encode()
    onboarding_evidence = (
        tmp_path / "evidence/typescript-onboarding/typescript-onboarding-evidence.json"
    )
    onboarding_evidence.parent.mkdir(parents=True)
    onboarding_evidence.write_bytes(aggregate_bytes)
    onboarding_status = onboarding_evidence.with_name("status.json")
    _write_release_evidence_json(
        onboarding_status,
        {
            "schemaVersion": 1,
            "kind": "kaji-typescript-onboarding-status",
            "commit": commit,
            "workflowRun": workflow_run,
            "workflowRunAttempt": 1,
            "workflowRef": workflow_ref,
            "releaseManifestSha256": fixture.manifest_hash,
            "aggregateSha256": hashlib.sha256(aggregate_bytes).hexdigest(),
            "conclusion": "passed",
            "failureCode": None,
            "exitCode": 0,
        },
    )

    bare_producer_digest = producer_digest.removeprefix("sha256:")
    for label in ("performance-status", "provider-evidence"):
        document = json.loads(fixture.paths[label].read_text())
        document["releaseArtifactDigest"] = bare_producer_digest
        _write_release_evidence_json(fixture.paths[label], document)

    _replace_command_argument(command, "--release-artifact-digest", producer_digest)
    command.extend(
        [
            "--mode",
            mode,
            "--producer-archive",
            str(producer_archive),
            "--node22-source-archive",
            str(source_archives[22]),
            "--node24-source-archive",
            str(source_archives[24]),
            "--onboarding-status",
            str(onboarding_status),
            "--onboarding-evidence",
            str(onboarding_evidence),
            "--node22-source-artifact-id",
            str(source_ids[22]),
            "--node22-source-artifact-digest",
            source_digests[22],
            "--node24-source-artifact-id",
            str(source_ids[24]),
            "--node24-source-artifact-digest",
            source_digests[24],
        ]
    )
    signed_paths: dict[str, Path] = {}
    authorization_sha256: str | None = None
    signed_rehearsal: SimpleNamespace | None = None
    if mode == "publish":
        signed_rehearsal = _signed_rehearsal_evidence_fixture(
            tmp_path / "signed-source",
            workflow_run_id=987,
            producer_artifact_id=1456,
            node_source_ids={22: 32201, 24: 32401},
            evidence_artifact_id=1789,
        )
        signed_candidate = tmp_path / "signed/kaji-artifacts.zip"
        signed_evidence = tmp_path / "signed/kaji-release-candidate-evidence.zip"
        signed_npm = tmp_path / "signed/irogane-kaji-0.2.0-beta.11.tgz"
        rebuilt_npm = tmp_path / "rebuilt/irogane-kaji-0.2.0-beta.11.tgz"
        signed_candidate.parent.mkdir(parents=True)
        rebuilt_npm.parent.mkdir(parents=True)
        signed_candidate.write_bytes(
            signed_rehearsal.release.producer_archive.read_bytes()
        )
        signed_evidence_bytes = signed_rehearsal.archive.read_bytes()
        signed_evidence.write_bytes(signed_evidence_bytes)
        signed_artifacts_dir = Path(
            _command_argument(
                signed_rehearsal.release.command,
                "--artifacts-dir",
            )
        )
        npm_bytes = (
            signed_artifacts_dir / "irogane-kaji-0.2.0-beta.11.tgz"
        ).read_bytes()
        signed_npm.write_bytes(npm_bytes)
        rebuilt_npm.write_bytes(npm_bytes)
        signed_evidence_digest = (
            "sha256:" + hashlib.sha256(signed_evidence_bytes).hexdigest()
        )
        signed_npm_sha256 = hashlib.sha256(npm_bytes).hexdigest()
        authorization = {
            "schemaVersion": "1.0.0",
            "commit": commit,
            "rehearsal": {
                "runId": 987,
                "runAttempt": 1,
                "workflowPath": ".github/workflows/kaji.rehearsal.yml",
                "workflowSha": commit,
            },
            "candidateArtifact": {
                "id": 1456,
                "name": "kaji-artifacts",
                "digest": signed_rehearsal.release.producer_digest,
            },
            "evidenceArtifact": {
                "id": 1789,
                "name": "kaji-release-candidate-evidence",
                "digest": signed_evidence_digest,
            },
            "releaseManifestSha256": signed_rehearsal.release.manifest_hash,
            "npmTarball": {
                "name": "irogane-kaji-0.2.0-beta.11.tgz",
                "sha256": signed_npm_sha256,
            },
        }
        authorization_sha256 = hashlib.sha256(
            (
                json.dumps(
                    authorization,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("ascii")
        ).hexdigest()
        command.extend(
            [
                "--authorization-sha256",
                authorization_sha256,
                "--rehearsal-run-id",
                "987",
                "--rehearsal-run-attempt",
                "1",
                "--rehearsal-workflow-path",
                ".github/workflows/kaji.rehearsal.yml",
                "--rehearsal-workflow-sha",
                commit,
                "--signed-candidate-archive",
                str(signed_candidate),
                "--signed-candidate-artifact-id",
                "1456",
                "--signed-candidate-artifact-digest",
                signed_rehearsal.release.producer_digest,
                "--signed-evidence-archive",
                str(signed_evidence),
                "--signed-evidence-artifact-id",
                "1789",
                "--signed-evidence-artifact-digest",
                signed_evidence_digest,
                "--signed-node22-source-artifact-id",
                "32201",
                "--signed-node22-source-artifact-digest",
                signed_rehearsal.release.source_digests[22],
                "--signed-node24-source-artifact-id",
                "32401",
                "--signed-node24-source-artifact-digest",
                signed_rehearsal.release.source_digests[24],
                "--signed-release-manifest-sha256",
                signed_rehearsal.release.manifest_hash,
                "--signed-npm-tarball-name",
                "irogane-kaji-0.2.0-beta.11.tgz",
                "--signed-npm-tarball-sha256",
                signed_npm_sha256,
                "--signed-npm-tarball",
                str(signed_npm),
                "--rebuilt-npm-tarball",
                str(rebuilt_npm),
            ]
        )
        signed_paths = {
            "signed-candidate-archive": signed_candidate,
            "signed-evidence-archive": signed_evidence,
            "signed-npm-tarball": signed_npm,
            "rebuilt-npm-tarball": rebuilt_npm,
        }
    paths = dict(fixture.paths)
    paths.update(
        {
            "onboarding-status": onboarding_status,
            "onboarding-evidence": onboarding_evidence,
            "producer-archive": producer_archive,
            "node22-source-archive": source_archives[22],
            "node24-source-archive": source_archives[24],
        }
    )
    return SimpleNamespace(
        **{
            key: value
            for key, value in vars(fixture).items()
            if key not in {"command", "paths"}
        },
        command=command,
        paths=paths,
        mode=mode,
        workflow_ref=workflow_ref,
        producer_archive=producer_archive,
        producer_digest=producer_digest,
        source_archives=source_archives,
        source_digests=source_digests,
        source_ids=source_ids,
        aggregate=aggregate,
        onboarding_status=onboarding_status,
        onboarding_evidence=onboarding_evidence,
        signed_paths=signed_paths,
        authorization_sha256=authorization_sha256,
        signed_rehearsal=signed_rehearsal,
    )


SIGNED_REHEARSAL_EVIDENCE_MEMBERS = {
    "compat-node-22.json",
    "compat-node-24.json",
    "compat-python-3.11.json",
    "compat-python-3.14.json",
    "offline-gate-summary.json",
    "offline-gates.log",
    "paired-benchmark-results.json",
    "performance-imagedata.json",
    "performance-status.json",
    "provider-evidence.json",
    "raw/benchmarks/replica-1-imagedata.json",
    "raw/benchmarks/replica-1.json",
    "raw/benchmarks/replica-2-imagedata.json",
    "raw/benchmarks/replica-2.json",
    "raw/benchmarks/replica-3-imagedata.json",
    "raw/benchmarks/replica-3.json",
    "raw/soak/python.json",
    "raw/soak/results.json",
    "raw/soak/typescript.json",
    "release-evidence-validation.json",
    "soak-results.json",
    "typescript-onboarding/status.json",
    "typescript-onboarding/typescript-onboarding-evidence.json",
    "typescript-onboarding/validation.log",
}


def _signed_rehearsal_evidence_members(
    fixture: SimpleNamespace,
) -> dict[str, bytes]:
    benchmark_root = fixture.paths["benchmark-results"].parent
    return {
        "compat-node-22.json": fixture.paths["compat-node-22"].read_bytes(),
        "compat-node-24.json": fixture.paths["compat-node-24"].read_bytes(),
        "compat-python-3.11.json": fixture.paths["compat-python-3.11"].read_bytes(),
        "compat-python-3.14.json": fixture.paths["compat-python-3.14"].read_bytes(),
        "offline-gate-summary.json": b'{"conclusion":"passed"}\n',
        "offline-gates.log": b"offline gates passed\n",
        "paired-benchmark-results.json": fixture.paths[
            "benchmark-results"
        ].read_bytes(),
        "performance-imagedata.json": fixture.paths[
            "performance-image-data"
        ].read_bytes(),
        "performance-status.json": fixture.paths["performance-status"].read_bytes(),
        "provider-evidence.json": fixture.paths["provider-evidence"].read_bytes(),
        **{
            f"raw/benchmarks/replica-{replica}.json": (
                benchmark_root / f"raw/benchmarks/replica-{replica}.json"
            ).read_bytes()
            for replica in ("1", "2", "3")
        },
        **{
            f"raw/benchmarks/replica-{replica}-imagedata.json": (
                benchmark_root / f"raw/benchmarks/replica-{replica}-imagedata.json"
            ).read_bytes()
            for replica in ("1", "2", "3")
        },
        "raw/soak/python.json": b'{"runtime":"python"}\n',
        "raw/soak/results.json": fixture.paths["soak-results"].read_bytes(),
        "raw/soak/typescript.json": b'{"runtime":"typescript"}\n',
        "release-evidence-validation.json": fixture.output.read_bytes(),
        "soak-results.json": fixture.paths["soak-results"].read_bytes(),
        "typescript-onboarding/status.json": fixture.onboarding_status.read_bytes(),
        "typescript-onboarding/typescript-onboarding-evidence.json": (
            fixture.onboarding_evidence.read_bytes()
        ),
        "typescript-onboarding/validation.log": b"onboarding passed\n",
    }


def _signed_rehearsal_evidence_fixture(
    tmp_path: Path,
    *,
    workflow_run_id: int = 123,
    producer_artifact_id: int = 456,
    node_source_ids: dict[int, int] | None = None,
    evidence_artifact_id: int = 1789,
) -> SimpleNamespace:
    tmp_path.mkdir(parents=True)
    fixture = _archive_native_release_evidence_fixture(
        tmp_path,
        workflow_run_id=workflow_run_id,
        producer_artifact_id=producer_artifact_id,
        node_source_ids=node_source_ids,
    )
    completed, summary = _run_release_evidence(fixture)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert summary["conclusion"] == "passed"
    members = _signed_rehearsal_evidence_members(fixture)
    assert set(members) == SIGNED_REHEARSAL_EVIDENCE_MEMBERS
    support = _load_test_support("test_typescript_onboarding_evidence.py")
    archive_bytes = support._zip_bytes(members)
    archive = tmp_path / "signed-rehearsal-evidence.zip"
    archive.write_bytes(archive_bytes)
    return SimpleNamespace(
        release=fixture,
        members=members,
        archive=archive,
        artifact_id=evidence_artifact_id,
        digest="sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
    )


def _attach_signed_rehearsal_evidence(
    fixture: SimpleNamespace,
    signed: SimpleNamespace,
) -> None:
    fixture.command.extend(
        [
            "--signed-evidence-archive",
            str(signed.archive),
            "--signed-evidence-artifact-id",
            str(signed.artifact_id),
            "--signed-evidence-artifact-digest",
            signed.digest,
        ]
    )
    for option in (
        "--onboarding-status",
        "--onboarding-evidence",
        "--python-compat-311",
        "--python-compat-314",
        "--node-compat-22",
        "--node-compat-24",
        "--performance-status",
        "--benchmark-results",
        "--soak-results",
        "--performance-image-data",
        "--provider-evidence",
    ):
        _remove_command_argument(fixture.command, option)


def test_release_evidence_cli_is_archive_native_and_mode_closed() -> None:
    source = _read("kaji/scripts/validate_release_evidence.py")
    help_result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "kaji/scripts/validate_release_evidence.py"),
            "--help",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert help_result.returncode == 0
    for option in (
        "--mode",
        "--producer-archive",
        "--node22-source-archive",
        "--node24-source-archive",
        "--onboarding-status",
        "--onboarding-evidence",
        "--node22-source-artifact-id",
        "--node22-source-artifact-digest",
        "--node24-source-artifact-id",
        "--node24-source-artifact-digest",
        "--authorization-sha256",
        "--signed-candidate-archive",
        "--signed-evidence-archive",
        "--signed-node22-source-artifact-id",
        "--signed-node22-source-artifact-digest",
        "--signed-node24-source-artifact-id",
        "--signed-node24-source-artifact-digest",
        "--signed-npm-tarball",
        "--rebuilt-npm-tarball",
    ):
        assert option in help_result.stdout
    for obsolete in (
        "--tthw-status",
        "--tthw-evidence",
        "validate_tthw_evidence",
        "validate_legacy_node_release_bindings",
    ):
        assert obsolete not in help_result.stdout
        assert obsolete not in source


@pytest.mark.parametrize(
    ("option", "value", "expected_code"),
    (
        ("--expected-commit", "A" * 40, "expected_commit_invalid"),
        (
            "--workflow-run",
            "http://github.com/enkyuan/alloy/actions/runs/123",
            "workflow_run_invalid",
        ),
        (
            "--workflow-run",
            "https://github.com/enkyuan/alloy/actions/runs/9007199254740992",
            "workflow_run_invalid",
        ),
        ("--workflow-run-attempt", "2", "workflow_run_attempt_invalid"),
        ("--release-artifact-id", "0", "release_artifact_id_invalid"),
        (
            "--release-artifact-id",
            "9007199254740992",
            "release_artifact_id_invalid",
        ),
        (
            "--release-artifact-digest",
            "0" * 64,
            "release_artifact_digest_invalid",
        ),
        (
            "--node22-source-artifact-digest",
            "sha256:" + "A" * 64,
            "node22_source_artifact_digest_invalid",
        ),
        (
            "--node24-source-artifact-id",
            "0224",
            "node24_source_artifact_id_invalid",
        ),
    ),
)
def test_release_evidence_invocation_grammar_is_canonical(
    tmp_path: Path,
    option: str,
    value: str,
    expected_code: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    command = list(fixture.command)
    _replace_command_argument(command, option, value)
    args = module.parse_args(command[2:])

    assert {
        "evidence": "invocation",
        "code": expected_code,
    } in module.invocation_failures(args)


def test_signed_rehearsal_invocation_requires_pairwise_distinct_artifact_ids(
    tmp_path: Path,
) -> None:
    signed = _signed_rehearsal_evidence_fixture(tmp_path / "source")
    fixture = signed.release
    _attach_signed_rehearsal_evidence(fixture, signed)
    module = _load_root_script("validate_release_evidence.py")
    _replace_command_argument(
        fixture.command,
        "--signed-evidence-artifact-id",
        _command_argument(fixture.command, "--release-artifact-id"),
    )

    failures = module.invocation_failures(module.parse_args(fixture.command[2:]))

    assert {
        "evidence": "invocation",
        "code": "artifact_ids_not_distinct",
    } in failures


def test_publish_invocation_requires_all_ids_and_run_ids_distinct(
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path, mode="publish")
    module = _load_root_script("validate_release_evidence.py")
    base_args = module.parse_args(fixture.command[2:])
    assert module.invocation_failures(base_args) == []
    artifact_options = (
        "--release-artifact-id",
        "--node22-source-artifact-id",
        "--node24-source-artifact-id",
        "--signed-candidate-artifact-id",
        "--signed-evidence-artifact-id",
        "--signed-node22-source-artifact-id",
        "--signed-node24-source-artifact-id",
    )
    assert (
        len({_command_argument(fixture.command, option) for option in artifact_options})
        == 7
    )

    duplicate_command = list(fixture.command)
    _replace_command_argument(
        duplicate_command,
        "--signed-node22-source-artifact-id",
        _command_argument(duplicate_command, "--release-artifact-id"),
    )
    duplicate_failures = module.invocation_failures(
        module.parse_args(duplicate_command[2:])
    )
    assert {
        "evidence": "invocation",
        "code": "artifact_ids_not_distinct",
    } in duplicate_failures

    repeated_run_command = list(fixture.command)
    _replace_command_argument(
        repeated_run_command,
        "--rehearsal-run-id",
        _command_argument(repeated_run_command, "--workflow-run").rsplit("/", 1)[1],
    )
    repeated_run_failures = module.invocation_failures(
        module.parse_args(repeated_run_command[2:])
    )
    assert {
        "evidence": "invocation",
        "code": "rehearsal_run_not_distinct",
    } in repeated_run_failures


def test_release_evidence_validator_accepts_archive_native_rehearsal(
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)

    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(fixture.output.read_text())
    assert summary["schemaVersion"] == 2
    assert summary["mode"] == "rehearsal"
    assert summary["workflowRef"] == fixture.workflow_ref
    assert summary["conclusion"] == "passed"
    assert summary["failureCode"] is None
    assert summary["failures"] == []
    assert summary["onboardingEvidence"] == {
        "aggregateSha256": hashlib.sha256(
            fixture.onboarding_evidence.read_bytes()
        ).hexdigest(),
        "recomputedAggregateSha256": hashlib.sha256(
            fixture.onboarding_evidence.read_bytes()
        ).hexdigest(),
        "nodeReceiptSha256": {
            "22": hashlib.sha256(
                fixture.paths["compat-node-22"].read_bytes()
            ).hexdigest(),
            "24": hashlib.sha256(
                fixture.paths["compat-node-24"].read_bytes()
            ).hexdigest(),
        },
        "releaseManifestSha256": fixture.manifest_hash,
        "statusSha256": hashlib.sha256(
            fixture.onboarding_status.read_bytes()
        ).hexdigest(),
    }
    assert summary["signedSource"] is None


def test_release_evidence_revalidates_signed_rehearsal_archive_without_extraction(
    tmp_path: Path,
) -> None:
    signed = _signed_rehearsal_evidence_fixture(tmp_path / "source")
    fixture = signed.release
    _attach_signed_rehearsal_evidence(fixture, signed)

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert summary["conclusion"] == "passed"
    assert summary["signedSource"] is None
    assert signed.members["release-evidence-validation.json"].endswith(b"\n")
    assert not signed.members["release-evidence-validation.json"].endswith(b"\n\n")
    assert (
        fixture.output.read_bytes()
        == signed.members["release-evidence-validation.json"]
    )


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("empty_summary", "signed_evidence_summary_invalid"),
        ("tampered_member", "signed_evidence_summary_mismatch"),
        ("missing_member", "signed_evidence_archive_invalid"),
        ("extra_member", "signed_evidence_archive_invalid"),
        ("traversal", "signed_evidence_archive_invalid"),
        ("symlink", "signed_evidence_archive_invalid"),
        ("duplicate", "signed_evidence_archive_invalid"),
        ("prefix", "signed_evidence_archive_invalid"),
        ("trailing", "signed_evidence_archive_invalid"),
        ("zip64", "signed_evidence_archive_invalid"),
        ("comment", "signed_evidence_archive_invalid"),
        ("encryption", "signed_evidence_archive_invalid"),
        ("unsupported_compression", "signed_evidence_archive_invalid"),
        ("compression_ratio", "signed_evidence_archive_invalid"),
    ),
)
def test_release_evidence_rejects_hostile_signed_rehearsal_archive(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    signed = _signed_rehearsal_evidence_fixture(tmp_path / "source")
    fixture = signed.release
    members = dict(signed.members)
    support = _load_test_support("test_typescript_onboarding_evidence.py")
    modes: dict[str, int] | None = None
    comment = b"x" if hostile_case == "comment" else b""
    if hostile_case == "empty_summary":
        members["release-evidence-validation.json"] = b"{}\n"
    elif hostile_case == "tampered_member":
        members["compat-python-3.11.json"] += b" "
    elif hostile_case == "missing_member":
        del members["provider-evidence.json"]
    elif hostile_case == "extra_member":
        members["unreviewed.json"] = b"{}\n"
    elif hostile_case == "traversal":
        members["../provider-evidence.json"] = members.pop("provider-evidence.json")
    elif hostile_case == "symlink":
        modes = {"release-evidence-validation.json": 0o120777}
    elif hostile_case == "compression_ratio":
        members["offline-gates.log"] = b"x" * (1024 * 1024)

    if hostile_case == "duplicate":
        output = BytesIO()
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=False,
        ) as archive:
            for name, encoded in members.items():
                archive.writestr(name, encoded)
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(
                    "provider-evidence.json",
                    members["provider-evidence.json"],
                )
        archive_bytes = output.getvalue()
    else:
        archive_bytes = support._zip_bytes(members, modes=modes, comment=comment)
    if hostile_case == "prefix":
        archive_bytes = b"x" + archive_bytes
    elif hostile_case == "trailing":
        archive_bytes += b"x"
    elif hostile_case == "zip64":
        mutated_archive = bytearray(archive_bytes)
        struct.pack_into(
            "<L",
            mutated_archive,
            len(mutated_archive) - 22 + 12,
            0xFFFFFFFF,
        )
        archive_bytes = bytes(mutated_archive)
    elif hostile_case in {"encryption", "unsupported_compression"}:
        mutated_archive = bytearray(archive_bytes)
        with zipfile.ZipFile(BytesIO(archive_bytes)) as opened:
            local_offset = opened.infolist()[0].header_offset
        central_offset = struct.unpack_from(
            "<L",
            archive_bytes,
            len(archive_bytes) - 22 + 16,
        )[0]
        if hostile_case == "encryption":
            local_flags = struct.unpack_from(
                "<H",
                archive_bytes,
                local_offset + 6,
            )[0]
            central_flags = struct.unpack_from(
                "<H",
                archive_bytes,
                central_offset + 8,
            )[0]
            struct.pack_into(
                "<H",
                mutated_archive,
                local_offset + 6,
                local_flags | 0x1,
            )
            struct.pack_into(
                "<H",
                mutated_archive,
                central_offset + 8,
                central_flags | 0x1,
            )
        else:
            struct.pack_into("<H", mutated_archive, local_offset + 8, 99)
            struct.pack_into("<H", mutated_archive, central_offset + 10, 99)
        archive_bytes = bytes(mutated_archive)
    signed.archive.write_bytes(archive_bytes)
    signed.digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    _attach_signed_rehearsal_evidence(fixture, signed)

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert expected_code in {
        failure["code"] for failure in cast(list[dict[str, str]], summary["failures"])
    }
    assert summary["onboardingEvidence"] is None
    assert summary["signedSource"] is None


def test_release_evidence_validator_accepts_signed_publish_source(
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path, mode="publish")

    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(fixture.output.read_text())
    assert summary["schemaVersion"] == 2
    assert summary["mode"] == "publish"
    assert summary["workflowRef"] == fixture.workflow_ref
    assert summary["conclusion"] == "passed"
    assert summary["signedSource"] == {
        "authorizationSha256": fixture.authorization_sha256,
        "rehearsal": {
            "runId": 987,
            "runAttempt": 1,
            "workflowPath": ".github/workflows/kaji.rehearsal.yml",
            "workflowSha": "a" * 40,
        },
        "candidateArtifact": {
            "id": 1456,
            "name": "kaji-artifacts",
            "digest": fixture.producer_digest,
        },
        "evidenceArtifact": {
            "id": 1789,
            "name": "kaji-release-candidate-evidence",
            "digest": "sha256:"
            + hashlib.sha256(
                fixture.signed_paths["signed-evidence-archive"].read_bytes()
            ).hexdigest(),
        },
        "releaseManifestSha256": fixture.manifest_hash,
        "npmTarball": {
            "name": "irogane-kaji-0.2.0-beta.11.tgz",
            "sha256": fixture.artifact_hashes["irogane-kaji-0.2.0-beta.11.tgz"],
        },
        "sourceRebuildCarrierEqual": True,
    }


def test_release_evidence_rehearsal_rejects_partial_or_mixed_signed_source_options(
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    signed_options = {
        "--authorization-sha256": "c" * 64,
        "--rehearsal-run-id": "987",
        "--rehearsal-run-attempt": "1",
        "--rehearsal-workflow-path": ".github/workflows/kaji.rehearsal.yml",
        "--rehearsal-workflow-sha": "a" * 40,
        "--signed-candidate-archive": str(fixture.producer_archive),
        "--signed-candidate-artifact-id": "1456",
        "--signed-candidate-artifact-digest": fixture.producer_digest,
        "--signed-evidence-archive": str(fixture.producer_archive),
        "--signed-evidence-artifact-id": "1789",
        "--signed-evidence-artifact-digest": fixture.producer_digest,
        "--signed-release-manifest-sha256": fixture.manifest_hash,
        "--signed-npm-tarball-name": "irogane-kaji-0.2.0-beta.11.tgz",
        "--signed-npm-tarball-sha256": fixture.artifact_hashes[
            "irogane-kaji-0.2.0-beta.11.tgz"
        ],
        "--signed-npm-tarball": str(
            Path(_command_argument(fixture.command, "--artifacts-dir"))
            / "irogane-kaji-0.2.0-beta.11.tgz"
        ),
        "--rebuilt-npm-tarball": str(
            Path(_command_argument(fixture.command, "--artifacts-dir"))
            / "irogane-kaji-0.2.0-beta.11.tgz"
        ),
    }
    for option, value in signed_options.items():
        args = module.parse_args([*fixture.command[2:], option, value])
        assert {
            "evidence": "invocation",
            "code": "signed_arguments_forbidden_in_rehearsal",
        } in module.invocation_failures(args), option

    fixture.command.extend(["--authorization-sha256", "c" * 64])

    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    summary = json.loads(fixture.output.read_text())
    assert {
        "evidence": "invocation",
        "code": "signed_arguments_forbidden_in_rehearsal",
    } in summary["failures"]
    assert summary["onboardingEvidence"] is None
    assert summary["signedSource"] is None


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("missing_argument", "signed_arguments_required"),
        ("authorization", "authorization_sha256_invalid"),
        ("rehearsal_run", "rehearsal_run_id_invalid"),
        ("rehearsal_attempt", "rehearsal_run_attempt_invalid"),
        ("rehearsal_path", "rehearsal_workflow_path_invalid"),
        ("rehearsal_sha", "rehearsal_workflow_sha_invalid"),
        ("candidate_id", "authorization_digest_mismatch"),
        ("evidence_id", "authorization_digest_mismatch"),
        ("candidate_archive", "signed_candidate_invalid"),
        ("candidate_digest", "authorization_digest_mismatch"),
        ("evidence_archive", "signed_evidence_digest_mismatch"),
        ("signed_manifest", "authorization_digest_mismatch"),
        ("signed_npm_hash", "authorization_digest_mismatch"),
        ("signed_npm", "signed_npm_hash_mismatch"),
        ("rebuilt_npm", "rebuilt_npm_mismatch"),
    ),
)
def test_release_evidence_publish_rejects_signed_tuple_drift(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path, mode="publish")
    if hostile_case == "missing_argument":
        _remove_command_argument(fixture.command, "--authorization-sha256")
    elif hostile_case == "authorization":
        _replace_command_argument(fixture.command, "--authorization-sha256", "C" * 64)
    elif hostile_case == "rehearsal_run":
        _replace_command_argument(fixture.command, "--rehearsal-run-id", "0")
    elif hostile_case == "rehearsal_attempt":
        _replace_command_argument(fixture.command, "--rehearsal-run-attempt", "2")
    elif hostile_case == "rehearsal_path":
        _replace_command_argument(
            fixture.command,
            "--rehearsal-workflow-path",
            ".github/workflows/kaji.publish.yml",
        )
    elif hostile_case == "rehearsal_sha":
        _replace_command_argument(fixture.command, "--rehearsal-workflow-sha", "b" * 40)
    elif hostile_case == "candidate_id":
        _replace_command_argument(
            fixture.command, "--signed-candidate-artifact-id", "1457"
        )
    elif hostile_case == "evidence_id":
        _replace_command_argument(
            fixture.command, "--signed-evidence-artifact-id", "1790"
        )
    elif hostile_case == "candidate_archive":
        fixture.signed_paths["signed-candidate-archive"].write_bytes(b"changed")
    elif hostile_case == "candidate_digest":
        _replace_command_argument(
            fixture.command,
            "--signed-candidate-artifact-digest",
            "sha256:" + "0" * 64,
        )
    elif hostile_case == "evidence_archive":
        fixture.signed_paths["signed-evidence-archive"].write_bytes(b"changed")
    elif hostile_case == "signed_manifest":
        _replace_command_argument(
            fixture.command,
            "--signed-release-manifest-sha256",
            "0" * 64,
        )
    elif hostile_case == "signed_npm_hash":
        _replace_command_argument(
            fixture.command,
            "--signed-npm-tarball-sha256",
            "0" * 64,
        )
    elif hostile_case == "signed_npm":
        fixture.signed_paths["signed-npm-tarball"].write_bytes(b"changed")
    else:
        fixture.signed_paths["rebuilt-npm-tarball"].write_bytes(b"changed")

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert expected_code in {
        failure["code"] for failure in cast(list[dict[str, str]], summary["failures"])
    }
    assert summary["onboardingEvidence"] is None
    assert summary["signedSource"] is None


def _run_release_evidence(
    fixture: SimpleNamespace,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    return completed, json.loads(fixture.output.read_text())


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("initial", "manifest_hash_mismatch"),
        ("failed", "manifest_hash_mismatch"),
        ("cross_variant", "onboarding_status_not_passed"),
        ("extra_key", "onboarding_status_invalid"),
        ("missing_key", "onboarding_status_invalid"),
        ("boolean_schema", "onboarding_status_invalid"),
        ("wrong_kind", "onboarding_status_invalid"),
        ("wrong_run", "workflow_run_mismatch"),
        ("wrong_attempt", "workflow_run_attempt_mismatch"),
        ("wrong_ref", "workflow_ref_mismatch"),
        ("duplicate_key", "evidence_invalid_json"),
        ("nonfinite", "evidence_invalid_json"),
    ),
)
def test_release_evidence_rejects_nonpassed_or_nonclosed_onboarding_status(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    status = json.loads(fixture.onboarding_status.read_text())
    if hostile_case == "initial":
        status.update(
            {
                "releaseManifestSha256": None,
                "aggregateSha256": None,
                "conclusion": "not_run",
                "failureCode": "onboarding_not_completed",
                "exitCode": None,
            }
        )
    elif hostile_case == "failed":
        status.update(
            {
                "releaseManifestSha256": None,
                "aggregateSha256": None,
                "conclusion": "failed",
                "failureCode": "archive_authentication_not_completed",
                "exitCode": 2,
            }
        )
    elif hostile_case == "cross_variant":
        status["conclusion"] = "failed"
        status["failureCode"] = "archive_authentication_not_completed"
        status["exitCode"] = 2
    elif hostile_case == "extra_key":
        status["untrusted"] = True
    elif hostile_case == "missing_key":
        del status["kind"]
    elif hostile_case == "boolean_schema":
        status["schemaVersion"] = True
    elif hostile_case == "wrong_kind":
        status["kind"] = "kaji-typescript-onboarding-status-v2"
    elif hostile_case == "wrong_run":
        status["workflowRun"] = "https://github.com/enkyuan/alloy/actions/runs/124"
    elif hostile_case == "wrong_attempt":
        status["workflowRunAttempt"] = 2
    elif hostile_case == "wrong_ref":
        status["workflowRef"] = (
            "enkyuan/alloy/.github/workflows/"
            "kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.11"
        )
    elif hostile_case == "duplicate_key":
        encoded = json.dumps(status, indent=2, sort_keys=True) + "\n"
        fixture.onboarding_status.write_text(
            encoded.replace(
                '  "schemaVersion": 1,\n',
                '  "schemaVersion": 1,\n  "schemaVersion": 1,\n',
                1,
            )
        )
    else:
        encoded = json.dumps(status, indent=2, sort_keys=True) + "\n"
        fixture.onboarding_status.write_text(
            encoded.replace('"exitCode": 0', '"exitCode": NaN')
        )
    if hostile_case not in {"duplicate_key", "nonfinite"}:
        _write_release_evidence_json(fixture.onboarding_status, status)

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert expected_code in {
        failure["code"] for failure in cast(list[dict[str, str]], summary["failures"])
    }
    assert summary["onboardingEvidence"] is None
    assert summary["signedSource"] is None


def test_release_evidence_rejects_oversized_onboarding_status(tmp_path: Path) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    encoded = fixture.onboarding_status.read_bytes()
    fixture.onboarding_status.write_bytes(
        encoded + b" " * (64 * 1024 + 1 - len(encoded))
    )

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert {
        "evidence": "onboarding-status",
        "code": "evidence_invalid_json",
    } in cast(list[dict[str, str]], summary["failures"])
    assert summary["onboardingEvidence"] is None


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("status_hash", "onboarding_aggregate_hash_mismatch"),
        ("aggregate_serialization", "onboarding_aggregate_bytes_invalid"),
        ("aggregate_semantics", "onboarding_evidence_invalid"),
        ("retained_node_bytes", "node_receipt_hash_mismatch"),
        ("producer_mutation", "onboarding_archive_invalid"),
        ("node_repack", "onboarding_archive_invalid"),
        ("swapped_nodes", "onboarding_archive_invalid"),
        ("source_id", "onboarding_evidence_invalid"),
        ("source_digest", "onboarding_archive_invalid"),
    ),
)
def test_release_evidence_rejects_archive_or_aggregate_substitution(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    if hostile_case == "status_hash":
        status = json.loads(fixture.onboarding_status.read_text())
        status["aggregateSha256"] = "0" * 64
        _write_release_evidence_json(fixture.onboarding_status, status)
    elif hostile_case == "aggregate_serialization":
        fixture.onboarding_evidence.write_bytes(
            fixture.onboarding_evidence.read_bytes() + b"\n"
        )
        status = json.loads(fixture.onboarding_status.read_text())
        status["aggregateSha256"] = hashlib.sha256(
            fixture.onboarding_evidence.read_bytes()
        ).hexdigest()
        _write_release_evidence_json(fixture.onboarding_status, status)
    elif hostile_case == "aggregate_semantics":
        aggregate = json.loads(fixture.onboarding_evidence.read_text())
        aggregate["cells"][0]["runner"]["imageVersion"] = "forged"
        encoded = json.dumps(aggregate, indent=2, sort_keys=True).encode()
        fixture.onboarding_evidence.write_bytes(encoded)
        status = json.loads(fixture.onboarding_status.read_text())
        status["aggregateSha256"] = hashlib.sha256(encoded).hexdigest()
        _write_release_evidence_json(fixture.onboarding_status, status)
    elif hostile_case == "retained_node_bytes":
        receipt = json.loads(fixture.paths["compat-node-22"].read_text())
        _write_release_evidence_json(fixture.paths["compat-node-22"], receipt)
    elif hostile_case == "producer_mutation":
        encoded = bytearray(fixture.producer_archive.read_bytes())
        encoded[-1] ^= 1
        fixture.producer_archive.write_bytes(encoded)
    elif hostile_case == "node_repack":
        support = _load_test_support("test_typescript_onboarding_evidence.py")
        receipt = fixture.paths["compat-node-22"].read_bytes()
        fixture.source_archives[22].write_bytes(
            support._zip_bytes(
                {"compatibility-receipt.json": receipt},
                comment=b"repacked",
            )
        )
    elif hostile_case == "swapped_nodes":
        node22 = _command_argument(fixture.command, "--node22-source-archive")
        node24 = _command_argument(fixture.command, "--node24-source-archive")
        _replace_command_argument(fixture.command, "--node22-source-archive", node24)
        _replace_command_argument(fixture.command, "--node24-source-archive", node22)
    elif hostile_case == "source_id":
        _replace_command_argument(
            fixture.command, "--node22-source-artifact-id", "2202"
        )
    else:
        _replace_command_argument(
            fixture.command,
            "--node22-source-artifact-digest",
            "sha256:" + "0" * 64,
        )

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert expected_code in {
        failure["code"] for failure in cast(list[dict[str, str]], summary["failures"])
    }
    assert summary["onboardingEvidence"] is None


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    (
        (("schemaVersion",), 1),
        (("executionMode",), "local"),
        (("conclusion",), "failed"),
        (("runner", "configuredLabel"), "ubuntu-latest"),
        (("runner", "runnerArch"), "ARM64"),
        (("runner", "platformOS"), "darwin"),
        (("runtime", "version"), "v23.0.0"),
        (("toolchain", "node"), "v22.0.0"),
        (("invocation", "runAttempt"), 2),
    ),
)
def test_release_evidence_revalidates_node_receipt_from_raw_archive(
    tmp_path: Path,
    field_path: tuple[str, ...],
    replacement: object,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    receipt = json.loads(fixture.paths["compat-node-22"].read_text())
    owner = receipt
    for field in field_path[:-1]:
        owner = owner[field]
    owner[field_path[-1]] = replacement
    receipt_bytes = json.dumps(receipt, sort_keys=True).encode()
    fixture.paths["compat-node-22"].write_bytes(receipt_bytes)
    support = _load_test_support("test_typescript_onboarding_evidence.py")
    archive_bytes = support._zip_bytes({"compatibility-receipt.json": receipt_bytes})
    fixture.source_archives[22].write_bytes(archive_bytes)
    _replace_command_argument(
        fixture.command,
        "--node22-source-artifact-digest",
        "sha256:" + hashlib.sha256(archive_bytes).hexdigest(),
    )

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert "onboarding_evidence_invalid" in {
        failure["code"] for failure in cast(list[dict[str, str]], summary["failures"])
    }
    assert summary["onboardingEvidence"] is None


@pytest.mark.parametrize(
    "hostile_case",
    (
        "status_symlink",
        "producer_directory",
        "node_archive_oversized",
        "signed_tarball_symlink",
    ),
)
def test_release_evidence_rejects_unsafe_or_oversized_inputs(
    tmp_path: Path,
    hostile_case: str,
) -> None:
    mode = "publish" if hostile_case == "signed_tarball_symlink" else "rehearsal"
    fixture = _archive_native_release_evidence_fixture(tmp_path, mode=mode)
    if hostile_case == "status_symlink":
        target = fixture.onboarding_status.with_name("status-target.json")
        fixture.onboarding_status.rename(target)
        fixture.onboarding_status.symlink_to(target)
    elif hostile_case == "producer_directory":
        target = fixture.producer_archive.with_suffix(".saved")
        fixture.producer_archive.rename(target)
        fixture.producer_archive.mkdir()
    elif hostile_case == "node_archive_oversized":
        fixture.source_archives[22].write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    else:
        signed = fixture.signed_paths["signed-npm-tarball"]
        target = signed.with_suffix(".saved")
        signed.rename(target)
        signed.symlink_to(target)

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert summary["conclusion"] == "failed"
    assert summary["onboardingEvidence"] is None
    assert summary["signedSource"] is None


def _current_release_snapshot_inputs(
    fixture: SimpleNamespace,
    module: ModuleType,
) -> tuple[Path, object]:
    args = module.parse_args(fixture.command[2:])
    producer, _, _, _ = module.load_current_archives(args)
    producer_release = module._verified_archive_release(
        producer,
        args.expected_commit,
    )
    return args.artifacts_dir, producer_release


@pytest.mark.parametrize(
    "hostile_case",
    ("symlink", "directory", "hardlink", "oversize"),
)
def test_current_release_snapshot_rejects_unsafe_members(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hostile_case: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    artifacts_dir, producer_release = _current_release_snapshot_inputs(fixture, module)
    target = artifacts_dir / "SHA256SUMS"
    saved = artifacts_dir / "saved-member"
    if hostile_case == "symlink":
        target.rename(saved)
        target.symlink_to(saved.name)
    elif hostile_case == "directory":
        target.unlink()
        target.mkdir()
    elif hostile_case == "hardlink":
        target.unlink()
        os.link(artifacts_dir / "manifest.json", target)
    else:
        limits = dict(module.CURRENT_RELEASE_MEMBER_LIMITS)
        limits["SHA256SUMS"] = len(target.read_bytes()) - 1
        monkeypatch.setattr(module, "CURRENT_RELEASE_MEMBER_LIMITS", limits)

    with pytest.raises(module.EvidenceValidationError) as error:
        module.load_current_release_snapshot(
            artifacts_dir,
            producer_release=producer_release,
            expected_commit="a" * 40,
        )
    assert error.value.code == "current_carrier_unsafe"


def test_current_release_snapshot_rejects_same_inode_write_during_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    artifacts_dir, producer_release = _current_release_snapshot_inputs(fixture, module)
    target = artifacts_dir / "manifest.json"
    target_inode = target.stat().st_ino
    original_read = module.os.read
    mutated = False

    def mutate_same_inode(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        encoded = original_read(descriptor, size)
        if (
            not mutated
            and encoded
            and module.os.fstat(descriptor).st_ino == target_inode
        ):
            mutated = True
            current = target.read_bytes()
            replacement = bytes([current[0] ^ 1]) + current[1:] if current else current
            target.write_bytes(replacement)
        return encoded

    monkeypatch.setattr(module.os, "read", mutate_same_inode)

    with pytest.raises(module.EvidenceValidationError) as error:
        module.load_current_release_snapshot(
            artifacts_dir,
            producer_release=producer_release,
            expected_commit="a" * 40,
        )
    assert mutated
    assert error.value.code == "current_carrier_unsafe"


def test_current_release_snapshot_rejects_directory_inventory_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    artifacts_dir, producer_release = _current_release_snapshot_inputs(fixture, module)
    original_listdir = module.os.listdir
    calls = 0

    def drift_inventory(descriptor: int) -> list[str]:
        nonlocal calls
        calls += 1
        inventory = original_listdir(descriptor)
        return inventory if calls == 1 else [*inventory, "unreviewed"]

    monkeypatch.setattr(module.os, "listdir", drift_inventory)

    with pytest.raises(module.EvidenceValidationError) as error:
        module.load_current_release_snapshot(
            artifacts_dir,
            producer_release=producer_release,
            expected_commit="a" * 40,
        )
    assert calls == 2
    assert error.value.code == "current_carrier_unsafe"


def test_current_release_snapshot_rejects_parent_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    module = _load_root_script("validate_release_evidence.py")
    artifacts_dir, producer_release = _current_release_snapshot_inputs(fixture, module)
    saved_dir = artifacts_dir.with_name("release-before-replacement")
    original_read = module.os.read
    replaced = False

    def replace_parent_path(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        encoded = original_read(descriptor, size)
        if not replaced and encoded:
            replaced = True
            artifacts_dir.rename(saved_dir)
            artifacts_dir.mkdir()
        return encoded

    monkeypatch.setattr(module.os, "read", replace_parent_path)

    with pytest.raises(module.EvidenceValidationError) as error:
        module.load_current_release_snapshot(
            artifacts_dir,
            producer_release=producer_release,
            expected_commit="a" * 40,
        )
    assert replaced
    assert error.value.code == "current_carrier_unsafe"


def test_release_evidence_rejects_valid_but_nonproducer_current_carrier(
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    artifacts_dir = Path(_command_argument(fixture.command, "--artifacts-dir"))
    tarball = artifacts_dir / "irogane-kaji-0.2.0-beta.11.tgz"
    tarball.write_bytes(tarball.read_bytes() + b"hostile")
    manifest_path = artifacts_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["artifacts"]:
        path = artifacts_dir / entry["file"]
        entry["size"] = path.stat().st_size
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _write_release_evidence_json(manifest_path, manifest)
    checksum_lines = [
        f"{entry['sha256']}  {entry['file']}" for entry in manifest["artifacts"]
    ]
    (artifacts_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n")

    completed, summary = _run_release_evidence(fixture)

    assert completed.returncode != 0
    assert {
        "evidence": "release-artifacts",
        "code": "current_carrier_mismatch",
    } in cast(list[dict[str, str]], summary["failures"])
    assert summary["validatedEvidence"] == []


def test_release_evidence_strict_loader_fails_closed_on_stable_read_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_root_script("validate_release_evidence.py")
    path = tmp_path / "status.json"
    path.write_text("{}")

    def reject_drift(*_args: object, **_kwargs: object) -> bytes:
        raise module.CompatibilityEvidenceError("/: input changed while reading")

    monkeypatch.setattr(module, "load_stable_bytes", reject_drift)
    with pytest.raises(module.EvidenceValidationError) as error:
        module.load_strict_document(path, "status")
    assert error.value.code == "evidence_invalid_json"


def test_release_evidence_fallback_is_closed_deterministic_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    normal_completed, normal = _run_release_evidence(fixture)
    assert normal_completed.returncode == 0
    module = _load_root_script("validate_release_evidence.py")
    args = module.parse_args(fixture.command[2:])
    monkeypatch.setattr(module, "parse_args", lambda _argv=None: args)

    def explode(_args: object) -> NoReturn:
        raise RuntimeError("NPM_TOKEN=DO_NOT_RETAIN")

    monkeypatch.setattr(module, "validate", explode)
    first_code = module.main([])
    first_stdout = capsys.readouterr().out
    first_bytes = fixture.output.read_bytes()
    second_code = module.main([])
    second_stdout = capsys.readouterr().out

    fallback = json.loads(first_bytes)
    assert first_code == second_code == 1
    assert set(fallback) == set(normal)
    assert fallback["schemaVersion"] == 2
    assert fallback["conclusion"] == "failed"
    assert fallback["onboardingEvidence"] is None
    assert fallback["signedSource"] is None
    assert "DO_NOT_RETAIN" not in first_stdout
    assert first_stdout == second_stdout
    assert fixture.output.read_bytes() == first_bytes


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
    fixture = _archive_native_release_evidence_fixture(tmp_path)

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
    fixture = _archive_native_release_evidence_fixture(tmp_path)
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


def test_release_evidence_uses_archive_native_node_bindings_only() -> None:
    source = _read("kaji/scripts/validate_release_evidence.py")

    assert "validate_legacy_node_release_bindings" not in source
    assert "validate_tthw_evidence" not in source
    assert "onboarding.load_authenticated_archive(" in source
    assert "onboarding.recompute_and_compare(" in source
    assert "node_receipt_sha256" in source


@pytest.mark.parametrize(
    ("hostile_case", "expected_code"),
    (
        ("missing_receipt", "evidence_missing"),
        ("missing_canonical_python_receipt", "evidence_missing"),
        ("missing_canonical_node_receipt", "evidence_missing"),
        ("not_run_receipt", "receipt_not_passed"),
        ("failed_receipt", "node_receipt_hash_mismatch"),
        ("mixed_manifest", "manifest_hash_mismatch"),
        ("stale_workflow_run", "workflow_run_mismatch"),
        ("prior_artifact_id", "release_artifact_id_mismatch"),
        ("invalid_github_proof", "github_package_proof_invalid"),
        ("invalid_ts_schema_1", "node_receipt_hash_mismatch"),
        ("invalid_ts_schema_3", "node_receipt_hash_mismatch"),
        ("invalid_ts_alias", "node_receipt_hash_mismatch"),
        ("invalid_ts_lifecycle", "node_receipt_hash_mismatch"),
        ("invalid_ts_counts", "node_receipt_hash_mismatch"),
        ("invalid_ts_proof_version_divergence", "node_receipt_hash_mismatch"),
        ("node_producer_id_drift", "node_receipt_hash_mismatch"),
        ("node_producer_digest_drift", "node_receipt_hash_mismatch"),
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
        ("unexpected_anthropic_cell", "provider_cells_mismatch"),
        ("canonical_extra_top_level", "compatibility_receipt_invalid"),
        ("canonical_negative_timing", "node_receipt_hash_mismatch"),
        ("canonical_toolchain_drift", "node_receipt_hash_mismatch"),
        ("canonical_boolean_attempt", "workflow_run_attempt_mismatch"),
    ),
)
def test_release_evidence_validator_rejects_hostile_retained_receipts(
    tmp_path: Path,
    hostile_case: str,
    expected_code: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    if hostile_case == "missing_receipt":
        fixture.paths["compat-python-3.11"].unlink()
    elif hostile_case == "missing_canonical_python_receipt":
        fixture.paths["compat-python-3.14"].unlink()
    elif hostile_case == "missing_canonical_node_receipt":
        fixture.paths["compat-node-24"].unlink()
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
            "node_producer_id_drift": "compat-node-22",
            "node_producer_digest_drift": "compat-node-22",
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
            "unexpected_anthropic_cell": "provider-evidence",
            "canonical_extra_top_level": "compat-python-3.14",
            "canonical_negative_timing": "compat-node-24",
            "canonical_toolchain_drift": "compat-node-24",
            "canonical_boolean_attempt": "compat-python-3.14",
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
        elif hostile_case == "node_producer_id_drift":
            document["producerArtifact"]["id"] = 457
        elif hostile_case == "node_producer_digest_drift":
            document["producerArtifact"]["digest"] = "sha256:" + "f" * 64
        elif hostile_case == "source_path":
            document["resolvedPackages"]["typescript"] = str(
                fixture.workspace / "kaji/packages/ts/dist/node_modules/@irogane/kaji"
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
        elif hostile_case == "unexpected_anthropic_cell":
            document["proofs"].append(
                {
                    **document["proofs"][0],
                    "provider": "anthropic",
                    "model": "claude-test-model",
                }
            )
        elif hostile_case == "canonical_extra_top_level":
            document["untrusted"] = True
        elif hostile_case == "canonical_negative_timing":
            document["timings"]["npm"]["warmRunMs"] = -1
        elif hostile_case == "canonical_toolchain_drift":
            document["toolchain"]["bun"] = "1.3.12"
        elif hostile_case == "canonical_boolean_attempt":
            document["workflowRunAttempt"] = True
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


@pytest.mark.parametrize(
    "receipt_label",
    (
        "compat-python-3.11",
        "compat-python-3.14",
        "compat-node-22",
        "compat-node-24",
    ),
)
@pytest.mark.parametrize(
    "hostile_case",
    (
        "extra-field",
        "boolean-schema",
        "negative-timing",
        "unsafe-timing",
        "toolchain-drift",
    ),
)
def test_release_evidence_closes_every_compatibility_receipt_shape(
    tmp_path: Path,
    receipt_label: str,
    hostile_case: str,
) -> None:
    fixture = _archive_native_release_evidence_fixture(tmp_path)
    path = fixture.paths[receipt_label]
    document = json.loads(path.read_text())
    timing_name = "wheel" if receipt_label.startswith("compat-python") else "npm"

    if hostile_case == "extra-field":
        document["untrusted"] = True
    elif hostile_case == "boolean-schema":
        document["schemaVersion"] = True
    elif hostile_case == "negative-timing":
        document["timings"][timing_name]["warmRunMs"] = -1
    elif hostile_case == "unsafe-timing":
        document["timings"][timing_name]["coldSetupToOutputMs"] = 9_007_199_254_740_992
    else:
        field = "python" if receipt_label.startswith("compat-python") else "node"
        document["toolchain"][field] = "mismatched"
    _write_release_evidence_json(path, document)

    completed = subprocess.run(
        fixture.command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode != 0
    summary = json.loads(fixture.output.read_text())
    expected_code = (
        "schema_mismatch"
        if receipt_label.startswith("compat-python")
        and hostile_case == "boolean-schema"
        else (
            "compatibility_receipt_invalid"
            if receipt_label.startswith("compat-python")
            else "node_receipt_hash_mismatch"
        )
    )
    expected_evidence = (
        receipt_label
        if receipt_label.startswith("compat-python")
        else "onboarding-evidence"
    )
    assert {
        "evidence": expected_evidence,
        "code": expected_code,
    } in summary["failures"]


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
    assert "does not promote GitHub by itself" in documentation
    assert "gmail-proof-v1.schema.json" in documentation
    assert "confirm-absence" in documentation
    assert "Exact-artifact GitHub proof" in release_matrix
