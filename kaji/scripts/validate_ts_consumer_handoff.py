#!/usr/bin/env python3
"""Independently validate an immutable TypeScript consumer handoff bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
import re
import secrets
import stat
import sys
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator


MANIFEST_NAME = "kaji-sdk.manifest.json"
SCHEMA_NAME = "kaji-ts-consumer-handoff-v1.schema.json"
RECEIPT_NAMES = (
    "source-equivalence.json",
    "signature-verification.json",
    "pack-once.json",
    "artifact-contract.json",
    "node-22.json",
    "node-24.json",
)
RECEIPT_IDS = (
    "source-equivalence",
    "signature-verification",
    "pack-once",
    "artifact-contract",
    "node-22",
    "node-24",
)
RECEIPT_DIGEST_KEYS = (
    "sourceEquivalence",
    "signatureVerification",
    "packOnce",
    "artifactContract",
    "node22",
    "node24",
)
CHECKS = (
    "bundle-file-set",
    "schema-bytes",
    "canonical-json",
    "artifact-bytes",
    "archive-safety",
    "package-metadata",
    "receipt-set",
    "receipt-relations",
    "catalogs",
    "policy-before-token",
    "license",
    "signer-workflow",
)
FAILURE_CODES = frozenset(
    {
        "INVALID_ARGUMENT",
        "UNSAFE_PATH",
        "OUTPUT_EXISTS",
        "SOURCE_NOT_ISOLATED",
        "SOURCE_DIRTY",
        "SOURCE_COMMIT_MISMATCH",
        "TRUSTED_VERIFIER_NOT_ON_DEFAULT",
        "SIGNATURE_RANGE_EMPTY",
        "SIGNATURE_INVALID",
        "SIGNER_NOT_APPROVED",
        "TAG_INVALID",
        "TOOLCHAIN_MISMATCH",
        "REGISTRY_UNAVAILABLE",
        "BUILD_FAILED",
        "PACK_FAILED",
        "PACK_COUNT_INVALID",
        "ARTIFACT_CHANGED",
        "RECEIPT_INVALID",
        "SCHEMA_INVALID",
        "VALIDATION_FAILED",
        "TRANSPORT_UNTRUSTED",
        "ATTESTATION_INVALID",
        "IMPORT_COLLISION",
        "INTERNAL_ERROR",
    }
)

PACKAGE_NAME = "@kaji/sdk"
REPOSITORY_URL = "https://github.com/enkyuan/alloy.git"
SIGNER_REPOSITORY = "enkyuan/alloy"
SIGNER_FILE_PATH = ".github/workflows/kaji.handoff.trusted.yml"
LICENSE_ID = "FSL-1.1-ALv2"
LICENSE_METADATA = LICENSE_ID

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)
WINDOWS_DRIVE = re.compile(r"[A-Za-z]:[/\\]")
DANGEROUS_PREFIXES = ("/Users/", "/private/", "/tmp/", "/home/", "file:")

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "contracts/release/kaji-ts-consumer-handoff-v1.schema.json"
)
TRUSTED_LICENSE_PATH = Path(__file__).resolve().parents[1] / "ts/LICENSE"


class ValidationError(Exception):
    def __init__(
        self,
        code: str,
        *,
        source_commit: str | None = None,
        artifact_sha256: str | None = None,
    ) -> None:
        if code not in FAILURE_CODES:
            raise ValueError("unknown failure code")
        super().__init__(code)
        self.code = code
        self.source_commit = source_commit
        self.artifact_sha256 = artifact_sha256


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise ValidationError("INVALID_ARGUMENT")


def _reject(
    code: str,
    *,
    source_commit: str | None = None,
    artifact_sha256: str | None = None,
) -> NoReturn:
    raise ValidationError(
        code,
        source_commit=source_commit,
        artifact_sha256=artifact_sha256,
    )


def _canonical_json(document: Any) -> bytes:
    try:
        return (
            json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _reject("VALIDATION_FAILED")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _regular_directory(path: Path, *, code: str = "UNSAFE_PATH") -> Path:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        return path.resolve(strict=True)
    except OSError:
        _reject(code)


def _directory_files(path: Path, expected: set[str], *, code: str) -> dict[str, Path]:
    root = _regular_directory(path, code=code)
    try:
        children = list(root.iterdir())
    except OSError:
        _reject(code)
    if {child.name for child in children} != expected:
        _reject(code)
    files: dict[str, Path] = {}
    for child in children:
        try:
            metadata = child.lstat()
        except OSError:
            _reject(code)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            _reject(code)
        files[child.name] = child
    return files


def _read_regular(path: Path, *, limit: int, code: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise OSError
            payload = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > limit or _stat_identity(before) != _stat_identity(after):
            raise OSError
        return payload
    except OSError:
        _reject(code)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def _load_json(path: Path, *, code: str) -> tuple[dict[str, Any], bytes]:
    encoded = _read_regular(path, limit=MAX_JSON_BYTES, code=code)
    try:
        document = json.loads(
            encoded.decode("ascii"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        _reject(code)
    if not isinstance(document, dict) or _canonical_json(document) != encoded:
        _reject(code)
    return document, encoded


def _safe_stable_strings(value: Any) -> None:
    if isinstance(value, str):
        if value.startswith(DANGEROUS_PREFIXES) or WINDOWS_DRIVE.match(value):
            _reject("UNSAFE_PATH")
    elif isinstance(value, list):
        for item in value:
            _safe_stable_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            _safe_stable_strings(item)


def _npm_pack_basename(version: str) -> str:
    if SEMVER.fullmatch(version) is None:
        _reject("SCHEMA_INVALID")
    return f"kaji-sdk-{version}.tgz"


def _checked_archive_name(raw_name: str) -> str:
    if (
        not raw_name
        or raw_name.startswith("/")
        or "\\" in raw_name
        or not raw_name.isascii()
    ):
        _reject("UNSAFE_PATH")
    name = raw_name.rstrip("/")
    parts = name.split("/")
    if (
        not name
        or any(part in {"", ".", ".."} for part in parts)
        or posixpath.normpath(name) != name
        or not name.startswith("package/")
    ):
        _reject("UNSAFE_PATH")
    return name


def _archive_payload(
    archive: tarfile.TarFile, members: Mapping[str, tarfile.TarInfo], name: str
) -> bytes:
    member = members.get(name)
    if member is None or not member.isfile() or member.issym() or member.islnk():
        _reject("VALIDATION_FAILED")
    stream = archive.extractfile(member)
    if stream is None:
        _reject("VALIDATION_FAILED")
    payload = stream.read(member.size + 1)
    if len(payload) != member.size:
        _reject("VALIDATION_FAILED")
    return payload


def _artifact_and_archive(
    tarball: Path,
) -> tuple[int, str, str, list[str], dict[str, Any], bytes, dict[str, bytes]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(tarball, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size < 1:
                raise OSError
            sha256 = hashlib.sha256()
            sha512 = hashlib.sha512()
            while chunk := stream.read(READ_CHUNK_BYTES):
                sha256.update(chunk)
                sha512.update(chunk)
            stream.seek(0)
            members: dict[str, tarfile.TarInfo] = {}
            total_size = 0
            try:
                with tarfile.open(fileobj=stream, mode="r:gz") as archive:
                    for member in archive:
                        if len(members) >= MAX_ARCHIVE_MEMBERS:
                            _reject("UNSAFE_PATH")
                        name = _checked_archive_name(member.name)
                        if name in members or member.issym() or member.islnk():
                            _reject("UNSAFE_PATH")
                        if not (member.isfile() or member.isdir()):
                            _reject("UNSAFE_PATH")
                        if member.size > MAX_ARCHIVE_MEMBER_BYTES:
                            _reject("UNSAFE_PATH")
                        total_size += member.size
                        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                            _reject("UNSAFE_PATH")
                        if member.isfile() and member.mode & 0o111:
                            relative = name.removeprefix("package/")
                            if not (
                                relative.startswith("dist/cli/")
                                and relative.endswith(".js")
                            ):
                                _reject("UNSAFE_PATH")
                        members[name] = member

                    package_bytes = _archive_payload(
                        archive, members, "package/package.json"
                    )
                    license_bytes = _archive_payload(
                        archive, members, "package/LICENSE"
                    )
                    try:
                        package = json.loads(
                            package_bytes.decode("utf-8"),
                            parse_constant=lambda _value: (_ for _ in ()).throw(
                                ValueError()
                            ),
                        )
                    except (UnicodeError, json.JSONDecodeError, ValueError):
                        _reject("VALIDATION_FAILED")
                    if not isinstance(package, dict):
                        _reject("VALIDATION_FAILED")
                    payloads: dict[str, bytes] = {}
                    exports = package.get("exports")
                    if isinstance(exports, dict):
                        for target in _export_targets(exports):
                            archive_name = f"package/{target.removeprefix('./')}"
                            payloads[archive_name] = _archive_payload(
                                archive, members, archive_name
                            )
            except (tarfile.TarError, EOFError, OSError):
                _reject("VALIDATION_FAILED")
            after = os.fstat(stream.fileno())
            if _stat_identity(before) != _stat_identity(after):
                _reject("ARTIFACT_CHANGED")
    except OSError:
        _reject("UNSAFE_PATH")

    integrity = "sha512-" + base64.b64encode(sha512.digest()).decode("ascii")
    return (
        before.st_size,
        sha256.hexdigest(),
        integrity,
        sorted(members, key=lambda value: value.encode("ascii")),
        package,
        license_bytes,
        payloads,
    )


def _export_targets(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        targets: list[str] = []
        for child in value.values():
            targets.extend(_export_targets(child))
        return targets
    return []


def _validate_signer(expected: Mapping[str, str]) -> None:
    digest = expected["digest"]
    if (
        expected["repository"] != SIGNER_REPOSITORY
        or expected["filePath"] != SIGNER_FILE_PATH
        or HEX40.fullmatch(digest) is None
        or expected["ref"] != f"{SIGNER_REPOSITORY}/{SIGNER_FILE_PATH}@{digest}"
    ):
        _reject("INVALID_ARGUMENT")


def _validate_source_relations(
    manifest: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    expected_mode: str,
) -> None:
    root = manifest["source"]
    source = receipts[0]["evidence"]
    signature = receipts[1]["evidence"]
    if (
        source["repository"] != root["repository"]
        or source["headCommit"] != root["commit"]
        or signature["headCommit"] != root["commit"]
        or source["treeSha"] != root["tree"]
        or signature["treeSha"] != root["tree"]
        or source["mergeBase"] != root["mergeBase"]
        or signature["mergeBase"] != root["mergeBase"]
        or source["trustedVerifierCommit"] != root["verifierCommit"]
        or signature["verifierCommit"] != root["verifierCommit"]
        or root["signature"]["mechanism"] != signature["mechanism"]
    ):
        _reject("RECEIPT_INVALID")
    range_spec = f"{root['mergeBase']}..{root['commit']}"
    if source["revisionCommand"] != [
        "git",
        "rev-list",
        "--reverse",
        "--topo-order",
        range_spec,
    ]:
        _reject("RECEIPT_INVALID")
    if signature["range"] != source["range"]:
        _reject("RECEIPT_INVALID")
    expected_commits = source["range"] or [root["commit"]]
    commits = signature["commits"]
    if [item["sha"] for item in commits] != expected_commits:
        _reject("RECEIPT_INVALID")
    approved = signature["approvedSignerEmail"]
    if any(item["signerEmail"] != approved for item in commits):
        _reject("SIGNER_NOT_APPROVED")
    expected_mechanism = (
        "github-rest-commit-and-annotated-tag-verification"
        if expected_mode == "release"
        else "github-rest-commit-verification"
    )
    if (
        signature["mechanism"] != expected_mechanism
        or root["signature"]["mechanism"] != expected_mechanism
    ):
        _reject("RECEIPT_INVALID")
    tag = signature.get("tag")
    if expected_mode == "release":
        if not isinstance(tag, dict):
            _reject("RECEIPT_INVALID")
        if tag["targetCommit"] != root["commit"] or tag["taggerEmail"] != approved:
            _reject("TAG_INVALID")
    elif tag is not None:
        _reject("RECEIPT_INVALID")


def _validate_relations(
    manifest: Mapping[str, Any],
    receipt_documents: Sequence[Mapping[str, Any]],
    receipt_bytes: Sequence[bytes],
    *,
    expected_mode: str,
    expected_commit: str,
    expected_signer: Mapping[str, str],
    archive_members: Sequence[str],
    packed_package: Mapping[str, Any],
    license_bytes: bytes,
    export_payloads: Mapping[str, bytes],
    artifact_size: int,
    artifact_sha256: str,
    artifact_integrity: str,
) -> None:
    artifact = manifest["artifact"]
    package = manifest["package"]
    source_root = manifest["source"]
    embedded = manifest["upstreamVerification"]
    first_six = embedded[:6]
    gate = embedded[6]
    if (
        artifact["size"] != artifact_size
        or artifact["sha256"] != artifact_sha256
        or artifact["npmIntegrity"] != artifact_integrity
        or artifact["filename"] != _npm_pack_basename(package["version"])
    ):
        _reject(
            "ARTIFACT_CHANGED",
            source_commit=expected_commit,
            artifact_sha256=artifact_sha256,
        )
    if list(first_six) != list(receipt_documents):
        _reject("RECEIPT_INVALID")
    if [receipt["id"] for receipt in first_six] != list(RECEIPT_IDS):
        _reject("RECEIPT_INVALID")
    if source_root["commit"] != expected_commit:
        _reject("SOURCE_COMMIT_MISMATCH")
    if any(
        receipt["sourceCommit"] != expected_commit
        or receipt["artifactSha256"] != artifact_sha256
        for receipt in embedded
    ):
        _reject("RECEIPT_INVALID")

    if (
        packed_package.get("name") != PACKAGE_NAME
        or packed_package.get("version") != package["version"]
        or packed_package.get("exports") != package["exports"]
        or packed_package.get("license") != LICENSE_METADATA
    ):
        _reject("VALIDATION_FAILED")
    for target in _export_targets(package["exports"]):
        if not target.startswith("./dist/"):
            _reject("UNSAFE_PATH")
        if f"package/{target.removeprefix('./')}" not in export_payloads:
            _reject("VALIDATION_FAILED")
    public_symbols = package["publicSymbols"]["github"]
    github_export = package["exports"]["./integrations/github"]
    for branch in ("import", "require"):
        types_target = github_export[branch]["types"]
        declaration = export_payloads.get(f"package/{types_target.removeprefix('./')}")
        if declaration is None:
            _reject("VALIDATION_FAILED")
        try:
            source = declaration.decode("utf-8")
        except UnicodeError:
            _reject("VALIDATION_FAILED")
        if any(
            re.search(rf"\b{re.escape(symbol)}\b", source) is None
            for symbol in public_symbols
        ):
            _reject("VALIDATION_FAILED")

    artifact_contract = first_six[3]["evidence"]
    pack = first_six[2]["evidence"]
    node22 = first_six[4]["evidence"]
    node24 = first_six[5]["evidence"]
    if (
        pack["mode"] != expected_mode
        or pack["package"] != {"name": PACKAGE_NAME, "version": package["version"]}
        or pack["artifact"]
        != {
            "filename": artifact["filename"],
            "size": artifact_size,
            "npmIntegrity": artifact_integrity,
        }
        or pack["construction"] != artifact["construction"]
        or pack["reproducibility"] != artifact["reproducibility"]
    ):
        _reject("RECEIPT_INVALID")
    expected_registry = (
        "version-unused" if expected_mode == "release" else "not-claimed"
    )
    if pack["registry"] != {"status": expected_registry}:
        _reject("RECEIPT_INVALID")

    expected_member_digest = hashlib.sha256(
        b"".join(name.encode("ascii") + b"\n" for name in archive_members)
    ).hexdigest()
    if artifact_contract["packlist"] != {
        "memberCount": len(archive_members),
        "membersSha256": expected_member_digest,
    }:
        _reject("RECEIPT_INVALID")
    if (
        artifact_contract["package"]["exports"] != package["exports"]
        or artifact_contract["package"]["publicSymbols"] != public_symbols
    ):
        _reject("RECEIPT_INVALID")

    github = manifest["github"]
    typescript_catalog = artifact_contract["catalogs"]["typescript"]
    shared_catalog = artifact_contract["catalogs"]["shared"]
    if typescript_catalog != {
        "schemaVersion": github["abi"]["schemaVersion"],
        "catalogVersion": github["abi"]["catalogVersion"],
        "totalCount": github["totalCount"],
        "readCount": github["readCount"],
        "tools": github["tools"],
        "readTools": github["readTools"],
    }:
        _reject("RECEIPT_INVALID")
    if shared_catalog != {
        "manifestVersion": github["sharedManifestVersion"],
        "totalCount": github["shared"]["totalCount"],
        "readCount": github["shared"]["readCount"],
        "tools": github["shared"]["tools"],
        "readTools": github["shared"]["readTools"],
    }:
        _reject("RECEIPT_INVALID")
    if github["userAgentVersion"] != github["abi"]["catalogVersion"]:
        _reject("RECEIPT_INVALID")

    for install in artifact_contract["installs"].values():
        if install["artifactSha256"] != artifact_sha256:
            _reject("RECEIPT_INVALID")
    if (
        node22["installedArtifactSha256"] != artifact_sha256
        or node24["installedArtifactSha256"] != artifact_sha256
        or int(node22["nodeVersion"].split(".", 1)[0]) != 22
        or int(node24["nodeVersion"].split(".", 1)[0]) != 24
    ):
        _reject("RECEIPT_INVALID")

    policy = artifact_contract["policy"]
    if manifest["securityEvidence"]["policyBeforeRequest"] != {
        **policy,
        "result": "passed",
    }:
        _reject("RECEIPT_INVALID")
    if policy["tokenLookups"] != 0 or policy["requestAttempts"] != 0:
        _reject("RECEIPT_INVALID")

    trusted_license = _read_regular(
        TRUSTED_LICENSE_PATH, limit=MAX_ARCHIVE_MEMBER_BYTES, code="VALIDATION_FAILED"
    )
    license_digest = _sha256_bytes(license_bytes)
    if (
        license_bytes != trusted_license
        or manifest["license"]
        != {
            "id": LICENSE_ID,
            "file": "LICENSE",
            "sha256": license_digest,
            "competingUseApproved": False,
            "futureLicense": "Apache-2.0",
            "futureLicenseAfter": "second-anniversary",
        }
        or artifact_contract["license"] != {"id": LICENSE_ID, "sha256": license_digest}
    ):
        _reject("VALIDATION_FAILED")

    _validate_source_relations(manifest, first_six, expected_mode=expected_mode)
    if source_root["verifierCommit"] != expected_signer["digest"]:
        _reject("RECEIPT_INVALID")

    receipt_digests = {
        key: _sha256_bytes(encoded)
        for key, encoded in zip(RECEIPT_DIGEST_KEYS, receipt_bytes, strict=True)
    }
    expected_gate_id = (
        "release-gate" if expected_mode == "release" else "internal-evaluation-gate"
    )
    expected_public_claim = "eligible" if expected_mode == "release" else "not-claimed"
    if (
        gate["id"] != expected_gate_id
        or gate["evidence"]["mode"] != expected_mode
        or gate["evidence"]["registry"] != expected_registry
        or gate["evidence"]["signerWorkflow"] != expected_signer
        or gate["evidence"]["toolchain"] != pack["toolchain"]
        or gate["evidence"]["publicReleaseClaim"] != expected_public_claim
        or gate["evidence"]["licenseUseClaim"] != "permitted-purpose-only"
        or gate["evidence"]["receiptSha256"] != receipt_digests
    ):
        _reject("RECEIPT_INVALID")


def validate_bundle(
    *,
    bundle_dir: Path,
    receipts_dir: Path,
    expected_mode: str,
    expected_commit: str,
    expected_signer_repository: str,
    expected_signer_file_path: str,
    expected_signer_digest: str,
    expected_signer_ref: str,
) -> dict[str, Any]:
    if expected_mode not in {"release", "internal-evaluation"}:
        _reject("INVALID_ARGUMENT")
    if HEX40.fullmatch(expected_commit) is None:
        _reject("INVALID_ARGUMENT")
    expected_signer = {
        "repository": expected_signer_repository,
        "filePath": expected_signer_file_path,
        "digest": expected_signer_digest,
        "ref": expected_signer_ref,
    }
    _validate_signer(expected_signer)

    bundle_root = _regular_directory(bundle_dir)
    try:
        names = {child.name for child in bundle_root.iterdir()}
    except OSError:
        _reject("UNSAFE_PATH")
    if MANIFEST_NAME not in names or SCHEMA_NAME not in names or len(names) != 3:
        _reject("UNSAFE_PATH")
    tarball_names = names - {MANIFEST_NAME, SCHEMA_NAME}
    if len(tarball_names) != 1:
        _reject("UNSAFE_PATH")
    artifact_name = next(iter(tarball_names))
    bundle_files = _directory_files(bundle_root, names, code="UNSAFE_PATH")

    trusted_schema_bytes = _read_regular(
        SCHEMA_PATH, limit=MAX_JSON_BYTES, code="SCHEMA_INVALID"
    )
    supplied_schema_bytes = _read_regular(
        bundle_files[SCHEMA_NAME], limit=MAX_JSON_BYTES, code="SCHEMA_INVALID"
    )
    if supplied_schema_bytes != trusted_schema_bytes:
        _reject("SCHEMA_INVALID")
    try:
        schema = json.loads(trusted_schema_bytes.decode("utf-8"))
        Draft202012Validator.check_schema(schema)
    except Exception:
        _reject("SCHEMA_INVALID")

    manifest, manifest_bytes = _load_json(
        bundle_files[MANIFEST_NAME], code="SCHEMA_INVALID"
    )
    errors = list(Draft202012Validator(schema).iter_errors(manifest))
    if errors:
        _reject("SCHEMA_INVALID")
    _safe_stable_strings(manifest)
    if manifest["artifact"]["filename"] != artifact_name:
        _reject("ARTIFACT_CHANGED")

    receipt_files = _directory_files(
        receipts_dir, set(RECEIPT_NAMES), code="RECEIPT_INVALID"
    )
    loaded_receipts = [
        _load_json(receipt_files[name], code="RECEIPT_INVALID")
        for name in RECEIPT_NAMES
    ]
    receipt_documents = [item[0] for item in loaded_receipts]
    receipt_bytes = [item[1] for item in loaded_receipts]

    (
        artifact_size,
        artifact_sha256,
        artifact_integrity,
        archive_members,
        packed_package,
        license_bytes,
        export_payloads,
    ) = _artifact_and_archive(bundle_files[artifact_name])
    _validate_relations(
        manifest,
        receipt_documents,
        receipt_bytes,
        expected_mode=expected_mode,
        expected_commit=expected_commit,
        expected_signer=expected_signer,
        archive_members=archive_members,
        packed_package=packed_package,
        license_bytes=license_bytes,
        export_payloads=export_payloads,
        artifact_size=artifact_size,
        artifact_sha256=artifact_sha256,
        artifact_integrity=artifact_integrity,
    )
    gate = manifest["upstreamVerification"][6]
    return {
        "schemaVersion": 1,
        "command": "validate",
        "result": "passed",
        "mode": expected_mode,
        "sourceCommit": expected_commit,
        "artifact": {
            "filename": artifact_name,
            "size": artifact_size,
            "sha256": artifact_sha256,
            "npmIntegrity": artifact_integrity,
        },
        "manifestSha256": _sha256_bytes(manifest_bytes),
        "schemaSha256": _sha256_bytes(trusted_schema_bytes),
        "receiptSha256": gate["evidence"]["receiptSha256"],
        "signerWorkflow": expected_signer,
        "checks": list(CHECKS),
    }


def _atomic_write_absent(path: Path, payload: bytes) -> None:
    parent = _regular_directory(path.parent)
    destination = parent / path.name
    if os.path.lexists(destination):
        _reject("OUTPUT_EXISTS")
    temporary = parent / f".{path.name}.tmp-{secrets.token_hex(12)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        _reject("OUTPUT_EXISTS")
    except OSError:
        _reject("INTERNAL_ERROR")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _failure_document(error: ValidationError) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "command": "validate",
        "result": "failed",
        "failureCode": error.code,
        "sourceCommit": error.source_commit,
        "artifactSha256": error.artifact_sha256,
    }


def _write_failure(failure_dir: Path | None, error: ValidationError) -> None:
    encoded = _canonical_json(_failure_document(error))
    if failure_dir is not None:
        try:
            root = _regular_directory(failure_dir)
            destination = root / "validate.failure.json"
            if not os.path.lexists(destination):
                _atomic_write_absent(destination, encoded)
        except Exception:
            pass
    sys.stderr.buffer.write(encoded)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--receipts-dir", required=True, type=Path)
    parser.add_argument(
        "--expected-mode", required=True, choices=("release", "internal-evaluation")
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-signer-repository", required=True)
    parser.add_argument("--expected-signer-file-path", required=True)
    parser.add_argument("--expected-signer-digest", required=True)
    parser.add_argument("--expected-signer-ref", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--failure-dir", type=Path)
    return parser


def _run(argv: Sequence[str]) -> int:
    failure_dir: Path | None = None
    try:
        arguments = _parser().parse_args(argv)
        failure_dir = arguments.failure_dir
        if os.path.lexists(arguments.output):
            _reject("OUTPUT_EXISTS")
        validation = validate_bundle(
            bundle_dir=arguments.bundle_dir,
            receipts_dir=arguments.receipts_dir,
            expected_mode=arguments.expected_mode,
            expected_commit=arguments.expected_commit,
            expected_signer_repository=arguments.expected_signer_repository,
            expected_signer_file_path=arguments.expected_signer_file_path,
            expected_signer_digest=arguments.expected_signer_digest,
            expected_signer_ref=arguments.expected_signer_ref,
        )
        _atomic_write_absent(arguments.output, _canonical_json(validation))
    except ValidationError as error:
        _write_failure(failure_dir, error)
        return 2 if error.code == "INVALID_ARGUMENT" else 1
    except Exception:
        _write_failure(failure_dir, ValidationError("INTERNAL_ERROR"))
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return _run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
