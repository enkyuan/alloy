#!/usr/bin/env python3
"""Validate exact-artifact compatibility receipts without release-policy coupling."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, NoReturn


EXPECTED_ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.9.tgz": ("typescript", "0.2.0-beta.9"),
}
PYTHON_COMPATIBILITY_RECEIPT_FIELDS = {
    "artifactSha256",
    "artifacts",
    "commit",
    "conclusion",
    "failureCode",
    "githubPackageProofs",
    "releaseManifestSha256",
    "runtime",
    "schemaVersion",
    "timings",
    "toolchain",
    "workflowRun",
    "workflowRunAttempt",
}
NODE_V2_PASSED_FIELDS = {
    "schemaVersion",
    "executionMode",
    "commit",
    "releaseManifestSha256",
    "artifactSha256",
    "packageArtifact",
    "producerArtifact",
    "runner",
    "invocation",
    "runtime",
    "artifacts",
    "githubPackageProofs",
    "onboardingProofs",
    "timings",
    "toolchain",
    "conclusion",
    "failureCode",
}
NODE_V2_NONPASSED_FIELDS = {
    "schemaVersion",
    "executionMode",
    "commit",
    "releaseManifestSha256",
    "artifactSha256",
    "runtime",
    "artifacts",
    "githubPackageProofs",
    "onboardingProofs",
    "conclusion",
    "failureCode",
    "failedPhase",
    "failureKind",
}
PACKAGE_ARTIFACT_FIELDS = {"name", "size", "sha256"}
PRODUCER_ARTIFACT_FIELDS = {
    "name",
    "id",
    "digest",
    "runId",
    "runAttempt",
    "headSha",
}
RUNNER_FIELDS = {
    "configuredLabel",
    "environment",
    "runnerOS",
    "runnerArch",
    "platformOS",
    "platformArch",
    "imageOS",
    "imageVersion",
}
INVOCATION_FIELDS = {
    "workflowRun",
    "runId",
    "runAttempt",
    "workflowRef",
    "workflowSha",
    "job",
}
ONBOARDING_PHASE_FIELDS = {
    "artifactInstall",
    "scaffoldInit",
    "noKeyRun",
    "echoSetup",
    "echoRun",
    "coldRun",
    "warmRun",
}
ONBOARDING_ASSERTION_FIELDS = {
    "noKeyText",
    "deterministicText",
    "turnIdPresent",
    "finalSequencePositive",
    "echoLifecycle",
    "echoLifecycleCounts",
    "echoToolCallIdentityCount",
    "echoToolCallIdNonempty",
    "echoResult",
    "echoFinalText",
    "forbiddenTerminalEventsAbsent",
    "coldWarmEqual",
}
TOOLCHAIN_FIELDS = {"python", "uv", "node", "npm", "bun", "typescript"}
TIMING_FIELDS = {"coldSetupToOutputMs", "warmRunMs"}
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_RELEASE_MANIFEST_BYTES = 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
TYPESCRIPT_TARBALL = "kaji-sdk-0.2.0-beta.9.tgz"
EXPECTED_MOCK_REPLY = "The mock provider has completed the tool loop."
PROTECTED_WORKFLOW_REFS = {
    "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main",
    "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.9",
}
WORKFLOW_RUN = re.compile(
    r"https://github[.]com/enkyuan/alloy/actions/runs/[1-9][0-9]*"
)
LEGACY_WORKFLOW_RUN = re.compile(r"https?://.+/actions/runs/[1-9][0-9]*")
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
CANONICAL_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,127}")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
NODE_VERSION = re.compile(r"v(?:22|24)[.][0-9]+[.][0-9]+")
FAILURE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
COMMAND_FAILURE_KINDS = {
    "unsupported_host",
    "start",
    "exit",
    "timeout",
    "output_limit",
    "cleanup",
    "capture",
    "shutting_down",
    "unknown",
}
HANDOFF_PHASES = {
    "handoff:npm-install",
    "handoff:bun-install",
    "handoff:typescript57-version",
    "handoff:typescriptCurrent-version",
    "handoff:typescript57-esm",
    "handoff:typescript57-cjs",
    "handoff:typescriptCurrent-esm",
    "handoff:typescriptCurrent-cjs",
    "handoff:npm-github-proof",
    "handoff:bun-github-proof",
    "handoff:archive-list",
    "handoff:archive-types",
    "handoff:archive-extract",
    "handoff:policy-before-token",
    "handoff:node-version",
    "handoff:npm-version",
    "handoff:node-esm",
    "handoff:node-commonjs",
}
STATIC_SMOKE_PHASES = {
    "npm:pack",
    "node:version",
    "npm:version",
    "bun:version",
    "npm:audit",
    "bun:audit",
    "exports:esm",
    "exports:cjs",
    "cli:help",
    "cli:help-cjs",
    "docs:compile-typescript-current",
    "docs:run",
    "workspace:cleanup",
}
MANAGER_SMOKE_PHASE_SUFFIXES = {
    "package-install",
    "bootstrap-install",
    "generated-install",
    "cli-init",
    "cli-owner-conflict",
    "cli-owner-qualified",
    "cli-add",
    "cli-inspect",
    "github-package-proof",
    "cli-list",
    "cli-replay",
    "compile-typescript-5.7",
    "compile-typescript-current",
    "github-types-compiler-version-5.7",
    "github-types-compiler-version-current",
    "github-types-esm-typescript-5.7",
    "github-types-esm-typescript-current",
    "github-types-cjs-typescript-5.7",
    "github-types-cjs-typescript-current",
    "lifecycle-run",
    "failure-history-run",
    "docs-getting-started-run",
    "installed-artifact-echo-run",
    "cold-run",
    "warm-run",
}
SMOKE_PHASES = (
    STATIC_SMOKE_PHASES
    | HANDOFF_PHASES
    | {
        f"{manager}:{suffix}"
        for manager in ("npm", "bun")
        for suffix in MANAGER_SMOKE_PHASE_SUFFIXES
    }
)
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


class EvidenceError(RuntimeError):
    """A closed compatibility receipt or exact-artifact binding failed."""


def fail(location: str, message: str) -> NoReturn:
    raise EvidenceError(f"{location}: {message}")


def pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )


def _stable_bytes(
    path: Path,
    *,
    label: str,
    location: str,
    max_bytes: int | None,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before_path = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_size < 1
            or (max_bytes is not None and before_path.st_size > max_bytes)
        ):
            raise OSError
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not _same_file(before_path, before):
                raise OSError
            encoded = stream.read(-1 if max_bytes is None else max_bytes + 1)
            after = os.fstat(stream.fileno())
        after_path = os.stat(path, follow_symlinks=False)
        if (
            not encoded
            or (max_bytes is not None and len(encoded) > max_bytes)
            or len(encoded) != before.st_size
            or not _same_file(before, after)
            or not _same_file(after, after_path)
        ):
            raise OSError
        return encoded
    except OSError:
        fail(location, f"invalid or unsafe {label}")


def load_stable_bytes(
    path: Path,
    label: str,
    *,
    location: str = "/",
    max_bytes: int | None = None,
) -> bytes:
    """Return one no-follow, same-inode byte snapshot for another validator."""

    return _stable_bytes(
        path,
        label=label,
        location=location,
        max_bytes=max_bytes,
    )


def _json_object(encoded: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError):
        fail("/", f"invalid {label}")
    if not isinstance(document, dict):
        fail("/", f"{label} must be an object")
    return document


def load_json_value_with_sha256(path: Path, label: str) -> tuple[Any, str]:
    encoded = _stable_bytes(
        path,
        label=label,
        location="/",
        max_bytes=MAX_JSON_BYTES,
    )
    try:
        document = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError):
        fail("/", f"invalid {label}")
    return document, hashlib.sha256(encoded).hexdigest()


def load_json_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    document, digest = load_json_value_with_sha256(path, label)
    if not isinstance(document, dict):
        fail("/", f"{label} must be an object")
    return document, digest


def load_json(path: Path, label: str) -> dict[str, Any]:
    return load_json_with_sha256(path, label)[0]


def artifact_identity(path: Path) -> tuple[int, str]:
    encoded = _stable_bytes(
        path,
        label="artifact file",
        location="/artifacts",
        max_bytes=None,
    )
    return len(encoded), hashlib.sha256(encoded).hexdigest()


_artifact_identity = artifact_identity


def sha256(path: Path) -> str:
    return artifact_identity(path)[1]


def _release_manifest_bytes(path: Path) -> bytes:
    return _stable_bytes(
        path,
        label="release manifest",
        location="/",
        max_bytes=MAX_RELEASE_MANIFEST_BYTES,
    )


@dataclass(frozen=True)
class ReleaseIdentity:
    commit: str
    manifest_sha256: str
    artifacts: tuple[Mapping[str, object], ...]


def read_release_identity(
    release_manifest: Path, artifacts_dir: Path
) -> ReleaseIdentity:
    manifest_bytes = _release_manifest_bytes(release_manifest)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _json_object(manifest_bytes, "release manifest")
    commit = manifest.get("commit")
    if not isinstance(commit, str) or COMMIT.fullmatch(commit) is None:
        fail("/commit", "release manifest commit is invalid")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        fail("/artifacts", "release manifest artifact list is missing")
    if any(
        not isinstance(entry, dict) or not isinstance(entry.get("file"), str)
        for entry in entries
    ):
        fail("/artifacts", "release manifest artifact list is invalid")
    manifest_by_name = {entry["file"]: entry for entry in entries}
    if (
        len(entries) != len(EXPECTED_ARTIFACTS)
        or len(manifest_by_name) != len(entries)
        or set(manifest_by_name) != set(EXPECTED_ARTIFACTS)
    ):
        fail("/artifacts", "release manifest artifact names differ")

    rows: list[dict[str, Any]] = []
    for name in sorted(EXPECTED_ARTIFACTS):
        package, version = EXPECTED_ARTIFACTS[name]
        size, artifact_hash = artifact_identity(artifacts_dir / name)
        row = {
            "name": name,
            "package": package,
            "version": version,
            "size": size,
            "sha256": artifact_hash,
        }
        manifest_entry = manifest_by_name[name]
        if any(
            manifest_entry.get(key) != value
            for key, value in {
                "package": package,
                "version": version,
                "commit": commit,
            }.items()
        ):
            fail("/artifacts", "release manifest artifact binding differs")
        if any(manifest_entry.get(key) != row[key] for key in ("size", "sha256")):
            fail("/artifacts", "retained artifact size/hash differs")
        rows.append(row)
    return ReleaseIdentity(commit, manifest_hash, tuple(rows))


def release_identity(
    release_manifest: Path, artifacts_dir: Path
) -> tuple[str, str, list[dict[str, Any]]]:
    identity = read_release_identity(release_manifest, artifacts_dir)
    return (
        identity.commit,
        identity.manifest_sha256,
        [dict(row) for row in identity.artifacts],
    )


def _closed_object(value: Any, fields: set[str], location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        fail(location, "object shape is invalid")
    return value


def _positive_safe_integer(value: Any, location: str) -> int:
    if type(value) is not int or value < 1 or value > MAX_SAFE_INTEGER:
        fail(location, "must be a positive safe integer")
    return value


def _nonnegative_safe_integer(value: Any, location: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER:
        fail(location, "must be a nonnegative safe integer")
    return value


def _compatibility_timing(value: Any, location: str) -> dict[str, int]:
    timing = _closed_object(value, TIMING_FIELDS, location)
    return {
        field: _nonnegative_safe_integer(timing[field], f"{location}/{field}")
        for field in ("coldSetupToOutputMs", "warmRunMs")
    }


def _compatibility_toolchain(
    value: Any,
    *,
    runtime: str,
    runtime_version: str,
    location: str,
    typescript_current: str | None = None,
) -> dict[str, str]:
    toolchain = _closed_object(value, TOOLCHAIN_FIELDS, location)
    if any(
        not isinstance(item, str) or not item or len(item) > 80
        for item in toolchain.values()
    ):
        fail(location, "compatibility toolchain value is invalid")
    if runtime == "python":
        if (
            toolchain["python"] != runtime_version
            or toolchain["uv"] != "0.11.25"
            or any(
                toolchain[field] != "not-used"
                for field in ("node", "npm", "bun", "typescript")
            )
        ):
            fail(location, "Python compatibility toolchain differs")
    else:
        expected_typescript = (
            f"5.7.3 and {typescript_current}"
            if typescript_current is not None
            else None
        )
        if (
            toolchain["python"] != "not-used"
            or toolchain["uv"] != "not-used"
            or toolchain["node"] != runtime_version
            or SEMVER.fullmatch(toolchain["npm"]) is None
            or toolchain["bun"] != "1.3.11"
            or expected_typescript is None
            or toolchain["typescript"] != expected_typescript
            or typescript_current == "5.7.3"
        ):
            fail(location, "Node compatibility toolchain differs")
    return {field: toolchain[field] for field in sorted(TOOLCHAIN_FIELDS)}


def validate_python_compatibility_receipt_v1(
    receipt: dict[str, Any],
    *,
    expected_runtime_version: str,
    commit: str,
    manifest_hash: str,
    artifacts_by_name: dict[str, dict[str, Any]],
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    location = "/compatibility/python"
    if (
        not isinstance(expected_runtime_version, str)
        or not re.fullmatch(r"3[.](?:11|14)", expected_runtime_version)
        or not isinstance(commit, str)
        or COMMIT.fullmatch(commit) is None
        or not isinstance(manifest_hash, str)
        or SHA256.fullmatch(manifest_hash) is None
        or not isinstance(expected_workflow_run, str)
        or LEGACY_WORKFLOW_RUN.fullmatch(expected_workflow_run) is None
        or type(expected_workflow_run_attempt) is not int
        or expected_workflow_run_attempt < 1
        or expected_workflow_run_attempt > MAX_SAFE_INTEGER
    ):
        fail(f"{location}/workflowRun", "expected Python identity is invalid")
    if set(receipt) != PYTHON_COMPATIBILITY_RECEIPT_FIELDS:
        fail(location, "compatibility receipt shape is invalid")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt.get("schemaVersion") != 1
        or receipt.get("conclusion") != "passed"
        or receipt.get("failureCode") is not None
    ):
        fail(location, "compatibility receipt did not pass")
    if receipt.get("commit") != commit:
        fail(f"{location}/commit", "compatibility commit differs")
    if receipt.get("releaseManifestSha256") != manifest_hash:
        fail(
            f"{location}/releaseManifestSha256",
            "compatibility release manifest differs",
        )
    if (
        type(receipt.get("workflowRunAttempt")) is not int
        or receipt.get("workflowRunAttempt") != expected_workflow_run_attempt
    ):
        fail(
            f"{location}/workflowRunAttempt",
            "compatibility workflow run attempt differs",
        )
    if receipt.get("workflowRun") != expected_workflow_run:
        fail(f"{location}/workflowRun", "compatibility workflow run differs")

    runtime = _closed_object(
        receipt.get("runtime"),
        {"implementation", "version", "executable"},
        f"{location}/runtime",
    )
    runtime_version = runtime.get("version")
    if (
        runtime.get("implementation") != "CPython"
        or not isinstance(runtime_version, str)
        or re.fullmatch(
            rf"{re.escape(expected_runtime_version)}[.][0-9]+", runtime_version
        )
        is None
        or not isinstance(runtime.get("executable"), str)
        or not runtime["executable"]
    ):
        fail(
            f"{location}/runtime",
            f"Python {expected_runtime_version} runtime is required",
        )
    artifact_paths = _closed_object(
        receipt.get("artifacts"), {"wheel", "sdist"}, f"{location}/artifacts"
    )
    expected_names = (
        "kaji_sdk-0.2.0b1-py3-none-any.whl",
        "kaji_sdk-0.2.0b1.tar.gz",
    )
    if (
        Path(str(artifact_paths["wheel"])).name != expected_names[0]
        or Path(str(artifact_paths["sdist"])).name != expected_names[1]
    ):
        fail(f"{location}/artifacts", "Python compatibility artifacts differ")
    proofs = _closed_object(
        receipt.get("githubPackageProofs"),
        {"wheel", "sdist"},
        f"{location}/githubPackageProofs",
    )
    if any(not isinstance(proofs[name], dict) for name in ("wheel", "sdist")):
        fail(
            f"{location}/githubPackageProofs",
            "Python compatibility proofs are invalid",
        )
    timings = _closed_object(
        receipt.get("timings"), {"wheel", "sdist"}, f"{location}/timings"
    )
    selected_timings = {
        name: _compatibility_timing(
            timings[name],
            f"{location}/timings/{name}",
        )
        for name in ("wheel", "sdist")
    }
    if any(
        name not in artifacts_by_name
        or not isinstance(artifacts_by_name[name], dict)
        or not isinstance(artifacts_by_name[name].get("sha256"), str)
        or SHA256.fullmatch(artifacts_by_name[name]["sha256"]) is None
        for name in expected_names
    ):
        fail(f"{location}/artifactSha256", "candidate artifact identity is invalid")
    expected_hashes = {
        name: artifacts_by_name[name]["sha256"] for name in expected_names
    }
    if receipt.get("artifactSha256") != expected_hashes:
        fail(f"{location}/artifactSha256", "compatibility artifact hashes differ")
    toolchain = _compatibility_toolchain(
        receipt.get("toolchain"),
        runtime="python",
        runtime_version=runtime_version,
        location=f"{location}/toolchain",
    )
    return selected_timings, toolchain


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
    if not valid:
        fail("/githubPackageProofs", "GitHub package proof is invalid")


def _onboarding_proof(
    value: Any,
    *,
    manager: str,
    location: str,
) -> dict[str, Any]:
    proof = _closed_object(value, {"manager", "phases", "assertions"}, location)
    if proof["manager"] != manager:
        fail(f"{location}/manager", "onboarding manager differs")
    phases = _closed_object(
        proof["phases"], ONBOARDING_PHASE_FIELDS, f"{location}/phases"
    )
    if any(value is not True for value in phases.values()):
        fail(f"{location}/phases", "onboarding phase did not pass")
    assertions = _closed_object(
        proof["assertions"], ONBOARDING_ASSERTION_FIELDS, f"{location}/assertions"
    )
    lifecycle_counts = _closed_object(
        assertions["echoLifecycleCounts"],
        {"requested", "started", "completed"},
        f"{location}/assertions/echoLifecycleCounts",
    )
    echo_result = _closed_object(
        assertions["echoResult"],
        {"message"},
        f"{location}/assertions/echoResult",
    )
    expected = {
        "noKeyText": EXPECTED_MOCK_REPLY,
        "deterministicText": EXPECTED_MOCK_REPLY,
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
        "echoFinalText": EXPECTED_MOCK_REPLY,
        "forbiddenTerminalEventsAbsent": True,
        "coldWarmEqual": True,
    }
    if not _strict_json_equal(assertions, expected):
        fail(f"{location}/assertions", "onboarding assertion did not pass")
    if not _strict_json_equal(lifecycle_counts, expected["echoLifecycleCounts"]):
        fail(
            f"{location}/assertions/echoLifecycleCounts",
            "Echo lifecycle counts differ",
        )
    if not _strict_json_equal(echo_result, expected["echoResult"]):
        fail(f"{location}/assertions/echoResult", "Echo result differs")
    return proof


@dataclass(frozen=True)
class ValidatedNodeReceipt:
    commit: str
    release_manifest_sha256: str
    package_artifact: Mapping[str, object]
    producer_artifact: Mapping[str, object]
    runtime: Mapping[str, object]
    runner: Mapping[str, object]
    invocation: Mapping[str, object]
    onboarding_proofs: Mapping[str, object]
    timings: Mapping[str, Mapping[str, int]]
    toolchain: Mapping[str, str]


def validate_node_compatibility_receipt_v2(
    receipt: dict[str, Any],
    *,
    expected_runtime_version: str,
    commit: str,
    manifest_hash: str,
    artifacts_by_name: dict[str, dict[str, Any]],
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> ValidatedNodeReceipt:
    location = "/compatibility/node"
    if (
        not isinstance(expected_runtime_version, str)
        or expected_runtime_version not in {"22", "24"}
        or not isinstance(commit, str)
        or COMMIT.fullmatch(commit) is None
        or not isinstance(manifest_hash, str)
        or SHA256.fullmatch(manifest_hash) is None
        or not isinstance(expected_workflow_run, str)
        or WORKFLOW_RUN.fullmatch(expected_workflow_run) is None
        or type(expected_workflow_run_attempt) is not int
        or expected_workflow_run_attempt != 1
    ):
        fail(f"{location}/invocation", "expected protected identity is invalid")
    if set(receipt) != NODE_V2_PASSED_FIELDS:
        fail(location, "compatibility receipt shape is invalid")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt.get("schemaVersion") != 2
        or receipt.get("executionMode") != "protected"
        or receipt.get("conclusion") != "passed"
        or receipt.get("failureCode") is not None
    ):
        fail(location, "protected compatibility receipt did not pass")
    if receipt.get("commit") != commit:
        fail(f"{location}/commit", "compatibility commit differs")
    if receipt.get("releaseManifestSha256") != manifest_hash:
        fail(
            f"{location}/releaseManifestSha256",
            "compatibility release manifest differs",
        )

    expected = artifacts_by_name.get(TYPESCRIPT_TARBALL)
    if not isinstance(expected, dict):
        fail(f"{location}/packageArtifact", "candidate artifact identity is missing")
    expected_hash = expected.get("sha256")
    expected_size = expected.get("size")
    if (
        not isinstance(expected_hash, str)
        or SHA256.fullmatch(expected_hash) is None
        or type(expected_size) is not int
        or expected_size < 1
        or expected_size > MAX_SAFE_INTEGER
    ):
        fail(f"{location}/packageArtifact", "candidate artifact identity is invalid")
    if receipt.get("artifactSha256") != {TYPESCRIPT_TARBALL: expected_hash}:
        fail(f"{location}/artifactSha256", "compatibility artifact hashes differ")

    package = _closed_object(
        receipt.get("packageArtifact"),
        PACKAGE_ARTIFACT_FIELDS,
        f"{location}/packageArtifact",
    )
    _positive_safe_integer(package["size"], f"{location}/packageArtifact/size")
    if package != {
        "name": TYPESCRIPT_TARBALL,
        "size": expected_size,
        "sha256": expected_hash,
    }:
        fail(f"{location}/packageArtifact", "package artifact identity differs")

    runtime = _closed_object(receipt.get("runtime"), {"version"}, f"{location}/runtime")
    runtime_version = runtime.get("version")
    if (
        not isinstance(runtime_version, str)
        or re.fullmatch(
            rf"v{re.escape(expected_runtime_version)}[.][0-9]+[.][0-9]+",
            runtime_version,
        )
        is None
        or NODE_VERSION.fullmatch(runtime_version) is None
    ):
        fail(
            f"{location}/runtime",
            f"Node {expected_runtime_version} runtime is required",
        )
    major = int(expected_runtime_version)
    if major not in {22, 24}:
        fail(f"{location}/runtime", "protected Node cell is invalid")

    runner = _closed_object(receipt.get("runner"), RUNNER_FIELDS, f"{location}/runner")
    expected_runner = {
        "configuredLabel": f"ubuntu-{major}.04",
        "environment": "github-hosted",
        "runnerOS": "Linux",
        "runnerArch": "X64",
        "platformOS": "linux",
        "platformArch": "x64",
        "imageOS": f"ubuntu{major}",
    }
    if any(runner.get(field) != value for field, value in expected_runner.items()):
        fail(f"{location}/runner", "protected runner identity differs")
    image_version = runner.get("imageVersion")
    if (
        not isinstance(image_version, str)
        or IMAGE_VERSION.fullmatch(image_version) is None
    ):
        fail(f"{location}/runner/imageVersion", "runner image version is invalid")

    producer = _closed_object(
        receipt.get("producerArtifact"),
        PRODUCER_ARTIFACT_FIELDS,
        f"{location}/producerArtifact",
    )
    invocation = _closed_object(
        receipt.get("invocation"),
        INVOCATION_FIELDS,
        f"{location}/invocation",
    )
    for field in ("id", "runId", "runAttempt"):
        _positive_safe_integer(producer[field], f"{location}/producerArtifact/{field}")
    for field in ("runId", "runAttempt"):
        _positive_safe_integer(invocation[field], f"{location}/invocation/{field}")
    if (
        producer.get("name") != "kaji-beta-artifacts"
        or not isinstance(producer.get("digest"), str)
        or CANONICAL_SHA256.fullmatch(producer["digest"]) is None
        or producer.get("runId") != invocation.get("runId")
        or producer.get("runAttempt") != invocation.get("runAttempt")
        or producer.get("runAttempt") != 1
        or producer.get("headSha") != commit
        or invocation.get("workflowRun") != expected_workflow_run
        or invocation.get("workflowRun")
        != f"https://github.com/enkyuan/alloy/actions/runs/{invocation.get('runId')}"
        or invocation.get("runAttempt") != expected_workflow_run_attempt
        or invocation.get("runAttempt") != 1
        or not isinstance(invocation.get("workflowRef"), str)
        or invocation["workflowRef"] not in PROTECTED_WORKFLOW_REFS
        or invocation.get("workflowSha") != commit
        or invocation.get("job") != "node-compat"
    ):
        fail(
            f"{location}/invocation",
            "protected producer/invocation binding differs",
        )

    artifact_paths = _closed_object(
        receipt.get("artifacts"),
        {"tarball", "package"},
        f"{location}/artifacts",
    )
    if (
        not isinstance(artifact_paths.get("tarball"), str)
        or not artifact_paths["tarball"]
        or Path(artifact_paths["tarball"]).name != TYPESCRIPT_TARBALL
        or not isinstance(artifact_paths.get("package"), str)
        or not artifact_paths["package"]
    ):
        fail(f"{location}/artifacts", "Node compatibility artifacts differ")

    github_proofs = _closed_object(
        receipt.get("githubPackageProofs"),
        {"npm", "bun"},
        f"{location}/githubPackageProofs",
    )
    try:
        validate_github_package_proofs(github_proofs, "typescript")
    except EvidenceError:
        fail(
            f"{location}/githubPackageProofs",
            "Node compatibility proofs are invalid",
        )

    onboarding = _closed_object(
        receipt.get("onboardingProofs"),
        {"npm", "bun"},
        f"{location}/onboardingProofs",
    )
    for manager in ("npm", "bun"):
        _onboarding_proof(
            onboarding[manager],
            manager=manager,
            location=f"{location}/onboardingProofs/{manager}",
        )

    timings = _closed_object(
        receipt.get("timings"), {"npm", "bun"}, f"{location}/timings"
    )
    selected_timings = {
        manager: _compatibility_timing(
            timings[manager], f"{location}/timings/{manager}"
        )
        for manager in ("npm", "bun")
    }
    declarations = github_proofs["npm"]["typescriptDeclarationChecks"]
    current = declarations["typescriptCurrent"]["version"]
    toolchain = _compatibility_toolchain(
        receipt.get("toolchain"),
        runtime="node",
        runtime_version=runtime_version,
        location=f"{location}/toolchain",
        typescript_current=current,
    )
    return ValidatedNodeReceipt(
        commit=commit,
        release_manifest_sha256=manifest_hash,
        package_artifact=dict(package),
        producer_artifact=dict(producer),
        runtime=dict(runtime),
        runner=dict(runner),
        invocation=dict(invocation),
        onboarding_proofs=dict(onboarding),
        timings=selected_timings,
        toolchain=toolchain,
    )


def validate_node_receipt_bindings(
    receipt: ValidatedNodeReceipt,
    *,
    package_artifact: Mapping[str, object],
    producer_artifact: Mapping[str, object],
    runner: Mapping[str, object],
    invocation: Mapping[str, object],
) -> None:
    expected = (
        (receipt.package_artifact, package_artifact, "/packageArtifact"),
        (receipt.producer_artifact, producer_artifact, "/producerArtifact"),
        (receipt.runner, runner, "/runner"),
        (receipt.invocation, invocation, "/invocation"),
    )
    for actual, trusted, location in expected:
        if not _strict_json_equal(actual, trusted):
            fail(location, "compatibility receipt differs from trusted binding")


def validate_protected_node_receipt_source_bindings(
    receipt: ValidatedNodeReceipt,
    *,
    package_artifact: Mapping[str, object],
    producer_artifact: Mapping[str, object],
    static_runner_policy: Mapping[str, object],
    invocation: Mapping[str, object],
) -> None:
    """Bind externally authenticated fields without self-binding imageVersion."""

    static_fields = RUNNER_FIELDS - {"imageVersion"}
    if set(static_runner_policy) != static_fields:
        fail("/runner", "static runner policy shape is invalid")
    expected = (
        (receipt.package_artifact, package_artifact, "/packageArtifact"),
        (receipt.producer_artifact, producer_artifact, "/producerArtifact"),
        (receipt.invocation, invocation, "/invocation"),
    )
    for actual, trusted, location in expected:
        if not _strict_json_equal(actual, trusted):
            fail(location, "compatibility receipt differs from trusted binding")
    observed_static = {
        field: receipt.runner.get(field) for field in sorted(static_fields)
    }
    if not _strict_json_equal(observed_static, static_runner_policy):
        fail("/runner", "compatibility receipt differs from static runner policy")
    image_version = receipt.runner.get("imageVersion")
    if (
        not isinstance(image_version, str)
        or IMAGE_VERSION.fullmatch(image_version) is None
    ):
        fail("/runner/imageVersion", "runner image version is invalid")


def validate_legacy_node_release_bindings(
    receipt: ValidatedNodeReceipt,
    *,
    package_artifact: Mapping[str, object],
    producer_artifact: Mapping[str, object],
    workflow_run: str,
    workflow_run_attempt: int,
    commit: str,
) -> None:
    """Bind only the trusted identity exposed by the staged legacy release CLI."""
    location = "/compatibility/node/legacyReleaseBinding"
    if (
        not isinstance(workflow_run, str)
        or WORKFLOW_RUN.fullmatch(workflow_run) is None
        or type(workflow_run_attempt) is not int
        or workflow_run_attempt < 1
        or workflow_run_attempt > MAX_SAFE_INTEGER
        or not isinstance(commit, str)
        or COMMIT.fullmatch(commit) is None
    ):
        fail(location, "legacy release binding identity is invalid")
    run_id = int(workflow_run.rsplit("/", 1)[1])
    if run_id > MAX_SAFE_INTEGER:
        fail(location, "legacy release binding run ID is invalid")

    expected = (
        (receipt.package_artifact, package_artifact, "/packageArtifact"),
        (receipt.producer_artifact, producer_artifact, "/producerArtifact"),
    )
    for actual, trusted, field_location in expected:
        if not _strict_json_equal(actual, trusted):
            fail(
                f"{location}{field_location}",
                "compatibility receipt differs from trusted legacy binding",
            )

    invocation = receipt.invocation
    if (
        receipt.commit != commit
        or invocation.get("workflowRun") != workflow_run
        or invocation.get("runId") != run_id
        or invocation.get("runAttempt") != workflow_run_attempt
        or invocation.get("workflowSha") != commit
    ):
        fail(location, "compatibility receipt differs from trusted legacy binding")


def validate_node_nonpassed_receipt_v2(
    receipt: dict[str, Any], *, required_mode: str | None = None
) -> None:
    location = "/compatibility/node"
    if set(receipt) != NODE_V2_NONPASSED_FIELDS:
        fail(location, "nonpassed compatibility receipt shape is invalid")
    conclusion = receipt.get("conclusion")
    mode = receipt.get("executionMode")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt.get("schemaVersion") != 2
        or conclusion not in {"failed", "not_run"}
        or mode not in {"protected", "local"}
        or (required_mode is not None and mode != required_mode)
    ):
        fail(location, "nonpassed compatibility identity is invalid")
    commit = receipt.get("commit")
    manifest_hash = receipt.get("releaseManifestSha256")
    if commit is not None and (
        not isinstance(commit, str) or COMMIT.fullmatch(commit) is None
    ):
        fail(f"{location}/commit", "nonpassed compatibility commit is invalid")
    if manifest_hash is not None and (
        not isinstance(manifest_hash, str) or SHA256.fullmatch(manifest_hash) is None
    ):
        fail(
            f"{location}/releaseManifestSha256",
            "nonpassed compatibility manifest is invalid",
        )
    artifact_hashes = receipt.get("artifactSha256")
    if not isinstance(artifact_hashes, dict) or (
        artifact_hashes
        and (
            set(artifact_hashes) != {TYPESCRIPT_TARBALL}
            or not isinstance(artifact_hashes[TYPESCRIPT_TARBALL], str)
            or SHA256.fullmatch(artifact_hashes[TYPESCRIPT_TARBALL]) is None
        )
    ):
        fail(
            f"{location}/artifactSha256",
            "nonpassed compatibility artifact identity is invalid",
        )
    runtime = _closed_object(receipt.get("runtime"), {"version"}, f"{location}/runtime")
    version = runtime["version"]
    if version is not None and (
        not isinstance(version, str) or NODE_VERSION.fullmatch(version) is None
    ):
        fail(f"{location}/runtime", "nonpassed compatibility runtime is invalid")
    for field in ("artifacts", "githubPackageProofs", "onboardingProofs"):
        _closed_object(receipt.get(field), set(), f"{location}/{field}")
    failure_code = receipt.get("failureCode")
    if (
        not isinstance(failure_code, str)
        or FAILURE_CODE.fullmatch(failure_code) is None
    ):
        fail(f"{location}/failureCode", "nonpassed failure code is invalid")
    failed_phase = receipt.get("failedPhase")
    failure_kind = receipt.get("failureKind")
    if failed_phase is not None and (
        not isinstance(failed_phase, str) or failed_phase not in SMOKE_PHASES
    ):
        fail(f"{location}/failedPhase", "nonpassed failure phase is invalid")
    if not isinstance(failure_kind, str) or failure_kind not in COMMAND_FAILURE_KINDS:
        fail(f"{location}/failureKind", "nonpassed failure kind is invalid")
    if conclusion == "not_run" and (
        failed_phase is not None or failure_kind != "unknown"
    ):
        fail(location, "not-run receipt retained a failure execution claim")


def validate_closed_compatibility_receipt(
    receipt: dict[str, Any],
    *,
    runtime: str,
    expected_runtime_version: str,
    commit: str,
    manifest_hash: str,
    artifacts_by_name: dict[str, dict[str, Any]],
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    if runtime == "python":
        return validate_python_compatibility_receipt_v1(
            receipt,
            expected_runtime_version=expected_runtime_version,
            commit=commit,
            manifest_hash=manifest_hash,
            artifacts_by_name=artifacts_by_name,
            expected_workflow_run=expected_workflow_run,
            expected_workflow_run_attempt=expected_workflow_run_attempt,
        )
    if runtime != "node":
        fail("/compatibility", "compatibility runtime is invalid")
    validated = validate_node_compatibility_receipt_v2(
        receipt,
        expected_runtime_version=expected_runtime_version,
        commit=commit,
        manifest_hash=manifest_hash,
        artifacts_by_name=artifacts_by_name,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_run_attempt=expected_workflow_run_attempt,
    )
    return (
        {key: dict(value) for key, value in validated.timings.items()},
        dict(validated.toolchain),
    )
