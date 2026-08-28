#!/usr/bin/env python3
"""Compose and validate protected TypeScript onboarding evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import struct
from typing import Any, Literal, Mapping
import zipfile
import zlib

from jsonschema import Draft202012Validator

import validate_compatibility_receipts as validation
import verify_release_artifacts as release_verification


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "kaji"
    / "contracts"
    / "release"
    / "typescript-onboarding-evidence-v1.schema.json"
)
TARBALL = "kaji-0.2.0-beta.11.tgz"
PRODUCER_NAME = "kaji-artifacts"
SOURCE_NAMES = {
    22: "kaji-node-compat-22",
    24: "kaji-node-compat-24",
}
NODE_RECEIPT_NAME = "compatibility-receipt.json"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_PRODUCER_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_NODE_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_PRODUCER_MEMBER_BYTES = 128 * 1024 * 1024
MAX_NODE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_DESTINATION_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
IO_CHUNK_BYTES = 1024 * 1024
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
ARTIFACT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
WORKFLOW_RUN = re.compile(
    r"https://github[.]com/enkyuan/alloy/actions/runs/[1-9][0-9]*"
)
WORKFLOW_REFS = {
    "enkyuan/alloy/.github/workflows/kaji.rehearsal.yml@refs/heads/main",
    "enkyuan/alloy/.github/workflows/kaji.publish.yml@refs/tags/kaji-v0.2.0-beta.11",
}
STATIC_RUNNER_POLICIES = {
    major: {
        "configuredLabel": f"ubuntu-{major}.04",
        "environment": "github-hosted",
        "runnerOS": "Linux",
        "runnerArch": "X64",
        "platformOS": "linux",
        "platformArch": "x64",
        "imageOS": f"ubuntu{major}",
    }
    for major in (22, 24)
}
_REQUIRED_DIR_FD_FUNCTIONS = (os.open, os.stat, os.unlink, os.rename)
_REQUIRED_FOLLOW_SYMLINK_FUNCTION = os.stat

EvidenceError = validation.EvidenceError


class EvidenceWriteAmbiguous(EvidenceError):
    """The destination and rollback could not both be made durable."""

    def __init__(self, recovery_name: str) -> None:
        self.recovery_name = recovery_name
        super().__init__(
            "/: onboarding evidence write is ambiguous; owner-only recovery retained"
        )


class EvidenceWriteUnrecoverable(EvidenceError):
    """Rollback failed and no crash-durable recovery name can be guaranteed."""

    def __init__(self) -> None:
        super().__init__(
            "/: onboarding evidence recovery could not be retained; "
            "manual filesystem inspection required"
        )


class EvidenceCleanupAmbiguous(EvidenceError):
    """Temporary/recovery cleanup could not be made crash-durable."""

    def __init__(self, recovery_name: str | None = None) -> None:
        self.recovery_name = recovery_name
        super().__init__(
            "/: onboarding evidence cleanup durability is ambiguous; "
            "manual filesystem inspection required"
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedArtifactArchive:
    """Trusted Actions artifact metadata paired with exact downloaded ZIP bytes."""

    name: Literal[
        "kaji-artifacts",
        "kaji-node-compat-22",
        "kaji-node-compat-24",
    ]
    artifact_id: int
    digest: str
    run_id: int
    run_attempt: Literal[1]
    head_sha: str
    expired: Literal[False]
    archive_bytes: bytes


@dataclass
class _DirectoryAnchor:
    descriptors: list[int]
    components: list[str]

    @property
    def directory_fd(self) -> int:
        return self.descriptors[-1]


@dataclass
class _WriteState:
    temporary_fd: int | None = None
    temporary_name: str | None = None
    recovery_fd: int | None = None
    recovery_name: str | None = None
    rollback_fd: int | None = None
    rollback_name: str | None = None
    replaced: bool = False
    recovery_namespace_safe: bool = True


def _schema_validator() -> Any:
    try:
        encoded = SCHEMA_PATH.read_bytes()
        schema = json.loads(encoded)
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError):
        validation.fail("/", "onboarding evidence schema is unavailable")
    return Draft202012Validator(schema)


def _positive_integer(value: Any, location: str) -> int:
    if type(value) is not int or value < 1 or value > MAX_SAFE_INTEGER:
        validation.fail(location, "must be a positive safe integer")
    return value


def _commit(value: Any, location: str) -> str:
    if not isinstance(value, str) or COMMIT.fullmatch(value) is None:
        validation.fail(location, "commit identity is invalid")
    return value


def _sha256(value: Any, location: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        validation.fail(location, "SHA-256 identity is invalid")
    return value


def _artifact_digest(value: Any, location: str) -> str:
    if not isinstance(value, str) or ARTIFACT_DIGEST.fullmatch(value) is None:
        validation.fail(location, "artifact digest is invalid")
    return value


def _child_location(location: str, field: str) -> str:
    return f"/{field}" if location == "/" else f"{location}/{field}"


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


def _archive_limit(name: str) -> int:
    if name == PRODUCER_NAME:
        return MAX_PRODUCER_ARCHIVE_BYTES
    if name in SOURCE_NAMES.values():
        return MAX_NODE_ARCHIVE_BYTES
    validation.fail("/", "artifact archive name is invalid")


def load_authenticated_archive(
    path: Path,
    *,
    name: Literal[
        "kaji-artifacts",
        "kaji-node-compat-22",
        "kaji-node-compat-24",
    ],
    artifact_id: int,
    digest: str,
    run_id: int,
    run_attempt: Literal[1],
    head_sha: str,
    expired: Literal[False],
) -> AuthenticatedArtifactArchive:
    """Stable-read an Actions archive; compose still reauthenticates it."""

    archive_bytes = validation.load_stable_bytes(
        path,
        "Actions artifact archive",
        max_bytes=_archive_limit(name),
    )
    archive = AuthenticatedArtifactArchive(
        name=name,
        artifact_id=artifact_id,
        digest=digest,
        run_id=run_id,
        run_attempt=run_attempt,
        head_sha=head_sha,
        expired=expired,
        archive_bytes=archive_bytes,
    )
    _authenticate_archive(archive, expected_name=name, location="/")
    return archive


def _validate_extra_fields(extra: bytes, location: str) -> None:
    offset = 0
    while offset < len(extra):
        if offset + 4 > len(extra):
            validation.fail(location, "ZIP extra fields are malformed")
        field_id, size = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if offset + size > len(extra):
            validation.fail(location, "ZIP extra fields are malformed")
        if field_id == 0x0001:
            validation.fail(location, "ZIP64 is not accepted")
        offset += size


def _validate_central_directory(
    encoded: bytes,
    *,
    offset: int,
    size: int,
    count: int,
    expected_names: set[bytes],
    location: str,
) -> None:
    cursor = offset
    end = offset + size
    for _ in range(count):
        if cursor + 46 > end or encoded[cursor : cursor + 4] != b"PK\x01\x02":
            validation.fail(location, "ZIP central directory is ambiguous")
        (
            filename_length,
            extra_length,
            comment_length,
            disk_start,
        ) = struct.unpack_from("<HHHH", encoded, cursor + 28)
        if disk_start != 0 or comment_length != 0:
            validation.fail(location, "ZIP central directory is ambiguous")
        filename_start = cursor + 46
        filename_end = filename_start + filename_length
        extra_end = filename_end + extra_length
        raw_name = encoded[filename_start:filename_end]
        if raw_name not in expected_names:
            validation.fail(location, "ZIP central member name is unsafe")
        _validate_extra_fields(encoded[filename_end:extra_end], location)
        cursor = extra_end + comment_length
        if cursor > end:
            validation.fail(location, "ZIP central directory is ambiguous")
    if cursor != end:
        validation.fail(location, "ZIP central directory is ambiguous")


def _zip_members(
    encoded: bytes,
    *,
    expected_names: set[str],
    archive_limit: int,
    member_limit: int,
    location: str,
) -> dict[str, bytes]:
    if type(encoded) is not bytes or not 22 <= len(encoded) <= archive_limit:
        validation.fail(location, "artifact archive bytes are invalid")
    eocd_offset = len(encoded) - 22
    if encoded[eocd_offset : eocd_offset + 4] != b"PK\x05\x06":
        validation.fail(location, "ZIP has prefix, comment, or trailing ambiguity")
    try:
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
    except struct.error:
        validation.fail(location, "ZIP end record is invalid")
    if (
        signature != b"PK\x05\x06"
        or disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries in {0, 0xFFFF}
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or comment_length != 0
        or central_offset + central_size != eocd_offset
    ):
        validation.fail(location, "ZIP end record is ambiguous")
    _validate_central_directory(
        encoded,
        offset=central_offset,
        size=central_size,
        count=total_entries,
        expected_names={name.encode("ascii") for name in expected_names},
        location=location,
    )

    try:
        with zipfile.ZipFile(BytesIO(encoded), "r") as archive:
            if archive.comment:
                validation.fail(location, "ZIP archive comment is not accepted")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) != total_entries or len(names) != len(set(names)):
                validation.fail(location, "ZIP member inventory is ambiguous")
            if set(names) != expected_names or len(names) != len(expected_names):
                validation.fail(location, "ZIP member inventory differs")
            if min(info.header_offset for info in infos) != 0:
                validation.fail(location, "ZIP prefix bytes are not accepted")
            ordered_infos = sorted(infos, key=lambda item: item.header_offset)
            boundaries = {
                info.header_offset: (
                    ordered_infos[index + 1].header_offset
                    if index + 1 < len(ordered_infos)
                    else central_offset
                )
                for index, info in enumerate(ordered_infos)
            }

            total_size = 0
            members: dict[str, bytes] = {}
            for info in infos:
                member_location = f"{location}/{info.filename}"
                name = info.filename
                path = PurePosixPath(name)
                if (
                    info.orig_filename != name
                    or "\x00" in name
                    or "\\" in name
                    or name.startswith("/")
                    or path.is_absolute()
                    or path.name != name
                    or any(part in {"", ".", ".."} for part in path.parts)
                ):
                    validation.fail(member_location, "ZIP member name is unsafe")
                local_offset = info.header_offset
                if (
                    local_offset < 0
                    or local_offset + 30 > central_offset
                    or encoded[local_offset : local_offset + 4] != b"PK\x03\x04"
                ):
                    validation.fail(member_location, "ZIP local header is invalid")
                (
                    local_version,
                    local_flags,
                    local_method,
                    _local_time,
                    _local_date,
                    local_crc,
                    local_compressed_size,
                    local_size,
                    local_name_length,
                    local_extra_length,
                ) = struct.unpack_from(
                    "<5H3L2H",
                    encoded,
                    local_offset + 4,
                )
                local_name_start = local_offset + 30
                local_name_end = local_name_start + local_name_length
                local_extra_end = local_name_end + local_extra_length
                if local_extra_end > central_offset or encoded[
                    local_name_start:local_name_end
                ] != name.encode("ascii"):
                    validation.fail(member_location, "ZIP local member name is unsafe")
                _validate_extra_fields(
                    encoded[local_name_end:local_extra_end],
                    member_location,
                )
                if (
                    local_version != info.extract_version
                    or local_flags != info.flag_bits
                    or local_method != info.compress_type
                ):
                    validation.fail(
                        member_location, "ZIP local header semantics differ"
                    )
                if local_flags & 0x8:
                    if (
                        local_crc not in {0, info.CRC}
                        or local_compressed_size not in {0, info.compress_size}
                        or local_size not in {0, info.file_size}
                    ):
                        validation.fail(
                            member_location, "ZIP data descriptor binding differs"
                        )
                elif (
                    local_crc != info.CRC
                    or local_compressed_size != info.compress_size
                    or local_size != info.file_size
                ):
                    validation.fail(member_location, "ZIP local size or CRC differs")
                compressed_end = local_extra_end + info.compress_size
                record_end = boundaries[info.header_offset]
                if compressed_end > record_end:
                    validation.fail(member_location, "ZIP local record overlaps")
                trailing = encoded[compressed_end:record_end]
                if local_flags & 0x8:
                    descriptor = struct.pack(
                        "<LLL",
                        info.CRC,
                        info.compress_size,
                        info.file_size,
                    )
                    if trailing not in {descriptor, b"PK\x07\x08" + descriptor}:
                        validation.fail(
                            member_location,
                            "ZIP data descriptor is ambiguous",
                        )
                elif trailing:
                    validation.fail(
                        member_location, "ZIP local record has unreferenced bytes"
                    )
                compressed = encoded[local_extra_end:compressed_end]
                if info.compress_type == zipfile.ZIP_STORED:
                    if info.compress_size != info.file_size:
                        validation.fail(
                            member_location, "stored ZIP member size differs"
                        )
                    decoded_from_raw = compressed
                else:
                    try:
                        decompressor = zlib.decompressobj(-15)
                        decoded_from_raw = decompressor.decompress(
                            compressed,
                            member_limit + 1,
                        )
                        if decompressor.unconsumed_tail:
                            validation.fail(
                                member_location,
                                "deflate ZIP member exceeds its bound",
                            )
                        decoded_from_raw += decompressor.flush()
                    except zlib.error:
                        validation.fail(
                            member_location, "deflate ZIP member is invalid"
                        )
                    if (
                        not decompressor.eof
                        or decompressor.unused_data
                        or decompressor.unconsumed_tail
                    ):
                        validation.fail(
                            member_location,
                            "deflate ZIP member has trailing data",
                        )
                if (
                    len(decoded_from_raw) != info.file_size
                    or len(decoded_from_raw) > member_limit
                    or zlib.crc32(decoded_from_raw) != info.CRC
                ):
                    validation.fail(member_location, "ZIP raw member identity differs")
                if info.is_dir() or info.external_attr & 0x10:
                    validation.fail(member_location, "ZIP directories are not accepted")
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                if file_type not in {0, stat.S_IFREG}:
                    validation.fail(member_location, "ZIP links are not accepted")
                if info.flag_bits & 0x1:
                    validation.fail(
                        member_location, "encrypted ZIP members are not accepted"
                    )
                if info.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    validation.fail(
                        member_location, "ZIP compression method is unsupported"
                    )
                if info.comment:
                    validation.fail(
                        member_location, "ZIP member comments are not accepted"
                    )
                _validate_extra_fields(info.extra, member_location)
                if (
                    info.file_size < 1
                    or info.file_size > member_limit
                    or info.compress_size < 0
                    or (
                        info.file_size
                        > max(1, info.compress_size) * MAX_COMPRESSION_RATIO
                    )
                ):
                    validation.fail(member_location, "ZIP member size is unsafe")
                total_size += info.file_size
                if total_size > archive_limit:
                    validation.fail(location, "ZIP expanded size is unsafe")

                output = bytearray()
                with archive.open(info, "r") as stream:
                    while True:
                        chunk = stream.read(IO_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > info.file_size or len(output) > member_limit:
                            validation.fail(
                                member_location, "ZIP member expanded size differs"
                            )
                if len(output) != info.file_size:
                    validation.fail(member_location, "ZIP member size differs")
                if bytes(output) != decoded_from_raw:
                    validation.fail(member_location, "ZIP member decoders differ")
                members[name] = bytes(output)
            return members
    except EvidenceError:
        raise
    except (
        OSError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        struct.error,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
    ):
        validation.fail(location, "artifact ZIP is invalid")


def _authenticate_archive(
    archive: AuthenticatedArtifactArchive,
    *,
    expected_name: str,
    location: str,
) -> dict[str, bytes]:
    if not isinstance(archive, AuthenticatedArtifactArchive):
        validation.fail(location, "authenticated artifact archive is invalid")
    if archive.name != expected_name or archive.expired is not False:
        validation.fail(location, "authenticated artifact identity differs")
    _positive_integer(archive.artifact_id, _child_location(location, "id"))
    digest = _artifact_digest(
        archive.digest,
        _child_location(location, "digest"),
    )
    _positive_integer(archive.run_id, _child_location(location, "runId"))
    if type(archive.run_attempt) is not int or archive.run_attempt != 1:
        validation.fail(
            _child_location(location, "runAttempt"),
            "trusted attempt differs",
        )
    _commit(archive.head_sha, _child_location(location, "headSha"))
    if type(archive.archive_bytes) is not bytes:
        validation.fail(location, "artifact archive bytes are invalid")
    observed_digest = "sha256:" + hashlib.sha256(archive.archive_bytes).hexdigest()
    if digest != observed_digest:
        validation.fail(
            _child_location(location, "digest"),
            "artifact archive digest differs",
        )
    if expected_name == PRODUCER_NAME:
        expected_names = set(release_verification.EXPECTED_ARTIFACTS) | {
            "manifest.json",
            "SHA256SUMS",
        }
        member_limit = MAX_PRODUCER_MEMBER_BYTES
    else:
        expected_names = {NODE_RECEIPT_NAME}
        member_limit = MAX_NODE_MEMBER_BYTES
    return _zip_members(
        archive.archive_bytes,
        expected_names=expected_names,
        archive_limit=_archive_limit(expected_name),
        member_limit=member_limit,
        location=location,
    )


def _release_inputs(
    producer_archive: AuthenticatedArtifactArchive,
) -> tuple[
    str,
    str,
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    members = _authenticate_archive(
        producer_archive,
        expected_name=PRODUCER_NAME,
        location="/producerArtifact",
    )
    commit = _commit(producer_archive.head_sha, "/commit")
    try:
        verified = release_verification.verify_release_member_bytes(members, commit)
    except (SystemExit, TypeError, ValueError, KeyError, AttributeError):
        validation.fail(
            "/producerArtifact", "authenticated release artifact set is invalid"
        )
    artifacts_by_name: dict[str, dict[str, Any]] = {}
    for name, (package, version) in release_verification.EXPECTED_ARTIFACTS.items():
        encoded = verified.members[name]
        artifacts_by_name[name] = {
            "name": name,
            "package": package,
            "version": version,
            "size": len(encoded),
            "sha256": verified.artifact_sha256[name],
        }
    candidate = artifacts_by_name[TARBALL]
    package_artifact = {
        "name": TARBALL,
        "size": candidate["size"],
        "sha256": candidate["sha256"],
    }
    producer_document = {
        "name": producer_archive.name,
        "id": producer_archive.artifact_id,
        "digest": producer_archive.digest,
        "runId": producer_archive.run_id,
        "runAttempt": producer_archive.run_attempt,
        "headSha": producer_archive.head_sha,
    }
    return (
        commit,
        verified.manifest_sha256,
        package_artifact,
        artifacts_by_name,
        producer_document,
    )


def _source_document(
    source: AuthenticatedArtifactArchive,
    *,
    major: int,
    commit: str,
    run_id: int,
    raw_sha256: str,
) -> dict[str, Any]:
    location = f"/cells/{0 if major == 22 else 1}/sourceArtifact"
    if source.run_id != run_id:
        validation.fail(f"{location}/runId", "trusted source run differs")
    if source.head_sha != commit:
        validation.fail(f"{location}/headSha", "trusted source commit differs")
    _sha256(raw_sha256, f"{location}/receiptSha256")
    return {
        "name": source.name,
        "id": source.artifact_id,
        "digest": source.digest,
        "runId": source.run_id,
        "runAttempt": source.run_attempt,
        "headSha": source.head_sha,
        "receiptSha256": raw_sha256,
    }


def _invocation_document(
    *,
    run_id: int,
    expected_workflow_run: str,
    expected_workflow_ref: str,
    expected_workflow_sha: str,
    commit: str,
) -> dict[str, Any]:
    if (
        not isinstance(expected_workflow_run, str)
        or WORKFLOW_RUN.fullmatch(expected_workflow_run) is None
        or expected_workflow_run
        != f"https://github.com/enkyuan/alloy/actions/runs/{run_id}"
    ):
        validation.fail("/invocation/workflowRun", "trusted workflow run differs")
    if expected_workflow_ref not in WORKFLOW_REFS:
        validation.fail("/invocation/workflowRef", "trusted workflow ref differs")
    if _commit(expected_workflow_sha, "/invocation/workflowSha") != commit:
        validation.fail("/invocation/workflowSha", "trusted workflow SHA differs")
    return {
        "workflowRun": expected_workflow_run,
        "runId": run_id,
        "runAttempt": 1,
        "workflowRef": expected_workflow_ref,
        "workflowSha": expected_workflow_sha,
        "job": "node-compat",
    }


def _receipt_document(encoded: bytes, location: str) -> dict[str, Any]:
    try:
        document = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError):
        validation.fail(location, "authenticated Node receipt is invalid")
    if not isinstance(document, dict):
        validation.fail(location, "authenticated Node receipt must be an object")
    return document


def _validated_cell(
    *,
    major: int,
    source_archive: AuthenticatedArtifactArchive,
    commit: str,
    manifest_sha256: str,
    package_artifact: dict[str, Any],
    artifacts_by_name: dict[str, dict[str, Any]],
    producer_artifact: dict[str, Any],
    invocation: dict[str, Any],
) -> dict[str, Any]:
    index = 0 if major == 22 else 1
    location = f"/cells/{index}"
    members = _authenticate_archive(
        source_archive,
        expected_name=SOURCE_NAMES[major],
        location=f"{location}/sourceArtifact",
    )
    raw_receipt = members[NODE_RECEIPT_NAME]
    raw_sha256 = hashlib.sha256(raw_receipt).hexdigest()
    raw_document = _receipt_document(raw_receipt, location)
    validated = validation.validate_node_compatibility_receipt_v2(
        raw_document,
        expected_runtime_version=str(major),
        commit=commit,
        manifest_hash=manifest_sha256,
        artifacts_by_name=artifacts_by_name,
        expected_workflow_run=invocation["workflowRun"],
        expected_workflow_run_attempt=1,
    )
    static_runner_policy = STATIC_RUNNER_POLICIES[major]
    validation.validate_protected_node_receipt_source_bindings(
        validated,
        package_artifact=package_artifact,
        producer_artifact=producer_artifact,
        static_runner_policy=static_runner_policy,
        invocation=invocation,
    )
    proofs = raw_document.get("githubPackageProofs")
    validation.validate_github_package_proofs(proofs, "typescript")
    source = _source_document(
        source_archive,
        major=major,
        commit=commit,
        run_id=producer_artifact["runId"],
        raw_sha256=raw_sha256,
    )
    return {
        "executionMode": "protected",
        "sourceArtifact": source,
        "runtime": deepcopy(dict(validated.runtime)),
        "runner": deepcopy(dict(validated.runner)),
        "invocation": deepcopy(invocation),
        "onboardingProofs": deepcopy(dict(validated.onboarding_proofs)),
        "timings": deepcopy(dict(validated.timings)),
        "toolchain": deepcopy(dict(validated.toolchain)),
        "conclusion": "passed",
        "failureCode": None,
    }


def _compose(
    *,
    producer_archive: AuthenticatedArtifactArchive,
    node22_archive: AuthenticatedArtifactArchive,
    node24_archive: AuthenticatedArtifactArchive,
    expected_workflow_run: str,
    expected_workflow_ref: str,
    expected_workflow_sha: str,
) -> dict[str, Any]:
    (
        commit,
        manifest_sha256,
        package,
        artifacts_by_name,
        producer,
    ) = _release_inputs(producer_archive)
    invocation = _invocation_document(
        run_id=producer["runId"],
        expected_workflow_run=expected_workflow_run,
        expected_workflow_ref=expected_workflow_ref,
        expected_workflow_sha=expected_workflow_sha,
        commit=commit,
    )
    cells = [
        _validated_cell(
            major=22,
            source_archive=node22_archive,
            commit=commit,
            manifest_sha256=manifest_sha256,
            package_artifact=package,
            artifacts_by_name=artifacts_by_name,
            producer_artifact=producer,
            invocation=invocation,
        ),
        _validated_cell(
            major=24,
            source_archive=node24_archive,
            commit=commit,
            manifest_sha256=manifest_sha256,
            package_artifact=package,
            artifacts_by_name=artifacts_by_name,
            producer_artifact=producer,
            invocation=invocation,
        ),
    ]
    source_ids = [cell["sourceArtifact"]["id"] for cell in cells]
    if source_ids[0] == source_ids[1] or producer["id"] in source_ids:
        validation.fail("/cells", "artifact identities are not distinct")
    document = {
        "schemaVersion": "1.0.0",
        "commit": commit,
        "releaseManifestSha256": manifest_sha256,
        "packageArtifact": deepcopy(package),
        "producerArtifact": deepcopy(producer),
        "cells": cells,
    }
    validate_document(document)
    return document


def compose_document(
    *,
    producer_archive: AuthenticatedArtifactArchive,
    node22_archive: AuthenticatedArtifactArchive,
    node24_archive: AuthenticatedArtifactArchive,
    expected_workflow_run: str,
    expected_workflow_ref: str,
    expected_workflow_sha: str,
) -> dict[str, Any]:
    """Compose one deterministic aggregate from exact authenticated ZIP bytes."""

    return _compose(
        producer_archive=producer_archive,
        node22_archive=node22_archive,
        node24_archive=node24_archive,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_ref=expected_workflow_ref,
        expected_workflow_sha=expected_workflow_sha,
    )


def validate_document(document: Mapping[str, Any]) -> None:
    """Validate the closed schema and every cross-field semantic binding."""

    if not isinstance(document, dict):
        validation.fail("/", "onboarding evidence must be an object")
    validator = _schema_validator()
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            [str(part) for part in error.absolute_schema_path],
        ),
    )
    if errors:
        error = errors[0]
        validation.fail(
            validation.pointer(error.absolute_path),
            "onboarding evidence schema differs",
        )

    commit = document["commit"]
    producer = document["producerArtifact"]
    package = document["packageArtifact"]
    cells = document["cells"]
    if commit != producer["headSha"]:
        validation.fail("/producerArtifact/headSha", "producer commit differs")
    run_id = producer["runId"]
    workflow_ref = cells[0]["invocation"]["workflowRef"]
    source_ids: list[int] = []
    for index, cell in enumerate(cells):
        source = cell["sourceArtifact"]
        invocation = cell["invocation"]
        runtime = cell["runtime"]
        toolchain = cell["toolchain"]
        source_ids.append(source["id"])
        if (
            source["headSha"] != commit
            or source["runId"] != run_id
            or source["runAttempt"] != 1
        ):
            validation.fail(
                f"/cells/{index}/sourceArtifact",
                "source artifact binding differs",
            )
        if (
            invocation["workflowSha"] != commit
            or invocation["runId"] != run_id
            or invocation["runAttempt"] != 1
            or invocation["workflowRun"]
            != f"https://github.com/enkyuan/alloy/actions/runs/{run_id}"
            or invocation["workflowRef"] != workflow_ref
        ):
            validation.fail(f"/cells/{index}/invocation", "workflow binding differs")
        if toolchain["node"] != runtime["version"]:
            validation.fail(f"/cells/{index}/toolchain/node", "runtime binding differs")
    if source_ids[0] == source_ids[1] or producer["id"] in source_ids:
        validation.fail("/cells", "artifact identities are not distinct")
    if package["name"] != TARBALL or producer["name"] != PRODUCER_NAME:
        validation.fail("/packageArtifact", "candidate identity differs")


def recompute_document(
    *,
    producer_archive: AuthenticatedArtifactArchive,
    node22_archive: AuthenticatedArtifactArchive,
    node24_archive: AuthenticatedArtifactArchive,
    expected_workflow_run: str,
    expected_workflow_ref: str,
    expected_workflow_sha: str,
) -> dict[str, Any]:
    """Reauthenticate and recompute every field from all three archive bytes."""

    return _compose(
        producer_archive=producer_archive,
        node22_archive=node22_archive,
        node24_archive=node24_archive,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_ref=expected_workflow_ref,
        expected_workflow_sha=expected_workflow_sha,
    )


def recompute_and_compare(
    document: Mapping[str, Any],
    *,
    producer_archive: AuthenticatedArtifactArchive,
    node22_archive: AuthenticatedArtifactArchive,
    node24_archive: AuthenticatedArtifactArchive,
    expected_workflow_run: str,
    expected_workflow_ref: str,
    expected_workflow_sha: str,
) -> None:
    """Strictly compare an aggregate with a fresh archive recomputation."""

    validate_document(document)
    recomputed = recompute_document(
        producer_archive=producer_archive,
        node22_archive=node22_archive,
        node24_archive=node24_archive,
        expected_workflow_run=expected_workflow_run,
        expected_workflow_ref=expected_workflow_ref,
        expected_workflow_sha=expected_workflow_sha,
    )
    if not _strict_equal(document, recomputed):
        validation.fail("/", "onboarding evidence recomputation differs")


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
        left.st_mode,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
        right.st_mode,
    )


def _require_writer_capabilities() -> None:
    required_constants = ("O_DIRECTORY", "O_NOFOLLOW")
    if (
        any(not hasattr(os, name) for name in required_constants)
        or any(
            function not in os.supports_dir_fd
            for function in _REQUIRED_DIR_FD_FUNCTIONS
        )
        or _REQUIRED_FOLLOW_SYMLINK_FUNCTION not in os.supports_follow_symlinks
    ):
        raise OSError


def _open_directory_anchor(parent: Path) -> _DirectoryAnchor:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptors: list[int] = []
    components: list[str] = []
    try:
        absolute = parent.is_absolute()
        descriptors.append(os.open("/" if absolute else ".", flags))
        parts = list(parent.parts)
        if absolute and parts and parts[0] == parent.anchor:
            parts = parts[1:]
        for component in parts:
            if (
                component in {"", ".", ".."}
                or "\x00" in component
                or "/" in component
                or "\\" in component
            ):
                raise OSError
            parent_fd = descriptors[-1]
            child_fd = os.open(component, flags, dir_fd=parent_fd)
            named = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            opened = os.fstat(child_fd)
            if (
                not stat.S_ISDIR(named.st_mode)
                or not stat.S_ISDIR(opened.st_mode)
                or not _same_inode(named, opened)
            ):
                os.close(child_fd)
                raise OSError
            descriptors.append(child_fd)
            components.append(component)
        anchor = _DirectoryAnchor(descriptors, components)
        _verify_directory_anchor(anchor)
        return anchor
    except OSError:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


def _verify_directory_anchor(anchor: _DirectoryAnchor) -> None:
    if len(anchor.descriptors) != len(anchor.components) + 1:
        raise OSError
    for descriptor in anchor.descriptors:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError
    final = os.fstat(anchor.directory_fd)
    if final.st_uid != os.geteuid() or stat.S_IMODE(final.st_mode) & 0o022:
        raise OSError
    for index, component in enumerate(anchor.components):
        named = os.stat(
            component,
            dir_fd=anchor.descriptors[index],
            follow_symlinks=False,
        )
        opened = os.fstat(anchor.descriptors[index + 1])
        if not stat.S_ISDIR(named.st_mode) or not _same_inode(named, opened):
            raise OSError


def _close_directory_anchor(anchor: _DirectoryAnchor | None) -> None:
    if anchor is None:
        return
    for descriptor in reversed(anchor.descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _destination_name(path: Path) -> str:
    name = path.name
    if not name or name in {".", ".."} or "\x00" in name or "/" in name or "\\" in name:
        raise OSError
    return name


def _create_exclusive_at(
    directory_fd: int,
    *,
    prefix: str,
    suffix: str,
    state: _WriteState,
    role: Literal["temporary", "recovery", "rollback"],
) -> tuple[int, str]:
    if role == "temporary":
        if state.temporary_fd is not None or state.temporary_name is not None:
            raise OSError
    elif role == "recovery":
        if state.recovery_fd is not None or state.recovery_name is not None:
            raise OSError
    elif role == "rollback":
        if state.rollback_fd is not None or state.rollback_name is not None:
            raise OSError
    else:
        raise OSError

    flags = (
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}{suffix}"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        if role == "temporary":
            state.temporary_fd = descriptor
            state.temporary_name = name
        elif role == "recovery":
            state.recovery_fd = descriptor
            state.recovery_name = name
        else:
            state.rollback_fd = descriptor
            state.rollback_name = name
        os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or not _same_inode(opened, named)
        ):
            raise OSError
        return descriptor, name
    raise OSError


def _write_fd(descriptor: int, encoded: bytes) -> None:
    offset = 0
    while offset < len(encoded):
        written = os.write(descriptor, encoded[offset:])
        if written < 1:
            raise OSError
        offset += written
    os.fsync(descriptor)


def _read_fd(descriptor: int, *, limit: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    output = bytearray()
    while True:
        chunk = os.read(descriptor, min(IO_CHUNK_BYTES, limit + 1 - len(output)))
        if not chunk:
            break
        output.extend(chunk)
        if len(output) > limit:
            raise OSError
    return bytes(output)


def _verify_named_fd(
    directory_fd: int,
    name: str,
    descriptor: int,
    *,
    expected: bytes,
) -> None:
    opened = os.fstat(descriptor)
    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or stat.S_IMODE(opened.st_mode) != 0o600
        or not _same_inode(opened, named)
        or opened.st_size != len(expected)
        or _read_fd(descriptor, limit=len(expected)) != expected
    ):
        raise OSError


def _read_destination(
    directory_fd: int, name: str
) -> tuple[bytes, os.stat_result] | None:
    try:
        named_before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(named_before.st_mode)
        or named_before.st_size > MAX_DESTINATION_BYTES
    ):
        raise OSError
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        opened_before = os.fstat(descriptor)
        if not _same_inode(named_before, opened_before):
            raise OSError
        encoded = _read_fd(descriptor, limit=MAX_DESTINATION_BYTES)
        opened_after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            len(encoded) != opened_before.st_size
            or not _same_file(opened_before, opened_after)
            or not _same_file(opened_after, named_after)
        ):
            raise OSError
        return encoded, named_after
    finally:
        os.close(descriptor)


def _destination_unchanged(
    directory_fd: int, name: str, previous: os.stat_result | None
) -> bool:
    try:
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return previous is None
    return (
        previous is not None
        and stat.S_ISREG(current.st_mode)
        and _same_file(current, previous)
    )


def _destination_matches_snapshot(
    directory_fd: int,
    name: str,
    previous_bytes: bytes | None,
    previous_stat: os.stat_result | None,
) -> bool:
    try:
        current = _read_destination(directory_fd, name)
    except OSError:
        return False
    if previous_bytes is None:
        return current is None and previous_stat is None
    return (
        current is not None
        and previous_stat is not None
        and current[0] == previous_bytes
        and _same_file(current[1], previous_stat)
    )


def _verify_installed(
    directory_fd: int,
    name: str,
    source_fd: int,
    expected: bytes,
) -> None:
    source = os.fstat(source_fd)
    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(source.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or stat.S_IMODE(named.st_mode) != 0o600
        or not _same_inode(source, named)
        or named.st_size != len(expected)
    ):
        raise OSError
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    installed_fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        installed_before = os.fstat(installed_fd)
        observed = _read_fd(installed_fd, limit=len(expected))
        installed_after = os.fstat(installed_fd)
        named_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            observed != expected
            or not _same_file(installed_before, installed_after)
            or not _same_file(installed_after, named_after)
            or not _same_inode(source, installed_after)
        ):
            raise OSError
    finally:
        os.close(installed_fd)


def _unlink_if_present(directory_fd: int, name: str | None) -> None:
    if name is None:
        return
    try:
        os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass


def _cleanup_names(directory_fd: int, names: tuple[str | None, ...]) -> bool:
    if not any(name is not None for name in names):
        return True
    durable = True
    for name in names:
        try:
            _unlink_if_present(directory_fd, name)
        except OSError:
            durable = False
    try:
        os.fsync(directory_fd)
    except OSError:
        durable = False
    return durable


def _close_fd(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _create_recovery(
    directory_fd: int,
    destination_name: str,
    previous_bytes: bytes,
    state: _WriteState,
) -> None:
    if not state.recovery_namespace_safe:
        raise OSError
    if state.recovery_name is not None:
        old_name = state.recovery_name
        try:
            _verify_named_fd(
                directory_fd,
                old_name,
                state.recovery_fd if state.recovery_fd is not None else -1,
                expected=previous_bytes,
            )
            os.fsync(directory_fd)
            return
        except OSError:
            _close_fd(state.recovery_fd)
            state.recovery_fd = None
            state.recovery_name = None
            try:
                os.unlink(old_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                state.recovery_namespace_safe = False
                raise
    if state.recovery_fd is not None:
        _close_fd(state.recovery_fd)
        state.recovery_fd = None
    descriptor, name = _create_exclusive_at(
        directory_fd,
        prefix=f".{destination_name}.",
        suffix=".recovery",
        state=state,
        role="recovery",
    )
    _write_fd(descriptor, previous_bytes)
    _verify_named_fd(
        directory_fd,
        name,
        descriptor,
        expected=previous_bytes,
    )
    os.fsync(directory_fd)


def _rollback(
    anchor: _DirectoryAnchor,
    destination_name: str,
    previous_bytes: bytes | None,
    state: _WriteState,
) -> None:
    directory_fd = anchor.directory_fd
    if previous_bytes is None:
        os.unlink(destination_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        _verify_directory_anchor(anchor)
        return

    _create_recovery(directory_fd, destination_name, previous_bytes, state)
    descriptor, name = _create_exclusive_at(
        directory_fd,
        prefix=f".{destination_name}.",
        suffix=".rollback",
        state=state,
        role="rollback",
    )
    _write_fd(descriptor, previous_bytes)
    _verify_named_fd(directory_fd, name, descriptor, expected=previous_bytes)
    _verify_directory_anchor(anchor)
    os.rename(
        name,
        destination_name,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
    )
    state.rollback_name = None
    _verify_installed(
        directory_fd,
        destination_name,
        descriptor,
        previous_bytes,
    )
    os.fsync(directory_fd)
    _verify_named_fd(
        directory_fd,
        state.recovery_name if state.recovery_name is not None else "",
        state.recovery_fd if state.recovery_fd is not None else -1,
        expected=previous_bytes,
    )
    os.unlink(
        state.recovery_name if state.recovery_name is not None else "",
        dir_fd=directory_fd,
    )
    state.recovery_name = None
    os.fsync(directory_fd)
    _verify_directory_anchor(anchor)


def write_json_atomic(path: Path, document: Mapping[str, Any]) -> str:
    """Write owner-only JSON through one descriptor-anchored transaction."""

    validate_document(document)
    encoded = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    anchor: _DirectoryAnchor | None = None
    state = _WriteState()
    previous_bytes: bytes | None = None
    previous_stat: os.stat_result | None = None
    snapshot_captured = False
    try:
        _require_writer_capabilities()
        destination_name = _destination_name(path)
        anchor = _open_directory_anchor(path.parent)
        directory_fd = anchor.directory_fd
        _verify_directory_anchor(anchor)
        previous = _read_destination(directory_fd, destination_name)
        previous_stat = None if previous is None else previous[1]
        previous_bytes = None if previous is None else previous[0]
        snapshot_captured = True
        if previous_bytes is not None:
            _create_recovery(
                directory_fd,
                destination_name,
                previous_bytes,
                state,
            )

        temporary_fd, temporary_name = _create_exclusive_at(
            directory_fd,
            prefix=f".{destination_name}.",
            suffix=".tmp",
            state=state,
            role="temporary",
        )
        _write_fd(temporary_fd, encoded)
        _verify_named_fd(
            directory_fd,
            temporary_name,
            temporary_fd,
            expected=encoded,
        )
        if not _destination_unchanged(
            directory_fd,
            destination_name,
            previous_stat,
        ):
            raise OSError
        _verify_directory_anchor(anchor)
        os.rename(
            temporary_name,
            destination_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        state.temporary_name = None
        state.replaced = True
        _verify_installed(
            directory_fd,
            destination_name,
            temporary_fd,
            encoded,
        )
        _verify_directory_anchor(anchor)
        os.fsync(directory_fd)
        if state.recovery_name is not None:
            _verify_named_fd(
                directory_fd,
                state.recovery_name,
                state.recovery_fd if state.recovery_fd is not None else -1,
                expected=previous_bytes if previous_bytes is not None else b"",
            )
            os.unlink(state.recovery_name, dir_fd=directory_fd)
            state.recovery_name = None
            os.fsync(directory_fd)
        _verify_installed(
            directory_fd,
            destination_name,
            temporary_fd,
            encoded,
        )
        _verify_directory_anchor(anchor)
        return digest
    except EvidenceWriteAmbiguous:
        raise
    except OSError:
        if anchor is not None and state.replaced:
            try:
                _rollback(
                    anchor,
                    _destination_name(path),
                    previous_bytes,
                    state,
                )
            except OSError:
                directory_fd = anchor.directory_fd
                cleanup_durable = _cleanup_names(
                    directory_fd,
                    (state.temporary_name, state.rollback_name),
                )
                state.temporary_name = None
                state.rollback_name = None
                if previous_bytes is not None:
                    try:
                        _create_recovery(
                            directory_fd,
                            _destination_name(path),
                            previous_bytes,
                            state,
                        )
                    except OSError:
                        pass
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                if state.recovery_name is None:
                    raise EvidenceWriteUnrecoverable() from None
                try:
                    _verify_named_fd(
                        directory_fd,
                        state.recovery_name,
                        state.recovery_fd if state.recovery_fd is not None else -1,
                        expected=previous_bytes if previous_bytes is not None else b"",
                    )
                except OSError:
                    raise EvidenceWriteUnrecoverable() from None
                recovery_name = state.recovery_name
                if not cleanup_durable:
                    raise EvidenceCleanupAmbiguous(recovery_name) from None
                raise EvidenceWriteAmbiguous(recovery_name) from None
        elif anchor is not None:
            directory_fd = anchor.directory_fd
            destination_name = _destination_name(path)
            if snapshot_captured and not _destination_matches_snapshot(
                directory_fd,
                destination_name,
                previous_bytes,
                previous_stat,
            ):
                cleanup_durable = _cleanup_names(
                    directory_fd,
                    (state.temporary_name, state.rollback_name),
                )
                state.temporary_name = None
                state.rollback_name = None
                if previous_bytes is None:
                    raise EvidenceWriteUnrecoverable() from None
                try:
                    _create_recovery(
                        directory_fd,
                        destination_name,
                        previous_bytes,
                        state,
                    )
                    if state.recovery_name is None:
                        raise OSError
                    _verify_named_fd(
                        directory_fd,
                        state.recovery_name,
                        state.recovery_fd if state.recovery_fd is not None else -1,
                        expected=previous_bytes,
                    )
                except OSError:
                    raise EvidenceWriteUnrecoverable() from None
                if not cleanup_durable:
                    raise EvidenceCleanupAmbiguous(state.recovery_name) from None
                raise EvidenceWriteAmbiguous(state.recovery_name) from None
            cleanup_durable = _cleanup_names(
                directory_fd,
                (
                    state.temporary_name,
                    state.rollback_name,
                    state.recovery_name,
                ),
            )
            state.temporary_name = None
            state.rollback_name = None
            state.recovery_name = None
            if not cleanup_durable:
                raise EvidenceCleanupAmbiguous() from None
        raise EvidenceError("/: onboarding evidence could not be written") from None
    finally:
        _close_fd(state.temporary_fd)
        _close_fd(state.recovery_fd)
        _close_fd(state.rollback_fd)
        _close_directory_anchor(anchor)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-archive", type=Path, required=True)
    parser.add_argument("--node22-archive", type=Path, required=True)
    parser.add_argument("--node24-archive", type=Path, required=True)
    parser.add_argument("--producer-artifact-id", type=int, required=True)
    parser.add_argument("--producer-artifact-digest", required=True)
    parser.add_argument("--node22-source-artifact-id", type=int, required=True)
    parser.add_argument("--node22-source-artifact-digest", required=True)
    parser.add_argument("--node24-source-artifact-id", type=int, required=True)
    parser.add_argument("--node24-source-artifact-digest", required=True)
    parser.add_argument("--expected-run-id", type=int, required=True)
    parser.add_argument("--expected-workflow-run", required=True)
    parser.add_argument("--expected-workflow-ref", required=True)
    parser.add_argument("--expected-workflow-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        common = {
            "run_id": args.expected_run_id,
            "run_attempt": 1,
            "head_sha": args.expected_workflow_sha,
            "expired": False,
        }
        inputs = {
            "producer_archive": load_authenticated_archive(
                args.producer_archive,
                name=PRODUCER_NAME,
                artifact_id=args.producer_artifact_id,
                digest=args.producer_artifact_digest,
                **common,
            ),
            "node22_archive": load_authenticated_archive(
                args.node22_archive,
                name="kaji-node-compat-22",
                artifact_id=args.node22_source_artifact_id,
                digest=args.node22_source_artifact_digest,
                **common,
            ),
            "node24_archive": load_authenticated_archive(
                args.node24_archive,
                name="kaji-node-compat-24",
                artifact_id=args.node24_source_artifact_id,
                digest=args.node24_source_artifact_digest,
                **common,
            ),
            "expected_workflow_run": args.expected_workflow_run,
            "expected_workflow_ref": args.expected_workflow_ref,
            "expected_workflow_sha": args.expected_workflow_sha,
        }
        document = compose_document(**inputs)
        recompute_and_compare(document, **inputs)
        digest = write_json_atomic(args.output, document)
    except EvidenceWriteAmbiguous as error:
        print(f"AMBIGUOUS: {error}")
        return 2
    except EvidenceWriteUnrecoverable as error:
        print(f"UNRECOVERABLE: {error}")
        return 3
    except EvidenceCleanupAmbiguous as error:
        print(f"CLEANUP_AMBIGUOUS: {error}")
        return 4
    except EvidenceError as error:
        print(f"FAIL: {error}")
        return 1
    except OSError:
        print("FAIL: onboarding evidence could not be read or written")
        return 1
    print(f"PASS: TypeScript onboarding evidence written sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
