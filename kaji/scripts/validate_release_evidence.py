#!/usr/bin/env python3
"""Fail closed unless every retained beta receipt names one release run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, NoReturn

from aggregate_benchmarks import _aggregate_case
from benchmark_platform import (
    MAX_IMAGE_DATA_BYTES,
    BenchmarkPlatformError,
    validate_retained_runner,
)
from paired_benchmark import (
    CASES,
    REFERENCE_IDENTITY_FILES,
    REFERENCE_PATH,
    RUNTIMES,
    THRESHOLD,
    _file_sha256,
    _json_sha256,
    _load_reference,
    _protocol_hash,
    _reference_identity,
    _validate_identity,
    _validate_replica_report,
    _validate_runner_evidence,
    _validate_utc_timestamp,
)
from validate_tthw_evidence import (
    EvidenceError as TthwEvidenceError,
    validate_closed_compatibility_receipt,
    validate_bindings as validate_tthw_bindings,
    validate_compatibility_receipts as validate_tthw_compatibility_receipts,
    validate_document as validate_tthw_document,
)
from verify_release_artifacts import VerifiedReleaseArtifacts, verify


COMMIT = re.compile(r"[0-9a-f]{40}")
ARTIFACT_DIGEST = re.compile(r"[0-9a-f]{64}")
ARTIFACT_ID = re.compile(r"[1-9][0-9]*")
WORKFLOW_RUN = re.compile(r"https?://.+/actions/runs/[1-9][0-9]*")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
PYTHON_WHEEL = "kaji_sdk-0.2.0b1-py3-none-any.whl"
PYTHON_SDIST = "kaji_sdk-0.2.0b1.tar.gz"
TYPESCRIPT_TARBALL = "kaji-sdk-0.2.0-beta.7.tgz"
TYPESCRIPT_GITHUB_TOOLS = (
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
)
TYPESCRIPT_GITHUB_READ_TOOLS = TYPESCRIPT_GITHUB_TOOLS[2:]
SHARED_GITHUB_TOOLS = TYPESCRIPT_GITHUB_TOOLS[:6]
SHARED_GITHUB_READ_TOOLS = TYPESCRIPT_GITHUB_READ_TOOLS[:4]


class EvidenceValidationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def reject(code: str) -> NoReturn:
    raise EvidenceValidationError(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        reject(code)


def load_document(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file() or path.is_symlink():
        reject("evidence_missing")
    try:
        encoded = path.read_bytes()
        document = json.loads(encoded)
    except (OSError, UnicodeError, json.JSONDecodeError):
        reject("evidence_invalid_json")
    require(isinstance(document, dict), "evidence_not_object")
    return document, hashlib.sha256(encoded).hexdigest()


def load_performance_image_data(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        reject("evidence_missing")
    try:
        encoded = path.read_bytes()
    except OSError:
        reject("performance_image_data_invalid")
    require(
        0 < len(encoded) <= MAX_IMAGE_DATA_BYTES,
        "performance_image_data_invalid",
    )
    return hashlib.sha256(encoded).hexdigest()


def full_artifact_hashes(release: VerifiedReleaseArtifacts) -> dict[str, str]:
    return dict(sorted(release.artifact_sha256.items()))


def runtime_artifacts(release: VerifiedReleaseArtifacts) -> dict[str, Any]:
    return {
        "python": {
            "file": PYTHON_WHEEL,
            "sha256": release.artifact_sha256[PYTHON_WHEEL],
        },
        "typescript": {
            "file": TYPESCRIPT_TARBALL,
            "sha256": release.artifact_sha256[TYPESCRIPT_TARBALL],
        },
    }


def validate_run_identity(document: dict[str, Any], args: argparse.Namespace) -> None:
    require(document.get("workflowRun") == args.workflow_run, "workflow_run_mismatch")
    require(
        document.get("workflowRunAttempt") == args.workflow_run_attempt,
        "workflow_run_attempt_mismatch",
    )


def validate_passed_receipt(document: dict[str, Any], args: argparse.Namespace) -> None:
    require(document.get("schemaVersion") == 1, "schema_mismatch")
    require(document.get("commit") == args.expected_commit, "commit_mismatch")
    validate_run_identity(document, args)
    require(
        document.get("conclusion") == "passed" and document.get("failureCode") is None,
        "receipt_not_passed",
    )


def validate_manifest(
    document: dict[str, Any], release: VerifiedReleaseArtifacts
) -> None:
    require(
        document.get("releaseManifestSha256") == release.manifest_sha256,
        "manifest_hash_mismatch",
    )


def _strict_json_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _strict_json_equal(value[key], item) for key, item in expected.items()
        )
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _strict_json_equal(actual, item)
            for actual, item in zip(value, expected, strict=True)
        )
    return value == expected


def _python_github_package_proof(runtime: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "evidenceClass": "offline_exact_artifact_smoke",
        "integration": "github",
        "runtime": runtime,
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


def _typescript_github_package_proof_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    declarations = value.get("typescriptDeclarationChecks")
    if not isinstance(declarations, dict):
        return False
    current = declarations.get("typescriptCurrent")
    current_version = current.get("version") if isinstance(current, dict) else None
    if (
        not isinstance(current_version, str)
        or SEMVER.fullmatch(current_version) is None
        or current_version == "5.7.3"
    ):
        return False

    tools = list(TYPESCRIPT_GITHUB_TOOLS)
    read_tools = list(TYPESCRIPT_GITHUB_READ_TOOLS)
    expected = {
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
            "tools": list(SHARED_GITHUB_TOOLS),
            "readTools": list(SHARED_GITHUB_READ_TOOLS),
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
                "version": current_version,
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
    return _strict_json_equal(value, expected)


def validate_github_package_proofs(value: Any, runtime: str) -> None:
    expected_keys = {"sdist", "wheel"} if runtime == "python" else {"bun", "npm"}
    if runtime == "python":
        valid = (
            isinstance(value, dict)
            and set(value) == expected_keys
            and all(
                _strict_json_equal(proof, _python_github_package_proof(runtime))
                for proof in value.values()
            )
        )
    else:
        valid = (
            runtime == "typescript"
            and isinstance(value, dict)
            and set(value) == expected_keys
            and _strict_json_equal(value["npm"], value["bun"])
            and all(
                _typescript_github_package_proof_valid(proof)
                for proof in value.values()
            )
        )
    require(
        valid,
        "github_package_proof_invalid",
    )


def validate_compatibility(
    document: dict[str, Any],
    *,
    runtime: str,
    version: str,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    validate_passed_receipt(document, args)
    validate_manifest(document, release)
    runtime_value = document.get("runtime")
    artifacts = document.get("artifacts")
    if not isinstance(runtime_value, dict):
        reject("compatibility_runtime_invalid")
    if not isinstance(artifacts, dict):
        reject("compatibility_artifacts_invalid")

    if runtime == "python":
        expected_hashes = {
            PYTHON_WHEEL: release.artifact_sha256[PYTHON_WHEEL],
            PYTHON_SDIST: release.artifact_sha256[PYTHON_SDIST],
        }
        require(
            document.get("artifactSha256") == expected_hashes,
            "artifact_hash_mismatch",
        )
        validate_github_package_proofs(document.get("githubPackageProofs"), runtime)
        try:
            validate_closed_compatibility_receipt(
                document,
                runtime="python",
                expected_runtime_version=version,
                commit=args.expected_commit,
                manifest_hash=release.manifest_sha256,
                artifacts_by_name={
                    name: {"sha256": digest} for name, digest in expected_hashes.items()
                },
                expected_workflow_run=args.workflow_run,
                expected_workflow_run_attempt=args.workflow_run_attempt,
            )
        except TthwEvidenceError:
            reject("compatibility_receipt_invalid")
        return

    expected_hashes = {TYPESCRIPT_TARBALL: release.artifact_sha256[TYPESCRIPT_TARBALL]}
    require(
        document.get("artifactSha256") == expected_hashes,
        "artifact_hash_mismatch",
    )
    validate_github_package_proofs(document.get("githubPackageProofs"), "typescript")
    try:
        validate_closed_compatibility_receipt(
            document,
            runtime="node",
            expected_runtime_version=version,
            commit=args.expected_commit,
            manifest_hash=release.manifest_sha256,
            artifacts_by_name={
                TYPESCRIPT_TARBALL: {
                    "sha256": release.artifact_sha256[TYPESCRIPT_TARBALL]
                }
            },
            expected_workflow_run=args.workflow_run,
            expected_workflow_run_attempt=args.workflow_run_attempt,
        )
    except TthwEvidenceError:
        reject("compatibility_receipt_invalid")
    validate_package_path(artifacts.get("package"), "typescript", args.workspace)


def validate_package_path(value: Any, runtime: str, workspace: Path) -> None:
    require(isinstance(value, str) and bool(value), "resolved_package_invalid")
    path = Path(value)
    require(path.is_absolute(), "resolved_package_invalid")
    resolved = path.resolve(strict=False)
    checkout = workspace.resolve(strict=False)
    require(
        resolved != checkout and not resolved.is_relative_to(checkout),
        "source_path_detected",
    )
    normalized = resolved.as_posix()
    require(
        not any(
            marker in normalized
            for marker in ("/kaji/src/", "/kaji/ts/src/", "/kaji/ts/dist/")
        ),
        "source_path_detected",
    )
    suffix = (
        "/site-packages/kaji/__init__.py"
        if runtime == "python"
        else "/node_modules/kaji-sdk"
    )
    require(normalized.endswith(suffix), "resolved_package_invalid")


def validate_resolved_packages(value: Any, args: argparse.Namespace) -> dict[str, str]:
    require(
        isinstance(value, dict) and set(value) == {"python", "typescript"},
        "resolved_packages_invalid",
    )
    validate_package_path(value["python"], "python", args.workspace)
    validate_package_path(value["typescript"], "typescript", args.workspace)
    return {"python": value["python"], "typescript": value["typescript"]}


def validate_performance_fingerprint(value: Any) -> dict[str, Any]:
    require(
        isinstance(value, dict) and bool(value),
        "performance_fingerprint_invalid",
    )
    try:
        validate_retained_runner(value.get("runner"))
    except BenchmarkPlatformError:
        reject("performance_runner_invalid")
    return value


def paired_artifacts(release: VerifiedReleaseArtifacts) -> dict[str, Any]:
    return {
        "pythonWheel": {
            "file": PYTHON_WHEEL,
            "sha256": release.artifact_sha256[PYTHON_WHEEL],
        },
        "pythonSdist": {
            "file": PYTHON_SDIST,
            "sha256": release.artifact_sha256[PYTHON_SDIST],
        },
        "typescript": {
            "file": TYPESCRIPT_TARBALL,
            "sha256": release.artifact_sha256[TYPESCRIPT_TARBALL],
        },
    }


def validate_paired_benchmark(
    document: dict[str, Any],
    *,
    raw_replicas: dict[str, dict[str, Any]],
    runner_image_digests: dict[str, str],
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    expected_keys = {
        "schemaVersion",
        "kind",
        "generatedAt",
        "protocolHash",
        "threshold",
        "referenceRecordSha256",
        "reference",
        "candidate",
        "referenceReceiptSha256",
        "candidateReceiptSha256",
        "replicas",
        "cases",
        "failures",
        "passed",
        "reportReceiptSha256",
    }
    require(set(document) == expected_keys, "paired_benchmark_schema_invalid")
    require(
        document.get("schemaVersion") == 1
        and document.get("kind") == "kaji-beta-paired-benchmark-aggregate",
        "paired_benchmark_schema_invalid",
    )
    try:
        _validate_utc_timestamp(document.get("generatedAt"), "aggregate generatedAt")
        reference_record = _load_reference()
        reference = _validate_identity(
            document.get("reference"), "reference", REFERENCE_IDENTITY_FILES
        )
        candidate = _validate_identity(document.get("candidate"), "candidate")
    except RuntimeError:
        reject("paired_benchmark_identity_invalid")
    require(
        document.get("protocolHash") == _protocol_hash()
        and document.get("threshold") == THRESHOLD
        and document.get("referenceRecordSha256") == _file_sha256(REFERENCE_PATH),
        "paired_benchmark_protocol_mismatch",
    )
    require(
        reference == _reference_identity(reference_record),
        "paired_benchmark_reference_mismatch",
    )
    expected_candidate = {
        "commit": args.expected_commit,
        "releaseManifestSha256": release.manifest_sha256,
        "artifacts": paired_artifacts(release),
    }
    require(candidate == expected_candidate, "artifact_hash_mismatch")
    require(
        document.get("referenceReceiptSha256") == _json_sha256(reference)
        and document.get("candidateReceiptSha256") == _json_sha256(candidate),
        "paired_benchmark_identity_receipt_mismatch",
    )
    unsigned = {
        key: value for key, value in document.items() if key != "reportReceiptSha256"
    }
    require(
        document.get("reportReceiptSha256") == _json_sha256(unsigned),
        "paired_benchmark_receipt_mismatch",
    )
    require(
        document.get("passed") is True and document.get("failures") == [],
        "performance_not_passed",
    )

    replicas = document.get("replicas")
    if not isinstance(replicas, dict) or set(replicas) != {"1", "2", "3"}:
        reject("paired_benchmark_replicas_invalid")
    require(
        set(raw_replicas) == {"1", "2", "3"},
        "paired_raw_replica_missing",
    )
    invocation_values: list[dict[str, Any]] = []
    validated_raw_replicas: dict[str, dict[str, Any]] = {}
    for replica in ("1", "2", "3"):
        receipt = replicas[replica]
        require(
            isinstance(receipt, dict)
            and set(receipt) == {"reportReceiptSha256", "runnerEvidence"},
            "paired_benchmark_replicas_invalid",
        )
        require(
            isinstance(receipt["reportReceiptSha256"], str)
            and ARTIFACT_DIGEST.fullmatch(receipt["reportReceiptSha256"]) is not None,
            "paired_benchmark_replicas_invalid",
        )
        try:
            raw_replica = _validate_replica_report(raw_replicas[replica])
        except RuntimeError:
            reject("paired_raw_replica_invalid")
        try:
            runner_evidence = _validate_runner_evidence(receipt["runnerEvidence"])
        except RuntimeError:
            reject("paired_benchmark_runner_invalid")
        require(
            raw_replica["replica"] == int(replica)
            and raw_replica["reportReceiptSha256"] == receipt["reportReceiptSha256"]
            and raw_replica["runnerEvidence"] == receipt["runnerEvidence"],
            "paired_raw_replica_mismatch",
        )
        require(
            runner_image_digests.get(replica)
            == runner_evidence["runner"].get("imageDataSha256"),
            "paired_image_data_hash_mismatch",
        )
        validated_raw_replicas[replica] = raw_replica
        invocation_values.append(runner_evidence["invocation"])
    expected_run_id = int(args.workflow_run.rsplit("/", 1)[1])
    require(
        all(
            invocation["runId"] == expected_run_id
            and invocation["runAttempt"] == args.workflow_run_attempt
            and invocation["workflowSha"] == args.expected_commit
            for invocation in invocation_values
        ),
        "paired_benchmark_invocation_mismatch",
    )
    require(
        len({invocation["job"] for invocation in invocation_values}) == 1
        and len({invocation["workflowRef"] for invocation in invocation_values}) == 1,
        "paired_benchmark_replicas_invalid",
    )

    ordered_replicas = [validated_raw_replicas[replica] for replica in ("1", "2", "3")]
    cases = document.get("cases")
    if not isinstance(cases, dict) or set(cases) != set(RUNTIMES):
        reject("performance_results_invalid")
    for runtime in RUNTIMES:
        runtime_cases = cases[runtime]
        if not isinstance(runtime_cases, dict) or set(runtime_cases) != set(CASES):
            reject("performance_results_invalid")
        for case in CASES:
            evidence = runtime_cases[case]
            expected = _aggregate_case(ordered_replicas, runtime, case)
            require(
                isinstance(evidence, dict)
                and set(evidence)
                == {
                    "durationRatios",
                    "rssRatios",
                    "durationVerdict",
                    "rssVerdict",
                    "verdict",
                },
                "performance_results_invalid",
            )
            require(evidence == expected, "performance_results_invalid")
            for field in ("durationRatios", "rssRatios"):
                ratios = evidence[field]
                require(
                    isinstance(ratios, list)
                    and len(ratios) == 3
                    and all(
                        not isinstance(ratio, bool)
                        and isinstance(ratio, (int, float))
                        and math.isfinite(float(ratio))
                        and ratio >= 0
                        and ratio <= THRESHOLD
                        for ratio in ratios
                    ),
                    "performance_results_invalid",
                )
            require(
                evidence["durationVerdict"] == "pass"
                and evidence["rssVerdict"] == "pass"
                and evidence["verdict"] == "pass",
                "performance_not_passed",
            )


def validate_soak_report(
    document: dict[str, Any],
    *,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> dict[str, str]:
    require(document.get("schemaVersion") == 1, "schema_mismatch")
    require(document.get("commit") == args.expected_commit, "commit_mismatch")
    require(document.get("protected") is True, "performance_not_protected")
    require(
        document.get("passed") is True and document.get("failures") == [],
        "performance_not_passed",
    )
    validate_manifest(document, release)
    require(
        document.get("artifacts") == runtime_artifacts(release),
        "artifact_hash_mismatch",
    )
    validate_performance_fingerprint(document.get("fingerprint"))
    resolved = validate_resolved_packages(document.get("resolvedPackages"), args)
    results = document.get("results")
    if not isinstance(results, dict):
        reject("performance_results_invalid")
    require(set(results) == {"python", "typescript"}, "performance_results_invalid")
    require(document.get("requestedMinutes") == 30, "soak_duration_invalid")
    for runtime, result in results.items():
        require(
            isinstance(result, dict)
            and result.get("resolvedPackage") == resolved[runtime],
            "resolved_package_mismatch",
        )
    return resolved


def validate_performance_status(
    document: dict[str, Any],
    benchmark: dict[str, Any],
    soak: dict[str, Any],
    soak_receipt_sha256: str,
    *,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    require(
        document.get("schemaVersion") == 2
        and document.get("kind") == "kaji-beta-performance-status",
        "performance_status_invalid",
    )
    require(document.get("commit") == args.expected_commit, "commit_mismatch")
    validate_run_identity(document, args)
    require(
        document.get("conclusion") == "passed" and document.get("failureCode") is None,
        "receipt_not_passed",
    )
    validate_manifest(document, release)
    require(
        document.get("artifacts") == paired_artifacts(release),
        "artifact_hash_mismatch",
    )
    require(
        document.get("benchmarkOutcome") == "success"
        and document.get("soakOutcome") == "success"
        and document.get("validationOutcome") == "success",
        "performance_status_invalid",
    )
    require(
        document.get("releaseArtifactId") == args.release_artifact_id,
        "release_artifact_id_mismatch",
    )
    require(
        document.get("releaseArtifactDigest") == args.release_artifact_digest,
        "release_artifact_digest_mismatch",
    )
    require(
        document.get("benchmarkReceiptSha256") == benchmark.get("reportReceiptSha256"),
        "paired_benchmark_receipt_mismatch",
    )
    require(
        document.get("soakReceiptSha256") == soak_receipt_sha256,
        "soak_receipt_mismatch",
    )


def validate_performance_image_data(
    digest: str,
    soak: dict[str, Any],
) -> None:
    soak_fingerprint = validate_performance_fingerprint(soak.get("fingerprint"))
    require(
        digest == soak_fingerprint.get("runner", {}).get("imageDataSha256"),
        "performance_image_data_hash_mismatch",
    )


def validate_provider(
    document: dict[str, Any],
    *,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    allowed_top = {
        "schemaVersion",
        "commit",
        "releaseManifestSha256",
        "artifacts",
        "conclusion",
        "failureCode",
        "proofs",
        "releaseArtifactId",
        "releaseArtifactDigest",
        "workflowRun",
        "workflowRunAttempt",
    }
    require(set(document) <= allowed_top, "provider_schema_invalid")
    validate_passed_receipt(document, args)
    validate_manifest(document, release)
    require(
        document.get("artifacts") == runtime_artifacts(release),
        "artifact_hash_mismatch",
    )
    require(
        document.get("releaseArtifactId") == args.release_artifact_id,
        "release_artifact_id_mismatch",
    )
    require(
        document.get("releaseArtifactDigest") == args.release_artifact_digest,
        "release_artifact_digest_mismatch",
    )

    row_keys = {
        "sdk",
        "provider",
        "proof",
        "status",
        "model",
        "artifactFile",
        "artifactSha256",
        "releaseManifestSha256",
        "resolvedPackage",
        "requestedToolCalls",
        "completedToolCalls",
        "requestedToolCallIds",
        "completedToolCallIds",
        "echoResultMatched",
        "finalTextPresent",
        "forbiddenTerminalEvents",
    }
    proofs = document.get("proofs")
    if not isinstance(proofs, list):
        reject("provider_cells_mismatch")
    require(len(proofs) == 2, "provider_cells_mismatch")
    expected_cells = {
        ("python", "openai"),
        ("typescript", "openai"),
    }
    cells = {
        (row.get("sdk"), row.get("provider")) for row in proofs if isinstance(row, dict)
    }
    require(cells == expected_cells, "provider_cells_mismatch")
    for row in proofs:
        if not isinstance(row, dict):
            reject("provider_schema_invalid")
        require(set(row) == row_keys, "provider_schema_invalid")
        sdk = row["sdk"]
        artifact = runtime_artifacts(release)[sdk]
        require(
            row["proof"] == "real_normalized_tool_loop",
            "provider_proof_invalid",
        )
        require(row["status"] == "passed", "provider_proof_not_passed")
        require(
            isinstance(row["model"], str) and bool(row["model"].strip()),
            "provider_model_invalid",
        )
        require(
            row["artifactFile"] == artifact["file"]
            and row["artifactSha256"] == artifact["sha256"]
            and row["releaseManifestSha256"] == release.manifest_sha256,
            "artifact_hash_mismatch",
        )
        validate_package_path(row["resolvedPackage"], sdk, args.workspace)
        requested = row["requestedToolCallIds"]
        completed = row["completedToolCallIds"]
        require(
            row["requestedToolCalls"] == 1
            and row["completedToolCalls"] == 1
            and isinstance(requested, list)
            and len(requested) == 1
            and isinstance(requested[0], str)
            and bool(requested[0])
            and completed == requested,
            "provider_tool_trace_invalid",
        )
        require(
            row["echoResultMatched"] is True
            and row["finalTextPresent"] is True
            and row["forbiddenTerminalEvents"] == [],
            "provider_terminal_trace_invalid",
        )


def validate_tthw_status(
    document: dict[str, Any],
    *,
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    validate_passed_receipt(document, args)
    validate_manifest(document, release)
    require(document.get("exitCode") == 0, "tthw_status_invalid")
    require(
        document.get("artifactSha256") == full_artifact_hashes(release),
        "artifact_hash_mismatch",
    )


def validate_tthw_raw(
    document: dict[str, Any],
    *,
    python_compatibility: dict[str, Any],
    node_compatibility: dict[str, Any],
    release: VerifiedReleaseArtifacts,
    args: argparse.Namespace,
) -> None:
    require(document.get("commit") == args.expected_commit, "commit_mismatch")
    validate_manifest(document, release)
    try:
        validate_tthw_document(document)
        validate_tthw_bindings(
            document,
            release.root / "manifest.json",
            release.root,
        )
        validate_tthw_compatibility_receipts(
            document,
            python_compatibility,
            node_compatibility,
            expected_workflow_run=args.workflow_run,
            expected_workflow_run_attempt=args.workflow_run_attempt,
        )
    except (TthwEvidenceError, KeyError, TypeError, ValueError):
        reject("tthw_evidence_invalid")


def input_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "compat-python-3.11": args.python_compat_311,
        "compat-python-3.14": args.python_compat_314,
        "compat-node-22": args.node_compat_22,
        "compat-node-24": args.node_compat_24,
        "performance-status": args.performance_status,
        "benchmark-results": args.benchmark_results,
        "soak-results": args.soak_results,
        "provider-evidence": args.provider_evidence,
        "tthw-status": args.tthw_status,
        "tthw-evidence": args.tthw_evidence,
    }


def invocation_failures(args: argparse.Namespace) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    checks = (
        (COMMIT.fullmatch(args.expected_commit) is not None, "expected_commit_invalid"),
        (WORKFLOW_RUN.fullmatch(args.workflow_run) is not None, "workflow_run_invalid"),
        (args.workflow_run_attempt > 0, "workflow_run_attempt_invalid"),
        (
            ARTIFACT_ID.fullmatch(args.release_artifact_id) is not None,
            "release_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.release_artifact_digest) is not None,
            "release_artifact_digest_invalid",
        ),
        (args.workspace.is_absolute(), "workspace_invalid"),
    )
    for valid, code in checks:
        if not valid:
            failures.append({"evidence": "invocation", "code": code})
    return failures


def validate(args: argparse.Namespace) -> dict[str, Any]:
    failures = invocation_failures(args)
    documents: dict[str, dict[str, Any]] = {}
    receipt_hashes: dict[str, str] = {}
    validated: list[str] = []

    for label, path in input_paths(args).items():
        try:
            document, digest = load_document(path)
        except EvidenceValidationError as error:
            failures.append({"evidence": label, "code": error.code})
        else:
            documents[label] = document
            receipt_hashes[label] = digest

    performance_image_data_digest: str | None = None
    try:
        performance_image_data_digest = load_performance_image_data(
            args.performance_image_data
        )
    except EvidenceValidationError as error:
        failures.append({"evidence": "performance-image-data", "code": error.code})
    else:
        receipt_hashes["performance-image-data"] = performance_image_data_digest

    paired_image_digests: dict[str, str] = {}
    raw_replicas: dict[str, dict[str, Any]] = {}
    for replica in ("1", "2", "3"):
        replica_label = f"paired-replica-{replica}"
        replica_path = (
            args.benchmark_results.parent
            / "raw"
            / "benchmarks"
            / f"replica-{replica}.json"
        )
        try:
            document, digest = load_document(replica_path)
        except EvidenceValidationError as error:
            failures.append({"evidence": replica_label, "code": error.code})
        else:
            raw_replicas[replica] = document
            receipt_hashes[replica_label] = digest

        image_label = f"paired-image-data-{replica}"
        image_path = (
            args.benchmark_results.parent
            / "raw"
            / "benchmarks"
            / f"replica-{replica}-imagedata.json"
        )
        try:
            digest = load_performance_image_data(image_path)
        except EvidenceValidationError as error:
            failures.append({"evidence": image_label, "code": error.code})
        else:
            paired_image_digests[replica] = digest
            receipt_hashes[image_label] = digest

    release: VerifiedReleaseArtifacts | None = None
    if not any(failure["evidence"] == "invocation" for failure in failures):
        try:
            release = verify(args.artifacts_dir, args.expected_commit)
        except SystemExit:
            failures.append(
                {"evidence": "release-artifacts", "code": "release_artifacts_invalid"}
            )

    def check(label: str, function: Callable[[], Any]) -> None:
        if label not in documents or release is None:
            return
        try:
            function()
        except EvidenceValidationError as error:
            failures.append({"evidence": label, "code": error.code})
        else:
            validated.append(label)

    if release is not None:
        for label, runtime, version in (
            ("compat-python-3.11", "python", "3.11"),
            ("compat-python-3.14", "python", "3.14"),
            ("compat-node-22", "node", "22"),
            ("compat-node-24", "node", "24"),
        ):
            check(
                label,
                lambda label=label,
                runtime=runtime,
                version=version: validate_compatibility(
                    documents[label],
                    runtime=runtime,
                    version=version,
                    release=release,
                    args=args,
                ),
            )

        check(
            "benchmark-results",
            lambda: validate_paired_benchmark(
                documents["benchmark-results"],
                raw_replicas=raw_replicas,
                runner_image_digests=paired_image_digests,
                release=release,
                args=args,
            ),
        )
        check(
            "soak-results",
            lambda: validate_soak_report(
                documents["soak-results"],
                release=release,
                args=args,
            ),
        )
        if "benchmark-results" in documents and "soak-results" in documents:
            if performance_image_data_digest is not None:
                try:
                    validate_performance_image_data(
                        performance_image_data_digest,
                        documents["soak-results"],
                    )
                except EvidenceValidationError as error:
                    failures.append(
                        {
                            "evidence": "performance-image-data",
                            "code": error.code,
                        }
                    )
                else:
                    validated.append("performance-image-data")
            check(
                "performance-status",
                lambda: validate_performance_status(
                    documents["performance-status"],
                    documents["benchmark-results"],
                    documents["soak-results"],
                    receipt_hashes["soak-results"],
                    release=release,
                    args=args,
                ),
            )
        check(
            "provider-evidence",
            lambda: validate_provider(
                documents["provider-evidence"], release=release, args=args
            ),
        )
        check(
            "tthw-status",
            lambda: validate_tthw_status(
                documents["tthw-status"], release=release, args=args
            ),
        )
        if all(
            label in documents
            for label in (
                "tthw-evidence",
                "compat-python-3.14",
                "compat-node-24",
            )
        ):
            check(
                "tthw-evidence",
                lambda: validate_tthw_raw(
                    documents["tthw-evidence"],
                    python_compatibility=documents["compat-python-3.14"],
                    node_compatibility=documents["compat-node-24"],
                    release=release,
                    args=args,
                ),
            )

    failures.sort(key=lambda item: (item["evidence"], item["code"]))
    conclusion = "passed" if not failures else "failed"
    return {
        "schemaVersion": 1,
        "commit": args.expected_commit,
        "workflowRun": args.workflow_run,
        "workflowRunAttempt": args.workflow_run_attempt,
        "releaseArtifactId": args.release_artifact_id,
        "releaseArtifactDigest": args.release_artifact_digest,
        "releaseManifestSha256": release.manifest_sha256 if release else None,
        "artifactSha256": full_artifact_hashes(release) if release else {},
        "conclusion": conclusion,
        "failureCode": None if not failures else "release_evidence_validation_failed",
        "failures": failures,
        "receiptSha256": dict(sorted(receipt_hashes.items())),
        "validatedEvidence": sorted(validated),
    }


def write_json_atomic(path: Path, document: dict[str, Any]) -> str:
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return rendered


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--release-artifact-id", required=True)
    parser.add_argument("--release-artifact-digest", required=True)
    parser.add_argument("--python-compat-311", type=Path, required=True)
    parser.add_argument("--python-compat-314", type=Path, required=True)
    parser.add_argument("--node-compat-22", type=Path, required=True)
    parser.add_argument("--node-compat-24", type=Path, required=True)
    parser.add_argument("--performance-status", type=Path, required=True)
    parser.add_argument("--benchmark-results", type=Path, required=True)
    parser.add_argument("--soak-results", type=Path, required=True)
    parser.add_argument("--performance-image-data", type=Path, required=True)
    parser.add_argument("--provider-evidence", type=Path, required=True)
    parser.add_argument("--tthw-status", type=Path, required=True)
    parser.add_argument("--tthw-evidence", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = validate(args)
    except Exception:
        summary = {
            "schemaVersion": 1,
            "commit": args.expected_commit,
            "workflowRun": args.workflow_run,
            "workflowRunAttempt": args.workflow_run_attempt,
            "releaseArtifactId": args.release_artifact_id,
            "releaseArtifactDigest": args.release_artifact_digest,
            "releaseManifestSha256": None,
            "artifactSha256": {},
            "conclusion": "failed",
            "failureCode": "release_evidence_validation_failed",
            "failures": [
                {"evidence": "validator", "code": "internal_validation_error"}
            ],
            "receiptSha256": {},
            "validatedEvidence": [],
        }
    rendered = write_json_atomic(args.output, summary)
    print(rendered, end="")
    return 0 if summary["conclusion"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
