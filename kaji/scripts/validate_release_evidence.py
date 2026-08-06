#!/usr/bin/env python3
"""Fail closed unless every retained beta receipt names one release run."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping, NoReturn

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
from validate_compatibility_receipts import (
    SEMVER as SEMVER,
    EvidenceError as CompatibilityEvidenceError,
    load_stable_bytes,
    load_json_value_with_sha256,
    validate_github_package_proofs as validate_compatibility_github_package_proofs,
    validate_node_compatibility_receipt_v2,
    validate_python_compatibility_receipt_v1,
)
import validate_typescript_onboarding_evidence as onboarding
from verify_release_artifacts import (
    VerifiedReleaseArtifactBytes,
    verify_release_member_bytes,
)


COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ARTIFACT_ID = re.compile(r"[1-9][0-9]*")
WORKFLOW_RUN = re.compile(
    r"https://github[.]com/enkyuan/alloy/actions/runs/[1-9][0-9]*"
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_SIGNED_EVIDENCE_BYTES = 256 * 1024 * 1024
MAX_SIGNED_EVIDENCE_MEMBER_BYTES = 128 * 1024 * 1024
MAX_SIGNED_TARBALL_BYTES = 128 * 1024 * 1024
MAX_ONBOARDING_STATUS_BYTES = 64 * 1024
MAX_PUBLICATION_STATUS_BYTES = 256 * 1024
IO_CHUNK_BYTES = 1024 * 1024
PYTHON_WHEEL = "kaji_sdk-0.2.0b1-py3-none-any.whl"
PYTHON_SDIST = "kaji_sdk-0.2.0b1.tar.gz"
TYPESCRIPT_TARBALL = "kaji-sdk-0.2.0-beta.11.tgz"
PRODUCER_ARTIFACT = "kaji-beta-artifacts"
EVIDENCE_ARTIFACT = "kaji-release-candidate-evidence"
REHEARSAL_WORKFLOW_PATH = ".github/workflows/kaji.rehearsal.yml"
PUBLISH_WORKFLOW_PATH = ".github/workflows/kaji.publish.yml"
PUBLISH_TAG = "kaji-v0.2.0-beta.11"
NPM_IDENTITY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
WORKFLOW_REFS = {
    "rehearsal": ("enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main"),
    "publish": (
        "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.11"
    ),
}
ONBOARDING_STATUS_KEYS = {
    "schemaVersion",
    "kind",
    "commit",
    "workflowRun",
    "workflowRunAttempt",
    "workflowRef",
    "releaseManifestSha256",
    "aggregateSha256",
    "conclusion",
    "failureCode",
    "exitCode",
}
RELEASE_MEMBERS = {
    PYTHON_WHEEL,
    PYTHON_SDIST,
    TYPESCRIPT_TARBALL,
    "manifest.json",
    "SHA256SUMS",
}
CURRENT_RELEASE_MEMBER_LIMITS = MappingProxyType(
    {
        PYTHON_WHEEL: 128 * 1024 * 1024,
        PYTHON_SDIST: 128 * 1024 * 1024,
        TYPESCRIPT_TARBALL: MAX_SIGNED_TARBALL_BYTES,
        "manifest.json": 256 * 1024,
        "SHA256SUMS": 64 * 1024,
    }
)
SIGNED_EVIDENCE_MEMBERS = {
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
SUMMARY_KEYS = {
    "schemaVersion",
    "mode",
    "commit",
    "workflowRun",
    "workflowRunAttempt",
    "workflowRef",
    "currentArtifact",
    "nodeSourceArtifacts",
    "releaseManifestSha256",
    "artifactSha256",
    "onboardingEvidence",
    "signedSource",
    "conclusion",
    "failureCode",
    "failures",
    "receiptSha256",
    "validatedEvidence",
}
EVIDENCE_PATH_ARGUMENTS = (
    "python_compat_311",
    "python_compat_314",
    "node_compat_22",
    "node_compat_24",
    "performance_status",
    "benchmark_results",
    "soak_results",
    "performance_image_data",
    "provider_evidence",
    "onboarding_status",
    "onboarding_evidence",
)
SIGNED_EVIDENCE_ARGUMENTS = (
    "signed_evidence_archive",
    "signed_evidence_artifact_id",
    "signed_evidence_artifact_digest",
)
SIGNED_ARGUMENTS = (
    "authorization_sha256",
    "rehearsal_run_id",
    "rehearsal_run_attempt",
    "rehearsal_workflow_path",
    "rehearsal_workflow_sha",
    "signed_candidate_archive",
    "signed_candidate_artifact_id",
    "signed_candidate_artifact_digest",
    "signed_evidence_archive",
    "signed_evidence_artifact_id",
    "signed_evidence_artifact_digest",
    "signed_node22_source_artifact_id",
    "signed_node22_source_artifact_digest",
    "signed_node24_source_artifact_id",
    "signed_node24_source_artifact_digest",
    "signed_release_manifest_sha256",
    "signed_npm_tarball_name",
    "signed_npm_tarball_sha256",
    "signed_npm_tarball",
    "rebuilt_npm_tarball",
)
PUBLICATION_STATUS_KEYS = {
    "schemaVersion",
    "target",
    "commit",
    "tag",
    "state",
    "previousState",
    "releaseReady",
    "installRecommendation",
    "registries",
    "publishJobs",
    "registryVerification",
    "incident",
    "workflowRun",
    "workflowRunAttempt",
    "workflowPath",
    "workflowSha",
    "expectedPublisher",
    "publisherIdentity",
}
PUBLISHER_IDENTITY_KEYS = {
    "schemaVersion",
    "commit",
    "tag",
    "workflowRun",
    "workflowRunAttempt",
    "workflowPath",
    "workflowSha",
    "expectedPublisher",
    "actualPublisher",
    "conclusion",
    "exitCode",
    "failureCode",
}


@dataclass(frozen=True)
class SignedEvidenceArchive:
    archive_bytes: bytes
    members: Mapping[str, bytes]
    summary: Mapping[str, Any]
    summary_bytes: bytes


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
        document, digest = load_json_value_with_sha256(path, "release evidence")
    except CompatibilityEvidenceError:
        reject("evidence_invalid_json")
    require(isinstance(document, dict), "evidence_not_object")
    return document, digest


def _reject_nonfinite(_: str) -> NoReturn:
    raise ValueError("nonfinite JSON number")


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def load_strict_document(
    path: Path,
    label: str,
    *,
    max_bytes: int | None = None,
) -> tuple[dict[str, Any], str, bytes]:
    try:
        encoded = load_stable_bytes(
            path,
            label,
            max_bytes=max_bytes,
        )
        document = json.loads(
            encoded,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_closed_pairs,
        )
    except (CompatibilityEvidenceError, UnicodeError, json.JSONDecodeError, ValueError):
        reject("evidence_invalid_json")
    require(isinstance(document, dict), "evidence_not_object")
    return document, hashlib.sha256(encoded).hexdigest(), encoded


def load_strict_document_bytes(
    encoded: bytes,
    *,
    max_bytes: int | None = None,
) -> tuple[dict[str, Any], str, bytes]:
    if type(encoded) is not bytes or (
        max_bytes is not None and len(encoded) > max_bytes
    ):
        reject("evidence_invalid_json")
    try:
        document = json.loads(
            encoded,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_closed_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        reject("evidence_invalid_json")
    require(isinstance(document, dict), "evidence_not_object")
    return document, hashlib.sha256(encoded).hexdigest(), encoded


def load_document_bytes(encoded: bytes) -> tuple[dict[str, Any], str]:
    document, digest, _ = load_strict_document_bytes(encoded)
    return document, digest


def _argument_positive_safe_integer(value: str | None) -> bool:
    if value is None or ARTIFACT_ID.fullmatch(value) is None:
        return False
    return int(value) <= MAX_SAFE_INTEGER


def _bare_artifact_digest(value: str) -> str:
    require(
        ARTIFACT_DIGEST.fullmatch(value) is not None,
        "release_artifact_digest_invalid",
    )
    return value.removeprefix("sha256:")


def _workflow_ref(args: argparse.Namespace) -> str:
    return WORKFLOW_REFS[args.mode]


def _workflow_run_id(args: argparse.Namespace) -> int:
    return int(args.workflow_run.rsplit("/", 1)[1])


def _workflow_run_is_valid(value: str) -> bool:
    return (
        WORKFLOW_RUN.fullmatch(value) is not None
        and int(value.rsplit("/", 1)[1]) <= MAX_SAFE_INTEGER
    )


def load_performance_image_data(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        reject("evidence_missing")
    try:
        encoded = load_stable_bytes(
            path,
            "performance image data",
            max_bytes=MAX_IMAGE_DATA_BYTES,
        )
    except CompatibilityEvidenceError:
        reject("performance_image_data_invalid")
    return hashlib.sha256(encoded).hexdigest()


def load_performance_image_data_bytes(encoded: bytes) -> str:
    require(
        type(encoded) is bytes and len(encoded) <= MAX_IMAGE_DATA_BYTES,
        "performance_image_data_invalid",
    )
    return hashlib.sha256(encoded).hexdigest()


def artifact_member_identity(
    release: VerifiedReleaseArtifactBytes,
    name: str,
) -> tuple[int, str]:
    encoded = release.members[name]
    return len(encoded), hashlib.sha256(encoded).hexdigest()


def _flat_zip_alias(index: int, name: str) -> str:
    prefix = f"member-{index:02d}-"
    suffix = ".bin"
    padding = len(name.encode("ascii")) - len(prefix) - len(suffix)
    require(padding >= 1, "signed_evidence_archive_invalid")
    alias = prefix + ("x" * padding) + suffix
    require(
        len(alias.encode("ascii")) == len(name.encode("ascii")) and "/" not in alias,
        "signed_evidence_archive_invalid",
    )
    return alias


def _flat_signed_evidence_zip(
    encoded: bytes,
) -> tuple[bytes, Mapping[str, str]]:
    require(
        type(encoded) is bytes and 22 <= len(encoded) <= MAX_SIGNED_EVIDENCE_BYTES,
        "signed_evidence_archive_invalid",
    )
    aliases = {
        name: _flat_zip_alias(index, name)
        for index, name in enumerate(sorted(SIGNED_EVIDENCE_MEMBERS))
    }
    try:
        eocd_offset = len(encoded) - 22
        (
            signature,
            disk_number,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
            comment_length,
        ) = struct.unpack_from("<4s4H2LH", encoded, eocd_offset)
        require(
            signature == b"PK\x05\x06"
            and disk_number == 0
            and central_disk == 0
            and disk_entries == total_entries == len(aliases)
            and central_size not in {0, 0xFFFFFFFF}
            and central_offset != 0xFFFFFFFF
            and comment_length == 0
            and central_offset + central_size == eocd_offset,
            "signed_evidence_archive_invalid",
        )
        flattened = bytearray(encoded)
        cursor = central_offset
        central_end = central_offset + central_size
        found: set[str] = set()
        for _ in range(total_entries):
            require(
                cursor + 46 <= central_end
                and encoded[cursor : cursor + 4] == b"PK\x01\x02",
                "signed_evidence_archive_invalid",
            )
            filename_length, extra_length, member_comment_length = struct.unpack_from(
                "<HHH",
                encoded,
                cursor + 28,
            )
            local_offset = struct.unpack_from("<L", encoded, cursor + 42)[0]
            filename_start = cursor + 46
            filename_end = filename_start + filename_length
            record_end = filename_end + extra_length + member_comment_length
            require(record_end <= central_end, "signed_evidence_archive_invalid")
            raw_name = encoded[filename_start:filename_end]
            name = raw_name.decode("ascii")
            require(
                name in aliases and name not in found,
                "signed_evidence_archive_invalid",
            )
            alias = aliases[name].encode("ascii")
            require(len(alias) == filename_length, "signed_evidence_archive_invalid")
            require(
                local_offset + 30 <= central_offset
                and encoded[local_offset : local_offset + 4] == b"PK\x03\x04",
                "signed_evidence_archive_invalid",
            )
            local_name_length, local_extra_length = struct.unpack_from(
                "<HH",
                encoded,
                local_offset + 26,
            )
            local_name_start = local_offset + 30
            local_name_end = local_name_start + local_name_length
            require(
                local_name_length == filename_length
                and local_name_end + local_extra_length <= central_offset
                and encoded[local_name_start:local_name_end] == raw_name,
                "signed_evidence_archive_invalid",
            )
            flattened[filename_start:filename_end] = alias
            flattened[local_name_start:local_name_end] = alias
            found.add(name)
            cursor = record_end
        require(
            cursor == central_end and found == set(aliases),
            "signed_evidence_archive_invalid",
        )
    except EvidenceValidationError:
        raise
    except (IndexError, KeyError, UnicodeError, struct.error, ValueError):
        reject("signed_evidence_archive_invalid")
    return bytes(flattened), MappingProxyType(aliases)


def _load_exact_signed_evidence_members(encoded: bytes) -> Mapping[str, bytes]:
    flattened, aliases = _flat_signed_evidence_zip(encoded)
    try:
        flat_members = onboarding._zip_members(
            flattened,
            expected_names=set(aliases.values()),
            archive_limit=MAX_SIGNED_EVIDENCE_BYTES,
            member_limit=MAX_SIGNED_EVIDENCE_MEMBER_BYTES,
            location="/signedEvidence",
        )
    except onboarding.EvidenceError:
        reject("signed_evidence_archive_invalid")
    return MappingProxyType(
        {name: flat_members[alias] for name, alias in sorted(aliases.items())}
    )


def load_signed_evidence_archive(args: argparse.Namespace) -> SignedEvidenceArchive:
    try:
        encoded = load_stable_bytes(
            args.signed_evidence_archive,
            "signed evidence archive",
            max_bytes=MAX_SIGNED_EVIDENCE_BYTES,
        )
    except CompatibilityEvidenceError:
        reject("signed_evidence_archive_invalid")
    require(
        hashlib.sha256(encoded).hexdigest()
        == _bare_artifact_digest(args.signed_evidence_artifact_digest),
        "signed_evidence_digest_mismatch",
    )
    members = _load_exact_signed_evidence_members(encoded)
    summary_bytes = members["release-evidence-validation.json"]
    try:
        summary, _, _ = load_strict_document_bytes(summary_bytes)
    except EvidenceValidationError:
        reject("signed_evidence_summary_invalid")
    require(
        set(summary) == SUMMARY_KEYS
        and type(summary.get("schemaVersion")) is int
        and summary["schemaVersion"] == 2
        and summary.get("mode") == "rehearsal"
        and summary.get("signedSource") is None
        and summary.get("conclusion") == "passed"
        and summary.get("failureCode") is None
        and summary.get("failures") == []
        and json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        == summary_bytes,
        "signed_evidence_summary_invalid",
    )
    return SignedEvidenceArchive(
        archive_bytes=bytes(encoded),
        members=members,
        summary=MappingProxyType(summary),
        summary_bytes=bytes(summary_bytes),
    )


def _strict_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _strict_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def validate_signed_evidence_summary(
    archive: SignedEvidenceArchive,
    *,
    release: VerifiedReleaseArtifactBytes,
    workflow_run: str,
    candidate_artifact_id: str,
    candidate_artifact_digest: str,
    node22_artifact_id: str,
    node22_artifact_digest: str,
    node24_artifact_id: str,
    node24_artifact_digest: str,
    expected_commit: str,
) -> None:
    members = archive.members

    def member_sha256(name: str) -> str:
        return hashlib.sha256(members[name]).hexdigest()

    try:
        aggregate, _, _ = load_strict_document_bytes(
            members["typescript-onboarding/typescript-onboarding-evidence.json"],
            max_bytes=onboarding.MAX_DESTINATION_BYTES,
        )
        onboarding.validate_document(aggregate)
    except (EvidenceValidationError, onboarding.EvidenceError):
        reject("signed_evidence_summary_mismatch")
    run_id = int(workflow_run.rsplit("/", 1)[1])
    expected_producer = {
        "name": PRODUCER_ARTIFACT,
        "id": int(candidate_artifact_id),
        "digest": candidate_artifact_digest,
        "runId": run_id,
        "runAttempt": 1,
        "headSha": expected_commit,
    }
    expected_node_sources = (
        {
            "name": "kaji-node-compat-22",
            "id": int(node22_artifact_id),
            "digest": node22_artifact_digest,
            "runId": run_id,
            "runAttempt": 1,
            "headSha": expected_commit,
            "receiptSha256": member_sha256("compat-node-22.json"),
        },
        {
            "name": "kaji-node-compat-24",
            "id": int(node24_artifact_id),
            "digest": node24_artifact_digest,
            "runId": run_id,
            "runAttempt": 1,
            "headSha": expected_commit,
            "receiptSha256": member_sha256("compat-node-24.json"),
        },
    )
    cells = aggregate.get("cells")
    require(
        _strict_equal(aggregate.get("producerArtifact"), expected_producer)
        and aggregate.get("commit") == expected_commit
        and aggregate.get("releaseManifestSha256") == release.manifest_sha256
        and isinstance(cells, list)
        and len(cells) == 2
        and all(
            isinstance(cell, dict)
            and _strict_equal(cell.get("sourceArtifact"), expected_source)
            for cell, expected_source in zip(
                cells,
                expected_node_sources,
                strict=True,
            )
        ),
        "signed_evidence_summary_mismatch",
    )

    expected_receipts = {
        "benchmark-results": member_sha256("paired-benchmark-results.json"),
        "compat-node-22": member_sha256("compat-node-22.json"),
        "compat-node-24": member_sha256("compat-node-24.json"),
        "compat-python-3.11": member_sha256("compat-python-3.11.json"),
        "compat-python-3.14": member_sha256("compat-python-3.14.json"),
        "node22-source-archive": _bare_artifact_digest(node22_artifact_digest),
        "node24-source-archive": _bare_artifact_digest(node24_artifact_digest),
        "onboarding-evidence": member_sha256(
            "typescript-onboarding/typescript-onboarding-evidence.json"
        ),
        "onboarding-status": member_sha256("typescript-onboarding/status.json"),
        "paired-image-data-1": member_sha256("raw/benchmarks/replica-1-imagedata.json"),
        "paired-image-data-2": member_sha256("raw/benchmarks/replica-2-imagedata.json"),
        "paired-image-data-3": member_sha256("raw/benchmarks/replica-3-imagedata.json"),
        "paired-replica-1": member_sha256("raw/benchmarks/replica-1.json"),
        "paired-replica-2": member_sha256("raw/benchmarks/replica-2.json"),
        "paired-replica-3": member_sha256("raw/benchmarks/replica-3.json"),
        "performance-image-data": member_sha256("performance-imagedata.json"),
        "performance-status": member_sha256("performance-status.json"),
        "producer-archive": _bare_artifact_digest(candidate_artifact_digest),
        "provider-evidence": member_sha256("provider-evidence.json"),
        "soak-results": member_sha256("soak-results.json"),
    }
    expected_onboarding = {
        "aggregateSha256": member_sha256(
            "typescript-onboarding/typescript-onboarding-evidence.json"
        ),
        "nodeReceiptSha256": {
            "22": member_sha256("compat-node-22.json"),
            "24": member_sha256("compat-node-24.json"),
        },
        "recomputedAggregateSha256": member_sha256(
            "typescript-onboarding/typescript-onboarding-evidence.json"
        ),
        "releaseManifestSha256": release.manifest_sha256,
        "statusSha256": member_sha256("typescript-onboarding/status.json"),
    }
    expected_fields = {
        "artifactSha256": full_artifact_hashes(release),
        "commit": expected_commit,
        "currentArtifact": {
            "digest": candidate_artifact_digest,
            "id": int(candidate_artifact_id),
            "name": PRODUCER_ARTIFACT,
        },
        "nodeSourceArtifacts": {
            "22": {
                "digest": node22_artifact_digest,
                "id": int(node22_artifact_id),
                "name": "kaji-node-compat-22",
            },
            "24": {
                "digest": node24_artifact_digest,
                "id": int(node24_artifact_id),
                "name": "kaji-node-compat-24",
            },
        },
        "onboardingEvidence": expected_onboarding,
        "receiptSha256": dict(sorted(expected_receipts.items())),
        "releaseManifestSha256": release.manifest_sha256,
        "validatedEvidence": [
            "benchmark-results",
            "compat-node-22",
            "compat-node-24",
            "compat-python-3.11",
            "compat-python-3.14",
            "node22-source-archive",
            "node24-source-archive",
            "onboarding-evidence",
            "onboarding-status",
            "performance-image-data",
            "performance-status",
            "producer-archive",
            "provider-evidence",
            "soak-results",
        ],
        "workflowRef": WORKFLOW_REFS["rehearsal"],
        "workflowRun": workflow_run,
        "workflowRunAttempt": 1,
    }
    require(
        all(
            _strict_equal(archive.summary.get(key), expected)
            for key, expected in expected_fields.items()
        ),
        "signed_evidence_summary_mismatch",
    )


def full_artifact_hashes(release: VerifiedReleaseArtifactBytes) -> dict[str, str]:
    return dict(sorted(release.artifact_sha256.items()))


def runtime_artifacts(release: VerifiedReleaseArtifactBytes) -> dict[str, Any]:
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
        type(document.get("workflowRunAttempt")) is int
        and document["workflowRunAttempt"] == args.workflow_run_attempt,
        "workflow_run_attempt_mismatch",
    )


def validate_passed_receipt(document: dict[str, Any], args: argparse.Namespace) -> None:
    require(
        type(document.get("schemaVersion")) is int and document["schemaVersion"] == 1,
        "schema_mismatch",
    )
    require(document.get("commit") == args.expected_commit, "commit_mismatch")
    validate_run_identity(document, args)
    require(
        document.get("conclusion") == "passed" and document.get("failureCode") is None,
        "receipt_not_passed",
    )


def validate_manifest(
    document: dict[str, Any], release: VerifiedReleaseArtifactBytes
) -> None:
    require(
        document.get("releaseManifestSha256") == release.manifest_sha256,
        "manifest_hash_mismatch",
    )


def validate_github_package_proofs(value: Any, runtime: str) -> None:
    try:
        validate_compatibility_github_package_proofs(value, runtime)
    except CompatibilityEvidenceError:
        reject("github_package_proof_invalid")


def validate_compatibility(
    document: dict[str, Any],
    *,
    runtime: str,
    version: str,
    release: VerifiedReleaseArtifactBytes,
    args: argparse.Namespace,
) -> None:
    if runtime == "python":
        validate_passed_receipt(document, args)
        validate_manifest(document, release)
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
            validate_python_compatibility_receipt_v1(
                document,
                expected_runtime_version=version,
                commit=args.expected_commit,
                manifest_hash=release.manifest_sha256,
                artifacts_by_name={
                    name: {"sha256": digest} for name, digest in expected_hashes.items()
                },
                expected_workflow_run=args.workflow_run,
                expected_workflow_run_attempt=args.workflow_run_attempt,
            )
        except CompatibilityEvidenceError:
            reject("compatibility_receipt_invalid")
        return

    validate_github_package_proofs(document.get("githubPackageProofs"), "typescript")
    try:
        tarball_size, tarball_sha256 = artifact_member_identity(
            release,
            TYPESCRIPT_TARBALL,
        )
        validate_node_compatibility_receipt_v2(
            document,
            expected_runtime_version=version,
            commit=args.expected_commit,
            manifest_hash=release.manifest_sha256,
            artifacts_by_name={
                TYPESCRIPT_TARBALL: {
                    "size": tarball_size,
                    "sha256": tarball_sha256,
                }
            },
            expected_workflow_run=args.workflow_run,
            expected_workflow_run_attempt=args.workflow_run_attempt,
        )
    except CompatibilityEvidenceError:
        reject("compatibility_receipt_invalid")
    artifacts = document["artifacts"]
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


def paired_artifacts(release: VerifiedReleaseArtifactBytes) -> dict[str, Any]:
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
    release: VerifiedReleaseArtifactBytes,
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
            and SHA256.fullmatch(receipt["reportReceiptSha256"]) is not None,
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
    release: VerifiedReleaseArtifactBytes,
    args: argparse.Namespace,
) -> dict[str, str]:
    require(
        type(document.get("schemaVersion")) is int and document["schemaVersion"] == 1,
        "schema_mismatch",
    )
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
    release: VerifiedReleaseArtifactBytes,
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
        document.get("releaseArtifactDigest")
        == _bare_artifact_digest(args.release_artifact_digest),
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
    release: VerifiedReleaseArtifactBytes,
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
        document.get("releaseArtifactDigest")
        == _bare_artifact_digest(args.release_artifact_digest),
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


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_current_release_member(
    directory_descriptor: int,
    name: str,
    *,
    limit: int,
    seen_inodes: set[tuple[int, int]],
) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        reject("current_carrier_unsafe")
    try:
        named_before = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        require(
            stat.S_ISREG(named_before.st_mode)
            and named_before.st_nlink == 1
            and 1 <= named_before.st_size <= limit,
            "current_carrier_unsafe",
        )
        identity = (named_before.st_dev, named_before.st_ino)
        require(identity not in seen_inodes, "current_carrier_unsafe")
        flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        try:
            opened_before = os.fstat(descriptor)
            require(
                _stat_identity(opened_before) == _stat_identity(named_before)
                and stat.S_ISREG(opened_before.st_mode)
                and opened_before.st_nlink == 1,
                "current_carrier_unsafe",
            )
            output = bytearray()
            while True:
                chunk = os.read(
                    descriptor,
                    min(IO_CHUNK_BYTES, limit + 1 - len(output)),
                )
                if not chunk:
                    break
                output.extend(chunk)
                require(len(output) <= limit, "current_carrier_unsafe")
            opened_after = os.fstat(descriptor)
            require(
                _stat_identity(opened_after) == _stat_identity(opened_before)
                and len(output) == opened_after.st_size,
                "current_carrier_unsafe",
            )
        finally:
            os.close(descriptor)
        named_after = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        require(
            _stat_identity(named_after) == _stat_identity(named_before),
            "current_carrier_unsafe",
        )
    except EvidenceValidationError:
        raise
    except (OSError, TypeError, ValueError):
        reject("current_carrier_unsafe")
    seen_inodes.add(identity)
    return bytes(output)


def load_current_release_snapshot(
    artifacts_dir: Path,
    *,
    producer_release: VerifiedReleaseArtifactBytes,
    expected_commit: str,
) -> VerifiedReleaseArtifactBytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        reject("current_carrier_unsafe")
    directory_descriptor: int | None = None
    try:
        named_before = artifacts_dir.lstat()
        require(
            stat.S_ISDIR(named_before.st_mode),
            "current_carrier_unsafe",
        )
        directory_descriptor = os.open(
            artifacts_dir,
            os.O_RDONLY | directory_flag | nofollow | getattr(os, "O_CLOEXEC", 0),
        )
        opened_before = os.fstat(directory_descriptor)
        require(
            stat.S_ISDIR(opened_before.st_mode)
            and opened_before.st_dev == named_before.st_dev
            and opened_before.st_ino == named_before.st_ino
            and opened_before.st_mode == named_before.st_mode,
            "current_carrier_unsafe",
        )
        inventory_before = os.listdir(directory_descriptor)
        require(
            len(inventory_before) == len(set(inventory_before))
            and set(inventory_before) == RELEASE_MEMBERS,
            "current_carrier_unsafe",
        )
        seen_inodes: set[tuple[int, int]] = set()
        members = {
            name: _read_current_release_member(
                directory_descriptor,
                name,
                limit=CURRENT_RELEASE_MEMBER_LIMITS[name],
                seen_inodes=seen_inodes,
            )
            for name in sorted(RELEASE_MEMBERS)
        }
        inventory_after = os.listdir(directory_descriptor)
        opened_after = os.fstat(directory_descriptor)
        named_after = artifacts_dir.lstat()
        require(
            inventory_after == inventory_before
            and _stat_identity(opened_after) == _stat_identity(opened_before)
            and named_after.st_dev == named_before.st_dev
            and named_after.st_ino == named_before.st_ino
            and named_after.st_mode == named_before.st_mode
            and named_after.st_mtime_ns == named_before.st_mtime_ns
            and named_after.st_ctime_ns == named_before.st_ctime_ns,
            "current_carrier_unsafe",
        )
    except EvidenceValidationError:
        raise
    except (OSError, TypeError, ValueError):
        reject("current_carrier_unsafe")
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
    try:
        current_release = verify_release_member_bytes(members, expected_commit)
    except SystemExit:
        reject("current_carrier_unsafe")
    require(
        set(current_release.members) == set(producer_release.members)
        and all(
            current_release.members[name] == producer_release.members[name]
            for name in current_release.members
        ),
        "current_carrier_mismatch",
    )
    return current_release


def load_current_archives(
    args: argparse.Namespace,
) -> tuple[Any, Any, Any, dict[str, str]]:
    try:
        producer = onboarding.load_authenticated_archive(
            args.producer_archive,
            name=PRODUCER_ARTIFACT,
            artifact_id=int(args.release_artifact_id),
            digest=args.release_artifact_digest,
            run_id=_workflow_run_id(args),
            run_attempt=1,
            head_sha=args.expected_commit,
            expired=False,
        )
        node22 = onboarding.load_authenticated_archive(
            args.node22_source_archive,
            name="kaji-node-compat-22",
            artifact_id=int(args.node22_source_artifact_id),
            digest=args.node22_source_artifact_digest,
            run_id=_workflow_run_id(args),
            run_attempt=1,
            head_sha=args.expected_commit,
            expired=False,
        )
        node24 = onboarding.load_authenticated_archive(
            args.node24_source_archive,
            name="kaji-node-compat-24",
            artifact_id=int(args.node24_source_artifact_id),
            digest=args.node24_source_artifact_digest,
            run_id=_workflow_run_id(args),
            run_attempt=1,
            head_sha=args.expected_commit,
            expired=False,
        )
    except (onboarding.EvidenceError, OSError, TypeError, ValueError):
        reject("onboarding_archive_invalid")
    return (
        producer,
        node22,
        node24,
        {
            "producer-archive": hashlib.sha256(producer.archive_bytes).hexdigest(),
            "node22-source-archive": hashlib.sha256(node22.archive_bytes).hexdigest(),
            "node24-source-archive": hashlib.sha256(node24.archive_bytes).hexdigest(),
        },
    )


def validate_onboarding_evidence(
    status: dict[str, Any],
    status_sha256: str,
    aggregate: dict[str, Any],
    aggregate_sha256: str,
    aggregate_bytes: bytes,
    *,
    archives: tuple[Any, Any, Any],
    node_receipt_sha256: dict[str, str],
    release: VerifiedReleaseArtifactBytes,
    args: argparse.Namespace,
) -> dict[str, Any]:
    require(set(status) == ONBOARDING_STATUS_KEYS, "onboarding_status_invalid")
    require(
        type(status.get("schemaVersion")) is int and status["schemaVersion"] == 1,
        "onboarding_status_invalid",
    )
    require(
        status.get("kind") == "kaji-typescript-onboarding-status",
        "onboarding_status_invalid",
    )
    require(status.get("commit") == args.expected_commit, "commit_mismatch")
    require(status.get("workflowRun") == args.workflow_run, "workflow_run_mismatch")
    require(
        type(status.get("workflowRunAttempt")) is int
        and status["workflowRunAttempt"] == 1,
        "workflow_run_attempt_mismatch",
    )
    require(
        status.get("workflowRef") == _workflow_ref(args),
        "workflow_ref_mismatch",
    )
    require(
        status.get("releaseManifestSha256") == release.manifest_sha256,
        "manifest_hash_mismatch",
    )
    require(
        isinstance(status.get("aggregateSha256"), str)
        and SHA256.fullmatch(status["aggregateSha256"]) is not None
        and status["aggregateSha256"] == aggregate_sha256,
        "onboarding_aggregate_hash_mismatch",
    )
    require(
        status.get("conclusion") == "passed"
        and status.get("failureCode") is None
        and type(status.get("exitCode")) is int
        and status["exitCode"] == 0,
        "onboarding_status_not_passed",
    )
    require(
        aggregate_bytes
        == json.dumps(aggregate, indent=2, sort_keys=True).encode("utf-8"),
        "onboarding_aggregate_bytes_invalid",
    )

    producer, node22, node24 = archives
    try:
        onboarding.validate_document(aggregate)
        onboarding.recompute_and_compare(
            aggregate,
            producer_archive=producer,
            node22_archive=node22,
            node24_archive=node24,
            expected_workflow_run=args.workflow_run,
            expected_workflow_ref=_workflow_ref(args),
            expected_workflow_sha=args.expected_commit,
        )
    except (onboarding.EvidenceError, KeyError, TypeError, ValueError):
        reject("onboarding_evidence_invalid")

    require(
        aggregate.get("commit") == args.expected_commit,
        "commit_mismatch",
    )
    require(
        aggregate.get("releaseManifestSha256") == release.manifest_sha256,
        "manifest_hash_mismatch",
    )
    require(
        aggregate.get("producerArtifact")
        == {
            "name": PRODUCER_ARTIFACT,
            "id": int(args.release_artifact_id),
            "digest": args.release_artifact_digest,
            "runId": _workflow_run_id(args),
            "runAttempt": 1,
            "headSha": args.expected_commit,
        },
        "producer_artifact_mismatch",
    )
    package = aggregate.get("packageArtifact")
    carrier_size, carrier_sha256 = artifact_member_identity(
        release,
        TYPESCRIPT_TARBALL,
    )
    require(
        isinstance(package, dict)
        and package.get("name") == TYPESCRIPT_TARBALL
        and package.get("sha256") == carrier_sha256
        and package.get("size") == carrier_size,
        "artifact_hash_mismatch",
    )
    cells = aggregate.get("cells")
    if not isinstance(cells, list) or len(cells) != 2:
        reject("onboarding_evidence_invalid")
    expected_sources = (
        (
            22,
            int(args.node22_source_artifact_id),
            args.node22_source_artifact_digest,
        ),
        (
            24,
            int(args.node24_source_artifact_id),
            args.node24_source_artifact_digest,
        ),
    )
    for index, (major, artifact_id, digest) in enumerate(expected_sources):
        cell = cells[index]
        if not isinstance(cell, dict):
            reject("onboarding_evidence_invalid")
        source = cell.get("sourceArtifact")
        require(
            isinstance(source, dict)
            and source.get("name") == f"kaji-node-compat-{major}"
            and source.get("id") == artifact_id
            and source.get("digest") == digest,
            "node_source_artifact_mismatch",
        )
        require(
            source.get("receiptSha256") == node_receipt_sha256[str(major)],
            "node_receipt_hash_mismatch",
        )
    return {
        "statusSha256": status_sha256,
        "aggregateSha256": aggregate_sha256,
        "recomputedAggregateSha256": hashlib.sha256(
            json.dumps(aggregate, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "releaseManifestSha256": release.manifest_sha256,
        "nodeReceiptSha256": dict(sorted(node_receipt_sha256.items())),
    }


def _verified_archive_release(
    archive: Any,
    expected_commit: str,
    *,
    error_code: str = "signed_candidate_invalid",
) -> VerifiedReleaseArtifactBytes:
    try:
        members = onboarding._authenticate_archive(
            archive,
            expected_name=PRODUCER_ARTIFACT,
            location="/producer",
        )
        return verify_release_member_bytes(members, expected_commit)
    except (
        onboarding.EvidenceError,
        OSError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        SystemExit,
    ):
        reject(error_code)


def _validate_authorization_digest(args: argparse.Namespace) -> None:
    authorization = {
        "schemaVersion": "1.0.0",
        "commit": args.expected_commit,
        "rehearsal": {
            "runId": int(args.rehearsal_run_id),
            "runAttempt": 1,
            "workflowPath": REHEARSAL_WORKFLOW_PATH,
            "workflowSha": args.expected_commit,
        },
        "candidateArtifact": {
            "id": int(args.signed_candidate_artifact_id),
            "name": PRODUCER_ARTIFACT,
            "digest": args.signed_candidate_artifact_digest,
        },
        "evidenceArtifact": {
            "id": int(args.signed_evidence_artifact_id),
            "name": EVIDENCE_ARTIFACT,
            "digest": args.signed_evidence_artifact_digest,
        },
        "releaseManifestSha256": args.signed_release_manifest_sha256,
        "npmTarball": {
            "name": TYPESCRIPT_TARBALL,
            "sha256": args.signed_npm_tarball_sha256,
        },
    }
    encoded = (
        json.dumps(
            authorization,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    require(
        hashlib.sha256(encoded).hexdigest() == args.authorization_sha256,
        "authorization_digest_mismatch",
    )


def validate_signed_source(
    args: argparse.Namespace,
    release: VerifiedReleaseArtifactBytes,
) -> tuple[dict[str, Any], dict[str, str]]:
    _validate_authorization_digest(args)
    try:
        signed_candidate = onboarding.load_authenticated_archive(
            args.signed_candidate_archive,
            name=PRODUCER_ARTIFACT,
            artifact_id=int(args.signed_candidate_artifact_id),
            digest=args.signed_candidate_artifact_digest,
            run_id=int(args.rehearsal_run_id),
            run_attempt=1,
            head_sha=args.expected_commit,
            expired=False,
        )
    except (onboarding.EvidenceError, OSError, TypeError, ValueError):
        reject("signed_candidate_invalid")
    signed_release = _verified_archive_release(
        signed_candidate,
        args.expected_commit,
    )
    signed_evidence = load_signed_evidence_archive(args)
    validate_signed_evidence_summary(
        signed_evidence,
        release=signed_release,
        workflow_run=(
            f"https://github.com/enkyuan/alloy/actions/runs/{args.rehearsal_run_id}"
        ),
        candidate_artifact_id=args.signed_candidate_artifact_id,
        candidate_artifact_digest=args.signed_candidate_artifact_digest,
        node22_artifact_id=args.signed_node22_source_artifact_id,
        node22_artifact_digest=args.signed_node22_source_artifact_digest,
        node24_artifact_id=args.signed_node24_source_artifact_id,
        node24_artifact_digest=args.signed_node24_source_artifact_digest,
        expected_commit=args.expected_commit,
    )
    try:
        signed_npm_bytes = load_stable_bytes(
            args.signed_npm_tarball,
            "signed npm tarball",
            max_bytes=MAX_SIGNED_TARBALL_BYTES,
        )
        rebuilt_npm_bytes = load_stable_bytes(
            args.rebuilt_npm_tarball,
            "rebuilt npm tarball",
            max_bytes=MAX_SIGNED_TARBALL_BYTES,
        )
    except CompatibilityEvidenceError:
        reject("signed_source_invalid")

    carrier_npm_bytes = release.members[TYPESCRIPT_TARBALL]
    signed_evidence_sha256 = hashlib.sha256(signed_evidence.archive_bytes).hexdigest()
    signed_npm_sha256 = hashlib.sha256(signed_npm_bytes).hexdigest()
    require(
        "sha256:" + signed_evidence_sha256 == args.signed_evidence_artifact_digest,
        "signed_evidence_digest_mismatch",
    )
    require(
        signed_release.manifest_sha256 == args.signed_release_manifest_sha256
        and signed_release.manifest_sha256 == release.manifest_sha256,
        "signed_manifest_mismatch",
    )
    require(
        set(signed_release.members) == set(release.members)
        and all(
            signed_release.members[name] == release.members[name]
            for name in signed_release.members
        ),
        "current_carrier_mismatch",
    )
    require(
        signed_release.artifact_sha256[TYPESCRIPT_TARBALL]
        == args.signed_npm_tarball_sha256
        and signed_npm_sha256 == args.signed_npm_tarball_sha256,
        "signed_npm_hash_mismatch",
    )
    require(
        signed_release.members[TYPESCRIPT_TARBALL] == signed_npm_bytes,
        "signed_npm_source_mismatch",
    )
    require(
        signed_npm_bytes == rebuilt_npm_bytes,
        "rebuilt_npm_mismatch",
    )
    require(
        signed_npm_bytes == carrier_npm_bytes,
        "current_carrier_mismatch",
    )
    return (
        {
            "authorizationSha256": args.authorization_sha256,
            "rehearsal": {
                "runId": int(args.rehearsal_run_id),
                "runAttempt": 1,
                "workflowPath": REHEARSAL_WORKFLOW_PATH,
                "workflowSha": args.expected_commit,
            },
            "candidateArtifact": {
                "id": int(args.signed_candidate_artifact_id),
                "name": PRODUCER_ARTIFACT,
                "digest": args.signed_candidate_artifact_digest,
            },
            "evidenceArtifact": {
                "id": int(args.signed_evidence_artifact_id),
                "name": EVIDENCE_ARTIFACT,
                "digest": args.signed_evidence_artifact_digest,
            },
            "releaseManifestSha256": args.signed_release_manifest_sha256,
            "npmTarball": {
                "name": TYPESCRIPT_TARBALL,
                "sha256": args.signed_npm_tarball_sha256,
            },
            "sourceRebuildCarrierEqual": True,
        },
        {
            "signed-candidate-archive": hashlib.sha256(
                signed_candidate.archive_bytes
            ).hexdigest(),
            "signed-evidence-archive": signed_evidence_sha256,
            "signed-npm-tarball": signed_npm_sha256,
            "rebuilt-npm-tarball": hashlib.sha256(rebuilt_npm_bytes).hexdigest(),
            "current-carrier-npm-tarball": hashlib.sha256(
                carrier_npm_bytes
            ).hexdigest(),
        },
    )


def input_paths(args: argparse.Namespace) -> dict[str, Path]:
    paths = {
        "compat-python-3.11": args.python_compat_311,
        "compat-python-3.14": args.python_compat_314,
        "compat-node-22": args.node_compat_22,
        "compat-node-24": args.node_compat_24,
        "performance-status": args.performance_status,
        "benchmark-results": args.benchmark_results,
        "soak-results": args.soak_results,
        "provider-evidence": args.provider_evidence,
    }
    require(all(isinstance(path, Path) for path in paths.values()), "evidence_missing")
    return paths


def input_member_names() -> dict[str, str]:
    return {
        "compat-python-3.11": "compat-python-3.11.json",
        "compat-python-3.14": "compat-python-3.14.json",
        "compat-node-22": "compat-node-22.json",
        "compat-node-24": "compat-node-24.json",
        "performance-status": "performance-status.json",
        "benchmark-results": "paired-benchmark-results.json",
        "soak-results": "soak-results.json",
        "provider-evidence": "provider-evidence.json",
    }


def invocation_failures(args: argparse.Namespace) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    checks = (
        (args.mode in WORKFLOW_REFS, "mode_invalid"),
        (COMMIT.fullmatch(args.expected_commit) is not None, "expected_commit_invalid"),
        (_workflow_run_is_valid(args.workflow_run), "workflow_run_invalid"),
        (
            type(args.workflow_run_attempt) is int and args.workflow_run_attempt == 1,
            "workflow_run_attempt_invalid",
        ),
        (
            _argument_positive_safe_integer(args.release_artifact_id),
            "release_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.release_artifact_digest) is not None,
            "release_artifact_digest_invalid",
        ),
        (
            _argument_positive_safe_integer(args.node22_source_artifact_id),
            "node22_source_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.node22_source_artifact_digest) is not None,
            "node22_source_artifact_digest_invalid",
        ),
        (
            _argument_positive_safe_integer(args.node24_source_artifact_id),
            "node24_source_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.node24_source_artifact_digest) is not None,
            "node24_source_artifact_digest_invalid",
        ),
        (args.workspace.is_absolute(), "workspace_invalid"),
    )
    for valid, code in checks:
        if not valid:
            failures.append({"evidence": "invocation", "code": code})
    if (
        _argument_positive_safe_integer(args.release_artifact_id)
        and _argument_positive_safe_integer(args.node22_source_artifact_id)
        and _argument_positive_safe_integer(args.node24_source_artifact_id)
        and len(
            {
                int(args.release_artifact_id),
                int(args.node22_source_artifact_id),
                int(args.node24_source_artifact_id),
            }
        )
        != 3
    ):
        failures.append({"evidence": "invocation", "code": "artifact_ids_not_distinct"})

    supplied_evidence_paths = {
        name for name in EVIDENCE_PATH_ARGUMENTS if getattr(args, name) is not None
    }
    supplied_signed_evidence = {
        name for name in SIGNED_EVIDENCE_ARGUMENTS if getattr(args, name) is not None
    }
    supplied_other_signed = {
        name
        for name in SIGNED_ARGUMENTS
        if name not in SIGNED_EVIDENCE_ARGUMENTS and getattr(args, name) is not None
    }
    if args.mode == "rehearsal":
        signed_revalidation = len(supplied_signed_evidence) == len(
            SIGNED_EVIDENCE_ARGUMENTS
        )
        if supplied_other_signed or 0 < len(supplied_signed_evidence) < len(
            SIGNED_EVIDENCE_ARGUMENTS
        ):
            failures.append(
                {
                    "evidence": "invocation",
                    "code": "signed_arguments_forbidden_in_rehearsal",
                }
            )
        elif signed_revalidation and supplied_evidence_paths:
            failures.append(
                {
                    "evidence": "invocation",
                    "code": "signed_evidence_paths_forbidden",
                }
            )
        elif not signed_revalidation and len(supplied_evidence_paths) != len(
            EVIDENCE_PATH_ARGUMENTS
        ):
            failures.append(
                {
                    "evidence": "invocation",
                    "code": "evidence_paths_required",
                }
            )
        if signed_revalidation:
            signed_rehearsal_checks = (
                (
                    _argument_positive_safe_integer(args.signed_evidence_artifact_id),
                    "signed_evidence_artifact_id_invalid",
                ),
                (
                    ARTIFACT_DIGEST.fullmatch(args.signed_evidence_artifact_digest)
                    is not None,
                    "signed_evidence_artifact_digest_invalid",
                ),
            )
            for valid, code in signed_rehearsal_checks:
                if not valid:
                    failures.append({"evidence": "invocation", "code": code})
            signed_ids = (
                args.release_artifact_id,
                args.node22_source_artifact_id,
                args.node24_source_artifact_id,
                args.signed_evidence_artifact_id,
            )
            if all(
                _argument_positive_safe_integer(value) for value in signed_ids
            ) and len({int(value) for value in signed_ids}) != len(signed_ids):
                failures.append(
                    {
                        "evidence": "invocation",
                        "code": "artifact_ids_not_distinct",
                    }
                )
        return failures

    if len(supplied_evidence_paths) != len(EVIDENCE_PATH_ARGUMENTS):
        failures.append({"evidence": "invocation", "code": "evidence_paths_required"})
    missing_signed = [name for name in SIGNED_ARGUMENTS if getattr(args, name) is None]
    if missing_signed:
        failures.append({"evidence": "invocation", "code": "signed_arguments_required"})
        return failures

    publish_checks = (
        (
            SHA256.fullmatch(args.authorization_sha256) is not None,
            "authorization_sha256_invalid",
        ),
        (
            _argument_positive_safe_integer(args.rehearsal_run_id),
            "rehearsal_run_id_invalid",
        ),
        (
            type(args.rehearsal_run_attempt) is int and args.rehearsal_run_attempt == 1,
            "rehearsal_run_attempt_invalid",
        ),
        (
            _argument_positive_safe_integer(args.rehearsal_run_id)
            and _workflow_run_id(args) != int(args.rehearsal_run_id),
            "rehearsal_run_not_distinct",
        ),
        (
            args.rehearsal_workflow_path == REHEARSAL_WORKFLOW_PATH,
            "rehearsal_workflow_path_invalid",
        ),
        (
            args.rehearsal_workflow_sha == args.expected_commit,
            "rehearsal_workflow_sha_invalid",
        ),
        (
            _argument_positive_safe_integer(args.signed_candidate_artifact_id),
            "signed_candidate_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.signed_candidate_artifact_digest)
            is not None,
            "signed_candidate_artifact_digest_invalid",
        ),
        (
            _argument_positive_safe_integer(args.signed_evidence_artifact_id),
            "signed_evidence_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.signed_evidence_artifact_digest) is not None,
            "signed_evidence_artifact_digest_invalid",
        ),
        (
            _argument_positive_safe_integer(args.signed_node22_source_artifact_id),
            "signed_node22_source_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.signed_node22_source_artifact_digest)
            is not None,
            "signed_node22_source_artifact_digest_invalid",
        ),
        (
            _argument_positive_safe_integer(args.signed_node24_source_artifact_id),
            "signed_node24_source_artifact_id_invalid",
        ),
        (
            ARTIFACT_DIGEST.fullmatch(args.signed_node24_source_artifact_digest)
            is not None,
            "signed_node24_source_artifact_digest_invalid",
        ),
        (
            SHA256.fullmatch(args.signed_release_manifest_sha256) is not None,
            "signed_release_manifest_sha256_invalid",
        ),
        (
            args.signed_npm_tarball_name == TYPESCRIPT_TARBALL,
            "signed_npm_tarball_name_invalid",
        ),
        (
            SHA256.fullmatch(args.signed_npm_tarball_sha256) is not None,
            "signed_npm_tarball_sha256_invalid",
        ),
    )
    for valid, code in publish_checks:
        if not valid:
            failures.append({"evidence": "invocation", "code": code})
    all_ids = (
        args.release_artifact_id,
        args.node22_source_artifact_id,
        args.node24_source_artifact_id,
        args.signed_candidate_artifact_id,
        args.signed_evidence_artifact_id,
        args.signed_node22_source_artifact_id,
        args.signed_node24_source_artifact_id,
    )
    if all(_argument_positive_safe_integer(value) for value in all_ids) and len(
        {int(value) for value in all_ids}
    ) != len(all_ids):
        failures.append(
            {
                "evidence": "invocation",
                "code": "artifact_ids_not_distinct",
            }
        )
    return failures


def validate(args: argparse.Namespace) -> dict[str, Any]:
    failures = invocation_failures(args)
    documents: dict[str, dict[str, Any]] = {}
    receipt_hashes: dict[str, str] = {}
    validated: list[str] = []
    archives: tuple[Any, Any, Any] | None = None
    producer_release: VerifiedReleaseArtifactBytes | None = None
    release: VerifiedReleaseArtifactBytes | None = None
    signed_revalidation = (
        args.mode == "rehearsal" and args.signed_evidence_archive is not None
    )
    if not any(failure["evidence"] == "invocation" for failure in failures):
        try:
            producer, node22, node24, archive_hashes = load_current_archives(args)
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-archives", "code": error.code})
        else:
            archives = (producer, node22, node24)
            receipt_hashes.update(archive_hashes)
            try:
                producer_release = _verified_archive_release(
                    producer,
                    args.expected_commit,
                    error_code="release_artifacts_invalid",
                )
                if signed_revalidation:
                    release = producer_release
                else:
                    release = load_current_release_snapshot(
                        args.artifacts_dir,
                        producer_release=producer_release,
                        expected_commit=args.expected_commit,
                    )
            except EvidenceValidationError as error:
                failures.append({"evidence": "release-artifacts", "code": error.code})

    signed_evidence: SignedEvidenceArchive | None = None
    if signed_revalidation and release is not None:
        try:
            signed_evidence = load_signed_evidence_archive(args)
            validate_signed_evidence_summary(
                signed_evidence,
                release=release,
                workflow_run=args.workflow_run,
                candidate_artifact_id=args.release_artifact_id,
                candidate_artifact_digest=args.release_artifact_digest,
                node22_artifact_id=args.node22_source_artifact_id,
                node22_artifact_digest=args.node22_source_artifact_digest,
                node24_artifact_id=args.node24_source_artifact_id,
                node24_artifact_digest=args.node24_source_artifact_digest,
                expected_commit=args.expected_commit,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "signed-evidence", "code": error.code})

    if signed_revalidation:
        document_inputs = (
            {
                label: signed_evidence.members[name]
                for label, name in input_member_names().items()
            }
            if signed_evidence is not None
            else {}
        )
        for label, encoded in document_inputs.items():
            try:
                document, digest = load_document_bytes(encoded)
            except EvidenceValidationError as error:
                failures.append({"evidence": label, "code": error.code})
            else:
                documents[label] = document
                receipt_hashes[label] = digest
    elif not any(failure["evidence"] == "invocation" for failure in failures):
        for label, path in input_paths(args).items():
            try:
                document, digest = load_document(path)
            except EvidenceValidationError as error:
                failures.append({"evidence": label, "code": error.code})
            else:
                documents[label] = document
                receipt_hashes[label] = digest

    onboarding_status: dict[str, Any] | None = None
    onboarding_status_sha256: str | None = None
    onboarding_evidence: dict[str, Any] | None = None
    onboarding_evidence_sha256: str | None = None
    onboarding_evidence_bytes: bytes | None = None
    performance_image_data_digest: str | None = None
    paired_image_digests: dict[str, str] = {}
    raw_replicas: dict[str, dict[str, Any]] = {}
    if signed_evidence is not None:
        try:
            (
                onboarding_status,
                onboarding_status_sha256,
                _,
            ) = load_strict_document_bytes(
                signed_evidence.members["typescript-onboarding/status.json"],
                max_bytes=MAX_ONBOARDING_STATUS_BYTES,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-status", "code": error.code})
        else:
            receipt_hashes["onboarding-status"] = onboarding_status_sha256
        try:
            (
                onboarding_evidence,
                onboarding_evidence_sha256,
                onboarding_evidence_bytes,
            ) = load_strict_document_bytes(
                signed_evidence.members[
                    "typescript-onboarding/typescript-onboarding-evidence.json"
                ],
                max_bytes=onboarding.MAX_DESTINATION_BYTES,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-evidence", "code": error.code})
        else:
            receipt_hashes["onboarding-evidence"] = onboarding_evidence_sha256
        try:
            performance_image_data_digest = load_performance_image_data_bytes(
                signed_evidence.members["performance-imagedata.json"]
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "performance-image-data", "code": error.code})
        else:
            receipt_hashes["performance-image-data"] = performance_image_data_digest
        for replica in ("1", "2", "3"):
            replica_label = f"paired-replica-{replica}"
            image_label = f"paired-image-data-{replica}"
            try:
                document, digest = load_document_bytes(
                    signed_evidence.members[f"raw/benchmarks/replica-{replica}.json"]
                )
            except EvidenceValidationError as error:
                failures.append({"evidence": replica_label, "code": error.code})
            else:
                raw_replicas[replica] = document
                receipt_hashes[replica_label] = digest
            try:
                digest = load_performance_image_data_bytes(
                    signed_evidence.members[
                        f"raw/benchmarks/replica-{replica}-imagedata.json"
                    ]
                )
            except EvidenceValidationError as error:
                failures.append({"evidence": image_label, "code": error.code})
            else:
                paired_image_digests[replica] = digest
                receipt_hashes[image_label] = digest
    elif not signed_revalidation and not any(
        failure["evidence"] == "invocation" for failure in failures
    ):
        try:
            (
                onboarding_status,
                onboarding_status_sha256,
                _,
            ) = load_strict_document(
                args.onboarding_status,
                "TypeScript onboarding status",
                max_bytes=MAX_ONBOARDING_STATUS_BYTES,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-status", "code": error.code})
        else:
            receipt_hashes["onboarding-status"] = onboarding_status_sha256
        try:
            (
                onboarding_evidence,
                onboarding_evidence_sha256,
                onboarding_evidence_bytes,
            ) = load_strict_document(
                args.onboarding_evidence,
                "TypeScript onboarding evidence",
                max_bytes=onboarding.MAX_DESTINATION_BYTES,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-evidence", "code": error.code})
        else:
            receipt_hashes["onboarding-evidence"] = onboarding_evidence_sha256
        try:
            performance_image_data_digest = load_performance_image_data(
                args.performance_image_data
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "performance-image-data", "code": error.code})
        else:
            receipt_hashes["performance-image-data"] = performance_image_data_digest
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

    onboarding_result: dict[str, Any] | None = None
    if (
        release is not None
        and archives is not None
        and onboarding_status is not None
        and onboarding_status_sha256 is not None
        and onboarding_evidence is not None
        and onboarding_evidence_sha256 is not None
        and onboarding_evidence_bytes is not None
        and all(label in documents for label in ("compat-node-22", "compat-node-24"))
    ):
        try:
            onboarding_result = validate_onboarding_evidence(
                onboarding_status,
                onboarding_status_sha256,
                onboarding_evidence,
                onboarding_evidence_sha256,
                onboarding_evidence_bytes,
                archives=archives,
                node_receipt_sha256={
                    "22": receipt_hashes["compat-node-22"],
                    "24": receipt_hashes["compat-node-24"],
                },
                release=release,
                args=args,
            )
        except EvidenceValidationError as error:
            failures.append({"evidence": "onboarding-evidence", "code": error.code})
        else:
            validated.extend(
                [
                    "compat-node-22",
                    "compat-node-24",
                    "onboarding-status",
                    "onboarding-evidence",
                    "producer-archive",
                    "node22-source-archive",
                    "node24-source-archive",
                ]
            )

    signed_source: dict[str, Any] | None = None
    if args.mode == "publish" and release is not None and not failures:
        try:
            signed_source, signed_hashes = validate_signed_source(args, release)
        except EvidenceValidationError as error:
            failures.append({"evidence": "signed-source", "code": error.code})
        else:
            receipt_hashes.update(signed_hashes)
            validated.extend(sorted(signed_hashes))

    failures.sort(key=lambda item: (item["evidence"], item["code"]))
    conclusion = "passed" if not failures else "failed"
    if failures:
        onboarding_result = None
        signed_source = None
        validated = []
    current_artifact: dict[str, Any] | None = None
    if (
        _argument_positive_safe_integer(args.release_artifact_id)
        and ARTIFACT_DIGEST.fullmatch(args.release_artifact_digest) is not None
    ):
        current_artifact = {
            "name": PRODUCER_ARTIFACT,
            "id": int(args.release_artifact_id),
            "digest": args.release_artifact_digest,
        }
    node_source_artifacts: dict[str, Any] = {}
    for major in (22, 24):
        artifact_id = getattr(args, f"node{major}_source_artifact_id")
        digest = getattr(args, f"node{major}_source_artifact_digest")
        if (
            _argument_positive_safe_integer(artifact_id)
            and ARTIFACT_DIGEST.fullmatch(digest) is not None
        ):
            node_source_artifacts[str(major)] = {
                "name": f"kaji-node-compat-{major}",
                "id": int(artifact_id),
                "digest": digest,
            }
    summary = {
        "schemaVersion": 2,
        "mode": args.mode,
        "commit": args.expected_commit,
        "workflowRun": args.workflow_run,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowRef": WORKFLOW_REFS.get(args.mode),
        "currentArtifact": current_artifact,
        "nodeSourceArtifacts": node_source_artifacts,
        "releaseManifestSha256": release.manifest_sha256 if release else None,
        "artifactSha256": full_artifact_hashes(release) if release else {},
        "onboardingEvidence": onboarding_result,
        "signedSource": signed_source,
        "conclusion": conclusion,
        "failureCode": None if not failures else "release_evidence_validation_failed",
        "failures": failures,
        "receiptSha256": dict(sorted(receipt_hashes.items())),
        "validatedEvidence": sorted(validated),
    }
    if (
        signed_evidence is not None
        and json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        != signed_evidence.summary_bytes
    ):
        mismatch = {
            "evidence": "signed-evidence",
            "code": "signed_evidence_summary_mismatch",
        }
        if mismatch not in summary["failures"]:
            summary["failures"].append(mismatch)
            summary["failures"].sort(key=lambda item: (item["evidence"], item["code"]))
        summary["conclusion"] = "failed"
        summary["failureCode"] = "release_evidence_validation_failed"
        summary["onboardingEvidence"] = None
        summary["signedSource"] = None
        summary["validatedEvidence"] = []
    return summary


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


def _valid_npm_identity(value: Any) -> bool:
    if not isinstance(value, str) or NPM_IDENTITY.fullmatch(value) is None:
        return False
    lowered = value.lower()
    if lowered.startswith(
        ("npm_", "github_pat_", "ghp_", "gho_", "ghr_", "ghu_", "ghs_")
    ):
        return False
    return (
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            value,
        )
        is None
    )


def validate_publication_status(
    path: Path,
    *,
    expected_commit: str,
    workflow_run: str,
    workflow_run_attempt: int,
    expected_tag: str,
    expected_workflow_path: str,
    expected_workflow_sha: str,
    expected_publisher: str,
) -> tuple[dict[str, Any], str]:
    require(
        COMMIT.fullmatch(expected_commit) is not None
        and _workflow_run_is_valid(workflow_run)
        and workflow_run_attempt == 1
        and expected_tag == PUBLISH_TAG
        and expected_workflow_path == PUBLISH_WORKFLOW_PATH
        and COMMIT.fullmatch(expected_workflow_sha) is not None
        and expected_workflow_sha == expected_commit
        and _valid_npm_identity(expected_publisher),
        "publication_status_expectation_invalid",
    )
    document, digest, encoded = load_strict_document(
        path,
        "publication status",
        max_bytes=MAX_PUBLICATION_STATUS_BYTES,
    )
    require(
        encoded
        == json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "publication_status_noncanonical",
    )
    require(
        set(document) == PUBLICATION_STATUS_KEYS
        and type(document.get("schemaVersion")) is int
        and document["schemaVersion"] == 1,
        "publication_status_schema_invalid",
    )
    require(
        document.get("target") == "npm"
        and document.get("commit") == expected_commit
        and document.get("tag") == expected_tag
        and document.get("state") == "npm_byte_verified"
        and document.get("previousState") == "unpublished"
        and document.get("releaseReady") is True
        and document.get("installRecommendation") is True
        and document.get("registries") == {"pypi": "absent", "npm": "present"}
        and document.get("publishJobs") == {"pypi": "skipped", "npm": "success"}
        and document.get("registryVerification") == "npm_byte_verified"
        and document.get("incident") is None,
        "publication_status_not_terminal",
    )
    require(
        document.get("workflowRun") == workflow_run
        and type(document.get("workflowRunAttempt")) is int
        and document["workflowRunAttempt"] == workflow_run_attempt
        and document.get("workflowPath") == expected_workflow_path
        and document.get("workflowSha") == expected_workflow_sha
        and document.get("expectedPublisher") == expected_publisher,
        "publication_status_tuple_mismatch",
    )

    publisher = document.get("publisherIdentity")
    require(
        isinstance(publisher, dict)
        and set(publisher)
        == {"conclusion", "reason", "artifact", "receiptSha256", "identity"}
        and publisher.get("conclusion") == "passed"
        and publisher.get("reason") is None
        and isinstance(publisher.get("receiptSha256"), str)
        and SHA256.fullmatch(publisher["receiptSha256"]) is not None,
        "publisher_identity_projection_invalid",
    )
    assert isinstance(publisher, dict)
    run_id = int(workflow_run.rsplit("/", 1)[1])
    artifact = publisher.get("artifact")
    require(
        isinstance(artifact, dict)
        and set(artifact) == {"name", "id", "digest"}
        and artifact.get("name")
        == f"kaji-publisher-identity-{run_id}-{workflow_run_attempt}"
        and type(artifact.get("id")) is int
        and 1 <= artifact["id"] <= MAX_SAFE_INTEGER
        and isinstance(artifact.get("digest"), str)
        and ARTIFACT_DIGEST.fullmatch(artifact["digest"]) is not None,
        "publisher_identity_artifact_invalid",
    )
    identity = publisher.get("identity")
    require(
        isinstance(identity, dict)
        and set(identity) == PUBLISHER_IDENTITY_KEYS
        and identity.get("schemaVersion") == "1.0.0"
        and identity.get("commit") == expected_commit
        and identity.get("tag") == expected_tag
        and identity.get("workflowRun") == workflow_run
        and type(identity.get("workflowRunAttempt")) is int
        and identity["workflowRunAttempt"] == workflow_run_attempt
        and identity.get("workflowPath") == expected_workflow_path
        and identity.get("workflowSha") == expected_workflow_sha
        and identity.get("workflowSha") == identity.get("commit")
        and identity.get("expectedPublisher") == expected_publisher
        and identity.get("actualPublisher") == expected_publisher
        and identity.get("conclusion") == "passed"
        and type(identity.get("exitCode")) is int
        and identity["exitCode"] == 0
        and identity.get("failureCode") is None,
        "publisher_identity_receipt_invalid",
    )
    assert isinstance(identity, dict)
    canonical_identity = (
        json.dumps(identity, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    require(
        hashlib.sha256(canonical_identity).hexdigest() == publisher["receiptSha256"],
        "publisher_identity_receipt_hash_mismatch",
    )
    return document, digest


def parse_publication_status_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate one terminal npm publication status."
    )
    parser.add_argument("--publication-status", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--expected-workflow-path", required=True)
    parser.add_argument("--expected-workflow-sha", required=True)
    parser.add_argument("--expected-publisher", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def publication_status_main(argv: list[str]) -> int:
    args = parse_publication_status_args(argv)
    retained_expected_publisher = (
        args.expected_publisher
        if _valid_npm_identity(args.expected_publisher)
        else None
    )
    publication_status_sha256: str | None = None
    state: str | None = None
    publisher_identity: dict[str, Any] | None = None
    failures: list[dict[str, str]] = []
    try:
        document, publication_status_sha256 = validate_publication_status(
            args.publication_status,
            expected_commit=args.expected_commit,
            workflow_run=args.workflow_run,
            workflow_run_attempt=args.workflow_run_attempt,
            expected_tag=args.expected_tag,
            expected_workflow_path=args.expected_workflow_path,
            expected_workflow_sha=args.expected_workflow_sha,
            expected_publisher=args.expected_publisher,
        )
    except EvidenceValidationError as error:
        failures.append({"evidence": "publication-status", "code": error.code})
    except Exception:
        failures.append(
            {
                "evidence": "publication-status",
                "code": "internal_validation_error",
            }
        )
    else:
        state = document["state"]
        publisher_identity = document["publisherIdentity"]
    conclusion = "passed" if not failures else "failed"
    summary = {
        "schemaVersion": 1,
        "kind": "kaji-publication-status-validation",
        "commit": args.expected_commit,
        "tag": args.expected_tag,
        "workflowRun": args.workflow_run,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowPath": args.expected_workflow_path,
        "workflowSha": args.expected_workflow_sha,
        "expectedPublisher": retained_expected_publisher,
        "state": state,
        "publisherIdentity": publisher_identity,
        "publicationStatusSha256": publication_status_sha256,
        "conclusion": conclusion,
        "failureCode": (
            None if not failures else "publication_status_validation_failed"
        ),
        "failures": failures,
    }
    rendered = write_json_atomic(args.output, summary)
    print(rendered, end="")
    return 0 if conclusion == "passed" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rehearsal", "publish"), required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--release-artifact-id", required=True)
    parser.add_argument("--release-artifact-digest", required=True)
    parser.add_argument("--python-compat-311", type=Path)
    parser.add_argument("--python-compat-314", type=Path)
    parser.add_argument("--node-compat-22", type=Path)
    parser.add_argument("--node-compat-24", type=Path)
    parser.add_argument("--performance-status", type=Path)
    parser.add_argument("--benchmark-results", type=Path)
    parser.add_argument("--soak-results", type=Path)
    parser.add_argument("--performance-image-data", type=Path)
    parser.add_argument("--provider-evidence", type=Path)
    parser.add_argument("--producer-archive", type=Path, required=True)
    parser.add_argument("--node22-source-archive", type=Path, required=True)
    parser.add_argument("--node24-source-archive", type=Path, required=True)
    parser.add_argument("--onboarding-status", type=Path)
    parser.add_argument("--onboarding-evidence", type=Path)
    parser.add_argument("--node22-source-artifact-id", required=True)
    parser.add_argument("--node22-source-artifact-digest", required=True)
    parser.add_argument("--node24-source-artifact-id", required=True)
    parser.add_argument("--node24-source-artifact-digest", required=True)
    parser.add_argument("--authorization-sha256")
    parser.add_argument("--rehearsal-run-id")
    parser.add_argument("--rehearsal-run-attempt", type=int)
    parser.add_argument("--rehearsal-workflow-path")
    parser.add_argument("--rehearsal-workflow-sha")
    parser.add_argument("--signed-candidate-archive", type=Path)
    parser.add_argument("--signed-candidate-artifact-id")
    parser.add_argument("--signed-candidate-artifact-digest")
    parser.add_argument("--signed-evidence-archive", type=Path)
    parser.add_argument("--signed-evidence-artifact-id")
    parser.add_argument("--signed-evidence-artifact-digest")
    parser.add_argument("--signed-node22-source-artifact-id")
    parser.add_argument("--signed-node22-source-artifact-digest")
    parser.add_argument("--signed-node24-source-artifact-id")
    parser.add_argument("--signed-node24-source-artifact-digest")
    parser.add_argument("--signed-release-manifest-sha256")
    parser.add_argument("--signed-npm-tarball-name")
    parser.add_argument("--signed-npm-tarball-sha256")
    parser.add_argument("--signed-npm-tarball", type=Path)
    parser.add_argument("--rebuilt-npm-tarball", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def fallback_summary(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "mode": args.mode,
        "commit": args.expected_commit,
        "workflowRun": args.workflow_run,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowRef": WORKFLOW_REFS.get(args.mode),
        "currentArtifact": None,
        "nodeSourceArtifacts": {},
        "releaseManifestSha256": None,
        "artifactSha256": {},
        "onboardingEvidence": None,
        "signedSource": None,
        "conclusion": "failed",
        "failureCode": "release_evidence_validation_failed",
        "failures": [{"evidence": "validator", "code": "internal_validation_error"}],
        "receiptSha256": {},
        "validatedEvidence": [],
    }


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        import sys

        argv = sys.argv[1:]
    if argv and argv[0] == "publication-status":
        return publication_status_main(argv[1:])
    args = parse_args(argv)
    try:
        summary = validate(args)
    except Exception:
        summary = fallback_summary(args)
    rendered = write_json_atomic(args.output, summary)
    print(rendered, end="")
    return 0 if summary["conclusion"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
