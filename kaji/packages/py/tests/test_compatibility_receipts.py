from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import inspect
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterator

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT / "kaji/scripts/validate_compatibility_receipts.py"
COMMIT = "a" * 40
MANIFEST_SHA256 = "b" * 64
TARBALL_SHA256 = "c" * 64
PRODUCER_DIGEST = "sha256:" + "d" * 64
WORKFLOW_RUN = "https://github.com/enkyuan/alloy/actions/runs/123"
WORKFLOW_REF = "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"
TARBALL = "kaji-0.2.0-beta.11.tgz"
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_compatibility_receipts", VALIDATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def github_package_proof() -> dict[str, Any]:
    tools = [
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
    read_tools = tools[2:]
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
            "tools": tools,
            "readTools": read_tools,
            "providerAliases": [f"github_{tool}" for tool in tools],
            "catalogNames": [f"github.{tool}" for tool in tools],
        },
        "cliCopiedCatalog": {
            "manifestVersion": "0.1.0",
            "toolCount": 6,
            "readToolCount": 4,
            "tools": tools[:6],
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
            "testName": (
                "rejects approval for github_create_issue before token or HTTP"
            ),
            "tokenLookups": 0,
            "requestAttempts": 0,
        },
        "aliasCollisionRejected": True,
        "conclusion": "passed",
        "failureCode": None,
    }


def onboarding_proof(manager: str) -> dict[str, Any]:
    return {
        "manager": manager,
        "phases": {
            "artifactInstall": True,
            "scaffoldInit": True,
            "noKeyRun": True,
            "echoSetup": True,
            "echoRun": True,
            "coldRun": True,
            "warmRun": True,
        },
        "assertions": {
            "noKeyText": "The mock provider has completed the tool loop.",
            "deterministicText": "The mock provider has completed the tool loop.",
            "turnIdPresent": True,
            "finalSequencePositive": True,
            "echoLifecycle": ["requested", "started", "completed"],
            "echoLifecycleCounts": {
                "requested": 1,
                "started": 1,
                "completed": 1,
            },
            "echoToolCallIdentityCount": 1,
            "echoToolCallIdNonempty": True,
            "echoResult": {"message": "hello"},
            "echoFinalText": "The mock provider has completed the tool loop.",
            "forbiddenTerminalEventsAbsent": True,
            "coldWarmEqual": True,
        },
    }


def node_v2_receipt(
    major: int = 24,
    *,
    commit: str = COMMIT,
    manifest_sha256: str = MANIFEST_SHA256,
    tarball_sha256: str = TARBALL_SHA256,
    tarball_size: int = 3,
    workflow_run: str = WORKFLOW_RUN,
    workflow_run_attempt: int = 1,
    producer_artifact_id: int = 456,
    producer_artifact_digest: str = PRODUCER_DIGEST,
) -> dict[str, Any]:
    assert major in {22, 24}
    proof = github_package_proof()
    node_version = f"v{major}.14.0"
    configured_label = f"ubuntu-{major}.04"
    return {
        "schemaVersion": 2,
        "executionMode": "protected",
        "commit": commit,
        "releaseManifestSha256": manifest_sha256,
        "artifactSha256": {TARBALL: tarball_sha256},
        "packageArtifact": {
            "name": TARBALL,
            "size": tarball_size,
            "sha256": tarball_sha256,
        },
        "producerArtifact": {
            "name": "kaji-artifacts",
            "id": producer_artifact_id,
            "digest": producer_artifact_digest,
            "runId": 123,
            "runAttempt": workflow_run_attempt,
            "headSha": commit,
        },
        "runner": {
            "configuredLabel": configured_label,
            "environment": "github-hosted",
            "runnerOS": "Linux",
            "runnerArch": "X64",
            "platformOS": "linux",
            "platformArch": "x64",
            "imageOS": f"ubuntu{major}",
            "imageVersion": "20260720.1.0",
        },
        "invocation": {
            "workflowRun": workflow_run,
            "runId": 123,
            "runAttempt": workflow_run_attempt,
            "workflowRef": WORKFLOW_REF,
            "workflowSha": commit,
            "job": "node-compat",
        },
        "runtime": {"version": node_version},
        "artifacts": {
            "tarball": f"/artifacts/{TARBALL}",
            "package": f"/opt/node/{major}/node_modules/kaji",
        },
        "githubPackageProofs": {
            "npm": proof,
            "bun": deepcopy(proof),
        },
        "onboardingProofs": {
            "npm": onboarding_proof("npm"),
            "bun": onboarding_proof("bun"),
        },
        "timings": {
            "npm": {"coldSetupToOutputMs": 11, "warmRunMs": 2},
            "bun": {"coldSetupToOutputMs": 13, "warmRunMs": 3},
        },
        "toolchain": {
            "python": "not-used",
            "uv": "not-used",
            "node": node_version,
            "npm": "11.4.2",
            "bun": "1.3.11",
            "typescript": "5.7.3 and 6.0.2",
        },
        "conclusion": "passed",
        "failureCode": None,
    }


def python_v1_receipt() -> dict[str, Any]:
    hashes = {
        "kaji-0.2.0b1-py3-none-any.whl": "e" * 64,
        "kaji-0.2.0b1.tar.gz": "f" * 64,
    }
    return {
        "schemaVersion": 1,
        "commit": COMMIT,
        "releaseManifestSha256": MANIFEST_SHA256,
        "artifactSha256": hashes,
        "runtime": {
            "implementation": "CPython",
            "version": "3.14.6",
            "executable": "/opt/python/3.14/bin/python",
        },
        "artifacts": {
            "wheel": "/artifacts/kaji-0.2.0b1-py3-none-any.whl",
            "sdist": "/artifacts/kaji-0.2.0b1.tar.gz",
        },
        "githubPackageProofs": {"wheel": {}, "sdist": {}},
        "timings": {
            "wheel": {"coldSetupToOutputMs": 10_001, "warmRunMs": 501},
            "sdist": {"coldSetupToOutputMs": 10_002, "warmRunMs": 502},
        },
        "conclusion": "passed",
        "failureCode": None,
        "workflowRun": WORKFLOW_RUN,
        "workflowRunAttempt": 1,
        "toolchain": {
            "python": "3.14.6",
            "uv": "0.11.25",
            "node": "not-used",
            "npm": "not-used",
            "bun": "not-used",
            "typescript": "not-used",
        },
    }


def _node_kwargs(receipt: dict[str, Any], major: int = 24) -> dict[str, Any]:
    return {
        "expected_runtime_version": str(major),
        "commit": COMMIT,
        "manifest_hash": MANIFEST_SHA256,
        "artifacts_by_name": {
            TARBALL: {
                "size": receipt["packageArtifact"]["size"],
                "sha256": receipt["packageArtifact"]["sha256"],
            }
        },
        "expected_workflow_run": WORKFLOW_RUN,
        "expected_workflow_run_attempt": 1,
    }


def _dict_paths(value: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    if not isinstance(value, dict):
        return
    yield prefix
    for key, nested in value.items():
        if isinstance(nested, dict):
            yield from _dict_paths(nested, (*prefix, key))


def _owner(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    current = value
    for key in path:
        current = current[key]
    return current


def test_valid_python_v1_and_protected_node_v2_cells() -> None:
    module = _module()
    python = python_v1_receipt()
    python_timings, python_toolchain = module.validate_python_compatibility_receipt_v1(
        python,
        expected_runtime_version="3.14",
        commit=COMMIT,
        manifest_hash=MANIFEST_SHA256,
        artifacts_by_name={
            name: {"sha256": digest}
            for name, digest in python["artifactSha256"].items()
        },
        expected_workflow_run=WORKFLOW_RUN,
        expected_workflow_run_attempt=1,
    )
    assert python_timings["wheel"]["warmRunMs"] == 501
    assert python_toolchain["python"] == "3.14.6"

    for major in (22, 24):
        receipt = node_v2_receipt(major)
        validated = module.validate_node_compatibility_receipt_v2(
            receipt, **_node_kwargs(receipt, major)
        )
        assert validated.runtime == {"version": f"v{major}.14.0"}
        assert validated.invocation["workflowRun"] == WORKFLOW_RUN


def test_python_reader_rejects_invalid_trusted_identity_types() -> None:
    module = _module()
    receipt = python_v1_receipt()
    arguments: dict[str, Any] = {
        "expected_runtime_version": "3.14",
        "commit": COMMIT,
        "manifest_hash": MANIFEST_SHA256,
        "artifacts_by_name": {
            name: {"sha256": digest}
            for name, digest in receipt["artifactSha256"].items()
        },
        "expected_workflow_run": WORKFLOW_RUN,
        "expected_workflow_run_attempt": 1,
    }
    cases: tuple[dict[str, Any], ...] = (
        {"expected_workflow_run_attempt": True},
        {"expected_runtime_version": "3.12"},
        {"expected_workflow_run": "not-a-run"},
        {"commit": None},
        {"manifest_hash": None},
        {"artifacts_by_name": {}},
    )
    for override in cases:
        changed = {**arguments, **override}
        with pytest.raises(module.EvidenceError):
            module.validate_python_compatibility_receipt_v1(receipt, **changed)


def test_node_v2_closes_every_object_boundary() -> None:
    module = _module()
    receipt = node_v2_receipt()
    paths = tuple(_dict_paths(receipt))
    assert len(paths) > 25
    for path in paths:
        owner = _owner(receipt, path)
        for key in tuple(owner):
            invalid = deepcopy(receipt)
            del _owner(invalid, path)[key]
            with pytest.raises(module.EvidenceError):
                module.validate_node_compatibility_receipt_v2(
                    invalid, **_node_kwargs(receipt)
                )
        invalid = deepcopy(receipt)
        _owner(invalid, path)["untrusted"] = True
        with pytest.raises(module.EvidenceError):
            module.validate_node_compatibility_receipt_v2(
                invalid, **_node_kwargs(receipt)
            )


@pytest.mark.parametrize("substitution", ("local", "failed", "not_run", "legacy_v1"))
def test_node_success_reader_rejects_terminal_or_legacy_substitution(
    substitution: str,
) -> None:
    module = _module()
    receipt = node_v2_receipt()
    if substitution == "local":
        receipt["executionMode"] = "local"
    elif substitution == "legacy_v1":
        receipt["schemaVersion"] = 1
        receipt["workflowRun"] = WORKFLOW_RUN
        receipt["workflowRunAttempt"] = 1
    else:
        receipt = {
            "schemaVersion": 2,
            "executionMode": "protected",
            "commit": COMMIT,
            "releaseManifestSha256": MANIFEST_SHA256,
            "artifactSha256": {},
            "runtime": {"version": None},
            "artifacts": {},
            "githubPackageProofs": {},
            "onboardingProofs": {},
            "conclusion": substitution,
            "failureCode": "compatibility_not_completed",
            "failedPhase": None,
            "failureKind": "unknown",
        }
    with pytest.raises(module.EvidenceError):
        module.validate_node_compatibility_receipt_v2(
            receipt, **_node_kwargs(node_v2_receipt())
        )


def test_closed_nonpassed_union_retains_no_success_claims() -> None:
    module = _module()
    not_run = {
        "schemaVersion": 2,
        "executionMode": "protected",
        "commit": None,
        "releaseManifestSha256": None,
        "artifactSha256": {},
        "runtime": {"version": None},
        "artifacts": {},
        "githubPackageProofs": {},
        "onboardingProofs": {},
        "conclusion": "not_run",
        "failureCode": "compatibility_not_completed",
        "failedPhase": None,
        "failureKind": "unknown",
    }
    module.validate_node_nonpassed_receipt_v2(not_run, required_mode="protected")
    failed = {
        **not_run,
        "conclusion": "failed",
        "failedPhase": "npm:package-install",
        "failureKind": "timeout",
    }
    module.validate_node_nonpassed_receipt_v2(failed, required_mode="protected")

    for hostile in (
        {**not_run, "timings": {}},
        {**not_run, "runtime": {"version": None, "kind": "node"}},
        {**not_run, "artifacts": {"tarball": "/tmp/partial"}},
        {**not_run, "failedPhase": "npm:package-install"},
        {**not_run, "failedPhase": {}},
        {**not_run, "failureKind": "timeout"},
        {**not_run, "failureKind": []},
    ):
        with pytest.raises(module.EvidenceError):
            module.validate_node_nonpassed_receipt_v2(
                hostile, required_mode="protected"
            )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("commit",), "0" * 40),
        (("releaseManifestSha256",), "0" * 64),
        (("producerArtifact", "id"), 0),
        (("producerArtifact", "id"), True),
        (("producerArtifact", "digest"), "d" * 64),
        (("producerArtifact", "runId"), 124),
        (("producerArtifact", "runId"), True),
        (("producerArtifact", "runAttempt"), 2),
        (("producerArtifact", "headSha"), "0" * 40),
        (
            ("invocation", "workflowRun"),
            "https://github.com/enkyuan/alloy/actions/runs/124",
        ),
        (
            ("invocation", "workflowRun"),
            "https://github.example/enkyuan/alloy/actions/runs/123",
        ),
        (
            ("invocation", "workflowRun"),
            "https://github.com/foreign/alloy/actions/runs/123",
        ),
        (("invocation", "runId"), 124),
        (("invocation", "runId"), True),
        (("invocation", "runAttempt"), 2),
        (
            ("invocation", "workflowRef"),
            "enkyuan/alloy/.github/workflows/other.yml@refs/heads/main",
        ),
        (("invocation", "workflowRef"), []),
        (("invocation", "workflowSha"), "0" * 40),
        (("invocation", "job"), "other"),
        (("runner", "configuredLabel"), "ubuntu-latest"),
        (("runner", "environment"), "self-hosted"),
        (("runner", "runnerOS"), "Windows"),
        (("runner", "runnerArch"), "ARM64"),
        (("runner", "platformOS"), "darwin"),
        (("runner", "platformArch"), "arm64"),
        (("runner", "imageOS"), "ubuntu20"),
        (("runner", "imageVersion"), "bad image"),
        (("runtime", "version"), "v23.14.0"),
        (("packageArtifact", "name"), "other.tgz"),
        (("packageArtifact", "size"), 0),
        (("packageArtifact", "size"), 4),
        (("packageArtifact", "size"), True),
        (("packageArtifact", "sha256"), "0" * 64),
        (("artifactSha256", TARBALL), "0" * 64),
    ),
)
def test_node_v2_rejects_identity_and_platform_drift(
    path: tuple[str, ...], value: Any
) -> None:
    module = _module()
    receipt = node_v2_receipt()
    owner = receipt
    for key in path[:-1]:
        owner = owner[key]
    owner[path[-1]] = value
    with pytest.raises(module.EvidenceError):
        module.validate_node_compatibility_receipt_v2(
            receipt, **_node_kwargs(node_v2_receipt())
        )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("onboardingProofs", "npm", "phases", "artifactInstall"), False),
        (("onboardingProofs", "npm", "phases", "scaffoldInit"), False),
        (("onboardingProofs", "npm", "phases", "noKeyRun"), False),
        (("onboardingProofs", "npm", "phases", "echoSetup"), False),
        (("onboardingProofs", "npm", "phases", "echoRun"), False),
        (("onboardingProofs", "npm", "phases", "coldRun"), False),
        (("onboardingProofs", "npm", "phases", "warmRun"), False),
        (("onboardingProofs", "npm", "assertions", "noKeyText"), "changed"),
        (("onboardingProofs", "npm", "assertions", "deterministicText"), "changed"),
        (("onboardingProofs", "npm", "assertions", "turnIdPresent"), False),
        (("onboardingProofs", "npm", "assertions", "finalSequencePositive"), False),
        (
            ("onboardingProofs", "npm", "assertions", "echoLifecycle"),
            ["completed", "started", "requested"],
        ),
        (
            (
                "onboardingProofs",
                "npm",
                "assertions",
                "echoLifecycleCounts",
                "requested",
            ),
            2,
        ),
        (("onboardingProofs", "npm", "assertions", "echoToolCallIdentityCount"), 2),
        (("onboardingProofs", "npm", "assertions", "echoToolCallIdNonempty"), False),
        (("onboardingProofs", "npm", "assertions", "echoResult", "message"), "changed"),
        (("onboardingProofs", "npm", "assertions", "echoFinalText"), "changed"),
        (
            ("onboardingProofs", "npm", "assertions", "forbiddenTerminalEventsAbsent"),
            False,
        ),
        (("onboardingProofs", "npm", "assertions", "coldWarmEqual"), False),
        (("timings", "npm", "warmRunMs"), -1),
        (("timings", "npm", "warmRunMs"), True),
        (("timings", "npm", "coldSetupToOutputMs"), MAX_SAFE_INTEGER + 1),
        (("toolchain", "node"), "v22.14.0"),
        (("toolchain", "npm"), "01.2.3"),
        (("toolchain", "bun"), "1.3.12"),
        (("toolchain", "typescript"), "5.7.3 and 5.7.3"),
    ),
)
def test_node_v2_rejects_onboarding_timing_and_toolchain_drift(
    path: tuple[str, ...], value: Any
) -> None:
    module = _module()
    manager_paths = (
        (
            path,
            (
                path[0],
                "bun",
                *path[2:],
            ),
        )
        if path[0] in {"onboardingProofs", "timings"} and path[1] == "npm"
        else (path,)
    )
    for manager_path in manager_paths:
        receipt = node_v2_receipt()
        owner = receipt
        for key in manager_path[:-1]:
            owner = owner[key]
        owner[manager_path[-1]] = value
        with pytest.raises(module.EvidenceError):
            module.validate_node_compatibility_receipt_v2(
                receipt, **_node_kwargs(node_v2_receipt())
            )


def test_node_v2_rejects_incomplete_or_unequal_github_proofs() -> None:
    module = _module()
    valid = node_v2_receipt()
    for mutate in (
        lambda value: value["githubPackageProofs"]["npm"].pop("lifecycle"),
        lambda value: value["githubPackageProofs"]["npm"]["lifecycle"][
            "githubFailure"
        ].update({"untrusted": True}),
        lambda value: value["githubPackageProofs"]["bun"][
            "typescriptDeclarationChecks"
        ]["typescriptCurrent"].update({"version": "6.0.3"}),
    ):
        receipt = deepcopy(valid)
        mutate(receipt)
        with pytest.raises(module.EvidenceError):
            module.validate_node_compatibility_receipt_v2(
                receipt, **_node_kwargs(valid)
            )


def test_node_reader_rejects_invalid_trusted_identity_types() -> None:
    module = _module()
    receipt = node_v2_receipt()
    cases: tuple[dict[str, Any], ...] = (
        {"expected_workflow_run_attempt": True},
        {"expected_runtime_version": "23"},
        {"expected_workflow_run": "https://github.example/actions/runs/123"},
        {"commit": None},
        {"manifest_hash": None},
    )
    for override in cases:
        arguments: dict[str, Any] = _node_kwargs(receipt)
        arguments.update(override)
        with pytest.raises(module.EvidenceError):
            module.validate_node_compatibility_receipt_v2(receipt, **arguments)


def test_strong_binding_rejects_well_formed_external_identity_substitution() -> None:
    module = _module()
    receipt = node_v2_receipt()
    validated = module.validate_node_compatibility_receipt_v2(
        receipt, **_node_kwargs(receipt)
    )
    trusted = {
        "package_artifact": deepcopy(receipt["packageArtifact"]),
        "producer_artifact": deepcopy(receipt["producerArtifact"]),
        "runner": deepcopy(receipt["runner"]),
        "invocation": deepcopy(receipt["invocation"]),
    }
    module.validate_node_receipt_bindings(validated, **trusted)

    substitutions = (
        ("package_artifact", "sha256", "e" * 64),
        ("producer_artifact", "id", 457),
        ("producer_artifact", "digest", "sha256:" + "e" * 64),
        ("producer_artifact", "runId", 124),
        ("producer_artifact", "runAttempt", 2),
        ("producer_artifact", "headSha", "f" * 40),
        ("runner", "imageVersion", "forged"),
        (
            "invocation",
            "workflowRef",
            "enkyuan/alloy/.github/workflows/kaji.publish.yml"
            "@refs/tags/kaji-v0.2.0-beta.11",
        ),
        ("invocation", "workflowSha", "f" * 40),
        ("invocation", "runId", 124),
        ("invocation", "runAttempt", 2),
    )
    for object_name, field, value in substitutions:
        changed = deepcopy(trusted)
        changed[object_name][field] = value
        with pytest.raises(module.EvidenceError):
            module.validate_node_receipt_bindings(validated, **changed)


def test_protected_source_binding_is_static_and_does_not_self_bind_image() -> None:
    module = _module()
    signature = inspect.signature(
        module.validate_protected_node_receipt_source_bindings
    )
    assert tuple(signature.parameters) == (
        "receipt",
        "package_artifact",
        "producer_artifact",
        "static_runner_policy",
        "invocation",
    )
    assert "image_version" not in signature.parameters
    receipt = node_v2_receipt()
    receipt["runner"]["imageVersion"] = "observed.1"
    validated = module.validate_node_compatibility_receipt_v2(
        receipt, **_node_kwargs(receipt)
    )
    trusted = {
        "package_artifact": deepcopy(receipt["packageArtifact"]),
        "producer_artifact": deepcopy(receipt["producerArtifact"]),
        "static_runner_policy": {
            field: value
            for field, value in receipt["runner"].items()
            if field != "imageVersion"
        },
        "invocation": deepcopy(receipt["invocation"]),
    }
    module.validate_protected_node_receipt_source_bindings(validated, **trusted)

    substitutions = (
        ("package_artifact", "sha256", "e" * 64),
        ("producer_artifact", "id", 457),
        ("static_runner_policy", "configuredLabel", "ubuntu-latest"),
        ("invocation", "workflowSha", "f" * 40),
    )
    for object_name, field, value in substitutions:
        changed = deepcopy(trusted)
        changed[object_name][field] = value
        with pytest.raises(module.EvidenceError):
            module.validate_protected_node_receipt_source_bindings(validated, **changed)

    extra = deepcopy(trusted)
    extra["static_runner_policy"]["imageVersion"] = "observed.1"
    with pytest.raises(module.EvidenceError, match="policy shape"):
        module.validate_protected_node_receipt_source_bindings(validated, **extra)


def test_legacy_release_binding_is_explicit_and_limited_to_trusted_dimensions() -> None:
    module = _module()
    signature = inspect.signature(module.validate_legacy_node_release_bindings)
    assert tuple(signature.parameters) == (
        "receipt",
        "package_artifact",
        "producer_artifact",
        "workflow_run",
        "workflow_run_attempt",
        "commit",
    )
    assert "runner" not in signature.parameters
    assert "invocation" not in signature.parameters

    receipt = node_v2_receipt()
    validated = module.validate_node_compatibility_receipt_v2(
        receipt, **_node_kwargs(receipt)
    )
    trusted: dict[str, Any] = {
        "package_artifact": deepcopy(receipt["packageArtifact"]),
        "producer_artifact": deepcopy(receipt["producerArtifact"]),
        "workflow_run": WORKFLOW_RUN,
        "workflow_run_attempt": 1,
        "commit": COMMIT,
    }
    module.validate_legacy_node_release_bindings(validated, **trusted)

    substitutions: tuple[tuple[str, Any], ...] = (
        (
            "package_artifact",
            {**trusted["package_artifact"], "sha256": "e" * 64},
        ),
        ("producer_artifact", {**trusted["producer_artifact"], "id": 457}),
        ("workflow_run", "https://github.com/enkyuan/alloy/actions/runs/124"),
        ("workflow_run_attempt", 2),
        ("commit", "f" * 40),
    )
    for name, value in substitutions:
        changed = {**trusted, name: value}
        with pytest.raises(module.EvidenceError):
            module.validate_legacy_node_release_bindings(validated, **changed)


def test_load_json_with_sha256_hashes_the_same_safe_snapshot(
    tmp_path: Path,
) -> None:
    module = _module()
    path = tmp_path / "receipt.json"
    encoded = b'{\n  "schemaVersion": 2,\n  "value": "same bytes"\n}\n'
    path.write_bytes(encoded)

    document, digest = module.load_json_with_sha256(path, "compatibility receipt")

    assert document == {"schemaVersion": 2, "value": "same bytes"}
    assert digest == hashlib.sha256(encoded).hexdigest()

    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(path)
    with pytest.raises(module.EvidenceError):
        module.load_json_with_sha256(symlink, "compatibility receipt")

    assert (
        module.load_stable_bytes(path, "compatibility receipt", max_bytes=1024)
        == encoded
    )


def test_release_identity_rejects_unsafe_or_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"artifact")
    symlink = tmp_path / "artifact-link"
    symlink.symlink_to(artifact)

    with pytest.raises(module.EvidenceError):
        module.artifact_identity(symlink)

    monkeypatch.setattr(module, "_same_file", lambda *_args: False)
    with pytest.raises(module.EvidenceError):
        module.artifact_identity(artifact)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"commit":"' + COMMIT + '","artifacts":[{"file":["unhashable"]}]}'
    )
    with pytest.raises(module.EvidenceError):
        module.read_release_identity(manifest, tmp_path)
