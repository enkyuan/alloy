#!/usr/bin/env python3
"""Verify published beta bytes and reduce the monotonic publication state."""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, NoReturn, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from process_runner import METADATA_BUDGET, CommandError, run_checked


PYPI_PROJECT = "kaji"
PYPI_VERSION = "0.2.0b1"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PROJECT}/{PYPI_VERSION}/json"
NPM_PACKAGE = "kaji"
NPM_VERSION = "0.2.0-beta.11"
NPM_SPEC = f"{NPM_PACKAGE}@{NPM_VERSION}"
NPM_REGISTRY = "https://registry.npmjs.org/"
NPM_TARBALL = "kaji-0.2.0-beta.11.tgz"
NPM_PURL = "pkg:npm/kaji@0.2.0-beta.11"
USER_AGENT = "kaji-release-verifier/1"
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SHA1_PATTERN = re.compile(r"[0-9a-f]{40}")
ARTIFACT_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
NPM_IDENTITY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
TAG_PATTERN = re.compile(r"kaji-v0[.]2[.]0-beta[.]11")
WORKFLOW_PATH = ".github/workflows/kaji.publish.yml"
SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
IN_TOTO_STATEMENT_V1 = "https://in-toto.io/Statement/v1"
NPM_GITHUB_BUILD_TYPE = (
    "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1"
)
GITHUB_HOSTED_BUILDER = "https://github.com/actions/runner/github-hosted"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_PUBLISHER_RECEIPT_BYTES = 64 * 1024
MAX_ATTESTATION_JSON_BYTES = 16 * 1024 * 1024
MAX_DSSE_STATEMENT_BYTES = 256 * 1024
PUBLISHER_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "contracts/release/publisher-identity-receipt-v1.schema.json"
)
PUBLISHER_STATUS_REASONS = frozenset(
    {
        "publish_job_not_started",
        "receipt_outputs_missing",
        "receipt_artifact_metadata_mismatch",
        "receipt_download_failed",
        "receipt_invalid",
        "identity_check_failed",
    }
)
NO_RECEIPT_REASONS = frozenset(
    {
        "publish_job_not_started",
        "receipt_outputs_missing",
        "receipt_artifact_metadata_mismatch",
        "receipt_download_failed",
    }
)

PublicationState = Literal[
    "unpublished",
    "pypi_only",
    "npm_only",
    "both_published",
    "byte_verified",
    "npm_byte_verified",
]
PublicationTarget = Literal["dual", "npm"]
RegistryObservation = Literal["present", "absent", "unknown"]
RegistryVerification = Literal[
    "not_run", "failed", "byte_verified", "npm_byte_verified"
]
PublishResult = Literal["success", "failure", "cancelled", "skipped", "unknown"]

_PUBLISHED_BY_STATE: dict[PublicationState, frozenset[str]] = {
    "unpublished": frozenset(),
    "pypi_only": frozenset({"pypi"}),
    "npm_only": frozenset({"npm"}),
    "both_published": frozenset({"pypi", "npm"}),
    "byte_verified": frozenset({"pypi", "npm"}),
    "npm_byte_verified": frozenset({"npm"}),
}


class VerificationMismatch(RuntimeError):
    """Published immutable metadata, bytes, or attestations do not match."""


class VerificationUnavailable(RuntimeError):
    """Expected registry metadata or attestations have not propagated yet."""


class PublisherIdentityError(RuntimeError):
    """Raw publisher identity bytes are unsafe, malformed, or tuple-invalid."""

    def __init__(
        self,
        code: str,
        *,
        receipt_sha256: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.receipt_sha256 = receipt_sha256


def _trusted_https_host(url: str, allowed_host: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and hostname == allowed_host
        and port is None
        and parsed.username is None
        and parsed.password is None
    )


class _SameHostHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host: str) -> None:
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not _trusted_https_host(target, self.allowed_host):
            raise VerificationMismatch(
                "registry download redirect attempted to leave the expected host"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    state: PublicationState
    release_ready: bool
    install_recommendation: bool
    incident_code: str | None = None
    recovery: str | None = None


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def _reject_nonfinite(_: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _strict_json(encoded: bytes, *, max_bytes: int) -> Any:
    if not encoded or len(encoded) > max_bytes:
        raise VerificationMismatch("cryptographic verifier returned oversized evidence")
    try:
        return json.loads(
            encoded,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_closed_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise VerificationMismatch(
            "cryptographic verifier returned malformed JSON"
        ) from error


def _canonical_json_bytes(document: Any) -> bytes:
    try:
        return (
            json.dumps(
                document,
                allow_nan=False,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PublisherIdentityError("receipt_invalid") from error


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_stable_regular_file(path: Path, *, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        before_path = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_nlink != 1
            or before_path.st_size < 1
            or before_path.st_size > max_bytes
        ):
            raise OSError
        before_path_identity = _file_identity(before_path)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            before_identity = _file_identity(before)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before_identity != before_path_identity
            ):
                raise OSError
            encoded = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            after_identity = _file_identity(after)
        after_path = os.stat(path, follow_symlinks=False)
        after_path_identity = _file_identity(after_path)
        if (
            len(encoded) != before.st_size
            or len(encoded) > max_bytes
            or before_identity != after_identity
            or after_identity != after_path_identity
        ):
            raise OSError
        return encoded
    except OSError as error:
        raise PublisherIdentityError("receipt_invalid") from error


def _publisher_schema_validator() -> Any:
    try:
        schema = json.loads(PUBLISHER_SCHEMA.read_bytes())
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as error:
        raise PublisherIdentityError("receipt_schema_unavailable") from error
    return Draft202012Validator(schema)


def _valid_publisher(value: str | None) -> bool:
    if value is None or NPM_IDENTITY_PATTERN.fullmatch(value) is None:
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


def _github_run_id(workflow_run: str) -> int | None:
    match = re.fullmatch(
        r"https://github[.]com/enkyuan/alloy/actions/runs/([1-9][0-9]{0,15})",
        workflow_run,
    )
    if match is None:
        return None
    value = int(match.group(1))
    return value if value <= MAX_SAFE_INTEGER else None


def validate_publisher_identity_receipt(
    path: Path,
    *,
    expected_commit: str,
    expected_tag: str,
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
    expected_workflow_path: str,
    expected_workflow_sha: str,
    expected_publisher: str | None,
) -> tuple[dict[str, Any], str]:
    encoded = _read_stable_regular_file(path, max_bytes=MAX_PUBLISHER_RECEIPT_BYTES)
    receipt_sha256 = hashlib.sha256(encoded).hexdigest()
    try:
        document = json.loads(
            encoded,
            parse_constant=_reject_nonfinite,
            object_pairs_hook=_closed_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise PublisherIdentityError(
            "receipt_invalid", receipt_sha256=receipt_sha256
        ) from error
    if not isinstance(document, dict) or encoded != _canonical_json_bytes(document):
        raise PublisherIdentityError("receipt_invalid", receipt_sha256=receipt_sha256)
    errors = sorted(
        _publisher_schema_validator().iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise PublisherIdentityError("receipt_invalid", receipt_sha256=receipt_sha256)
    if (
        document.get("commit") != expected_commit
        or document.get("tag") != expected_tag
        or document.get("workflowRun") != expected_workflow_run
        or document.get("workflowRunAttempt") != expected_workflow_run_attempt
        or document.get("workflowPath") != expected_workflow_path
        or document.get("workflowSha") != expected_workflow_sha
        or document.get("workflowSha") != document.get("commit")
        or document.get("expectedPublisher") != expected_publisher
    ):
        raise PublisherIdentityError(
            "receipt_invalid",
            receipt_sha256=receipt_sha256,
        )
    actual = document.get("actualPublisher")
    conclusion = document.get("conclusion")
    failure_code = document.get("failureCode")
    if conclusion == "passed":
        valid_semantics = (
            expected_publisher is not None
            and actual == expected_publisher
            and document.get("exitCode") == 0
            and failure_code is None
        )
    elif failure_code == "publisher_mismatch":
        valid_semantics = (
            isinstance(actual, str)
            and expected_publisher is not None
            and actual != expected_publisher
        )
    else:
        valid_semantics = conclusion == "failed"
    if not valid_semantics:
        raise PublisherIdentityError(
            "receipt_invalid",
            receipt_sha256=receipt_sha256,
        )
    return document, receipt_sha256


def fetch(
    url: str, *, allowed_host: str | None = None, max_bytes: int = 2 * 1024 * 1024
) -> bytes:
    if allowed_host is not None and not _trusted_https_host(url, allowed_host):
        raise VerificationMismatch("registry URL is outside the expected host")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(
        *(
            (_SameHostHTTPSRedirectHandler(allowed_host),)
            if allowed_host is not None
            else ()
        )
    )
    with opener.open(request, timeout=30) as response:  # noqa: S310
        if allowed_host is not None and not _trusted_https_host(
            response.geturl(), allowed_host
        ):
            raise VerificationMismatch(
                "registry download redirected outside the expected host"
            )
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise VerificationMismatch(
                    "registry response has an invalid content length"
                ) from error
            if declared_length < 0 or declared_length > max_bytes:
                raise VerificationMismatch(
                    "registry response exceeds the expected size cap"
                )
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise VerificationMismatch(
                "registry response exceeds the expected size cap"
            )
        return payload


def manifest_data(
    artifacts: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = json.loads((artifacts / "manifest.json").read_text())
    return manifest, {entry["file"]: entry for entry in manifest["artifacts"]}


def _run_verifier(command: list[str], *, cwd: Path) -> bytes:
    completed = run_checked(
        command,
        cwd=cwd,
        budget=METADATA_BUDGET,
        capture=True,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationMismatch(f"{command[0]} cryptographic verification failed")
    return completed.stdout


def _integrity_url(filename: str) -> str:
    quoted = urllib.parse.quote(filename, safe="")
    return (
        f"https://pypi.org/integrity/{PYPI_PROJECT}/{PYPI_VERSION}/{quoted}/provenance"
    )


def _attestation_count(provenance: Any) -> int:
    if not isinstance(provenance, dict):
        return 0
    bundles = provenance.get("attestation_bundles")
    if not isinstance(bundles, list):
        return 0
    return sum(
        len(bundle.get("attestations", []))
        for bundle in bundles
        if isinstance(bundle, dict) and isinstance(bundle.get("attestations"), list)
    )


def verify_pypi(
    entries: dict[str, dict[str, Any]],
    *,
    downloads_dir: Path,
    repository: str,
    commit: str,
) -> dict[str, Any]:
    metadata = json.loads(
        fetch(PYPI_URL, allowed_host="pypi.org", max_bytes=2 * 1024 * 1024)
    )
    if not isinstance(metadata, dict):
        raise VerificationMismatch("PyPI returned malformed project metadata")
    info = metadata.get("info")
    if (
        not isinstance(info, dict)
        or info.get("name") != PYPI_PROJECT
        or info.get("version") != PYPI_VERSION
    ):
        raise VerificationMismatch("PyPI returned the wrong project or version")
    expected_names = {
        name for name, entry in entries.items() if entry["package"] == "python"
    }
    urls = metadata.get("urls")
    if not isinstance(urls, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("filename"), str)
        for item in urls
    ):
        raise VerificationMismatch("PyPI returned malformed file metadata")
    actual_names = [item["filename"] for item in urls]
    if len(actual_names) != len(set(actual_names)):
        raise VerificationMismatch("PyPI returned duplicate published files")
    unexpected_names = set(actual_names) - expected_names
    if unexpected_names:
        raise VerificationMismatch("PyPI published unexpected files")
    if expected_names - set(actual_names):
        raise VerificationUnavailable("PyPI expected file set has not propagated")

    repository_url = f"https://github.com/{repository}"
    files = []
    for item in sorted(urls, key=lambda value: str(value.get("filename"))):
        if not isinstance(item, dict):
            raise VerificationMismatch("PyPI returned malformed file metadata")
        name = item.get("filename")
        if not isinstance(name, str):
            raise VerificationMismatch("PyPI returned malformed file metadata")
        entry = entries[name]
        digests = item.get("digests")
        if not isinstance(digests, dict):
            raise VerificationMismatch(f"PyPI digest metadata is malformed for {name}")
        digest = digests.get("sha256")
        if digest != entry["sha256"] or item.get("size") != entry["size"]:
            raise VerificationMismatch(f"PyPI digest/size mismatch for {name}")
        direct_url = item.get("url")
        if not isinstance(direct_url, str):
            raise VerificationMismatch(f"PyPI direct URL missing for {name}")
        parsed = urllib.parse.urlparse(direct_url)
        if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org":
            raise VerificationMismatch(
                f"PyPI direct URL outside trusted host for {name}"
            )

        payload = fetch(
            direct_url,
            allowed_host="files.pythonhosted.org",
            max_bytes=entry["size"],
        )
        if (
            len(payload) != entry["size"]
            or hashlib.sha256(payload).hexdigest() != entry["sha256"]
        ):
            raise VerificationMismatch(
                f"downloaded PyPI file differs from manifest: {name}"
            )
        downloaded = downloads_dir / f"registry-{name}"
        downloaded.write_bytes(payload)

        integrity_url = _integrity_url(name)
        provenance_bytes = fetch(
            integrity_url, allowed_host="pypi.org", max_bytes=5 * 1024 * 1024
        )
        provenance = json.loads(provenance_bytes)
        if not isinstance(provenance, dict):
            raise VerificationMismatch(
                f"PyPI Integrity API returned malformed provenance for {name}"
            )
        attestation_count = _attestation_count(provenance)
        if attestation_count < 1:
            raise VerificationUnavailable(
                f"PyPI Integrity API has no attestations for {name}"
            )
        provenance_file = downloads_dir / f"registry-{name}.provenance.json"
        provenance_file.write_bytes(provenance_bytes)
        pypi_attestation_output = _run_verifier(
            [
                "pypi-attestations",
                "verify",
                "pypi",
                "--repository",
                repository_url,
                direct_url,
            ],
            cwd=downloads_dir,
        )
        pypi_attestation_file = downloads_dir / f"registry-{name}.pypi-attestations.txt"
        pypi_attestation_file.write_bytes(pypi_attestation_output)
        github_attestation_output = _run_verifier(
            [
                "gh",
                "attestation",
                "verify",
                str(downloaded),
                "-R",
                repository,
                "--signer-workflow",
                f"{repository}/.github/workflows/kaji.publish.yml",
                "--source-digest",
                commit,
                "--format",
                "json",
            ],
            cwd=downloads_dir,
        )
        github_attestation_file = (
            downloads_dir / f"registry-{name}.github-attestation.json"
        )
        github_attestation_file.write_bytes(github_attestation_output)
        files.append(
            {
                "filename": name,
                "downloadedFile": downloaded.name,
                "directUrl": direct_url,
                "integrityUrl": integrity_url,
                "integrityFile": provenance_file.name,
                "integritySha256": hashlib.sha256(provenance_bytes).hexdigest(),
                "attestationCount": attestation_count,
                "pypiAttestationFile": pypi_attestation_file.name,
                "githubAttestationFile": github_attestation_file.name,
                "githubSourceCommit": commit,
                "sha256": entry["sha256"],
                "size": entry["size"],
                "byteVerified": True,
                "pypiAttestationVerified": True,
                "githubAttestationVerified": True,
            }
        )
    return {"metadataUrl": PYPI_URL, "files": files}


def parse_integrity(integrity: str) -> tuple[str, bytes]:
    if not isinstance(integrity, str) or not integrity:
        raise VerificationMismatch("npm returned an empty integrity value")
    if re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", integrity) is None:
        raise VerificationMismatch(
            "npm integrity must be exactly one canonical sha512 token"
        )
    encoded = integrity.removeprefix("sha512-")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise VerificationMismatch(
            "npm returned malformed integrity metadata"
        ) from error
    if (
        len(decoded) != hashlib.sha512().digest_size
        or base64.b64encode(decoded).decode("ascii") != encoded
    ):
        raise VerificationMismatch(
            "npm integrity must be canonical sha512 with a 64-byte digest"
        )
    return "sha512", decoded


def validate_shasum(shasum: Any, payload: bytes) -> str:
    if not isinstance(shasum, str) or SHA1_PATTERN.fullmatch(shasum) is None:
        raise VerificationMismatch(
            "npm shasum must be exactly 40 lowercase hexadecimal characters"
        )
    if hashlib.sha1(payload).hexdigest() != shasum:  # noqa: S324
        raise VerificationMismatch("downloaded npm tarball fails registry shasum")
    return shasum


def _exact_keys(value: Any, expected: set[str], message: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise VerificationMismatch(message)
    return value


def _positive_safe_integer(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _statement_identity(
    *,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> dict[str, str]:
    ref = f"refs/tags/{tag}"
    repository_url = f"https://github.com/{repository}"
    workflow_uri = f"{repository_url}/{workflow_path}@{ref}"
    invocation = (
        f"{repository_url}/actions/runs/{workflow_run_id}/"
        f"attempts/{workflow_run_attempt}"
    )
    return {
        "ref": ref,
        "repositoryUrl": repository_url,
        "workflowUri": workflow_uri,
        "invocation": invocation,
    }


def _validate_provenance_statement(
    statement: Any,
    *,
    payload: bytes,
    subject_name: str,
    digest_algorithm: str,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    require_npm_statement: bool,
) -> dict[str, Any]:
    root = _exact_keys(
        statement,
        {"_type", "subject", "predicateType", "predicate"},
        "attestation statement has an unexpected shape",
    )
    if (
        root["_type"] != IN_TOTO_STATEMENT_V1
        or root["predicateType"] != SLSA_PROVENANCE_V1
    ):
        raise VerificationMismatch("attestation statement type is not SLSA v1")
    subjects = root["subject"]
    if not isinstance(subjects, list) or not subjects:
        raise VerificationMismatch("attestation must have at least one subject")
    if require_npm_statement and len(subjects) != 1:
        raise VerificationMismatch("npm attestation must have exactly one subject")
    expected_digest = hashlib.new(digest_algorithm, payload).hexdigest()
    target_matches = 0
    observed_names: set[str] = set()
    for candidate in subjects:
        subject = _exact_keys(
            candidate,
            {"name", "digest"},
            "attestation subject has an unexpected shape",
        )
        name = subject["name"]
        digest = _exact_keys(
            subject["digest"],
            {digest_algorithm},
            "attestation subject digest has an unexpected shape",
        )
        digest_value = digest[digest_algorithm]
        if (
            not isinstance(name, str)
            or not name
            or name in observed_names
            or not isinstance(digest_value, str)
            or re.fullmatch(r"[0-9a-f]+", digest_value) is None
            or len(digest_value) != len(expected_digest)
        ):
            raise VerificationMismatch("attestation subject is malformed or duplicated")
        observed_names.add(name)
        if name == subject_name and digest_value == expected_digest:
            target_matches += 1
    if target_matches != 1:
        raise VerificationMismatch("attestation subject does not match npm bytes")

    predicate = _exact_keys(
        root["predicate"],
        {"buildDefinition", "runDetails"},
        "attestation predicate has an unexpected shape",
    )
    build = _exact_keys(
        predicate["buildDefinition"],
        {
            "buildType",
            "externalParameters",
            "internalParameters",
            "resolvedDependencies",
        },
        "attestation build definition has an unexpected shape",
    )
    permitted_build_types = {NPM_GITHUB_BUILD_TYPE}
    if not require_npm_statement:
        permitted_build_types.add("https://actions.github.io/buildtypes/workflow/v1")
    if build["buildType"] not in permitted_build_types:
        raise VerificationMismatch("attestation build type is not GitHub workflow v1")
    external = _exact_keys(
        build["externalParameters"],
        {"workflow"},
        "attestation external parameters have an unexpected shape",
    )
    workflow = _exact_keys(
        external["workflow"],
        {"ref", "repository", "path"},
        "attestation workflow has an unexpected shape",
    )
    identity = _statement_identity(
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )
    if workflow != {
        "ref": identity["ref"],
        "repository": identity["repositoryUrl"],
        "path": workflow_path,
    }:
        raise VerificationMismatch("attestation workflow identity mismatch")
    if not isinstance(build["internalParameters"], dict):
        raise VerificationMismatch("attestation internal parameters are malformed")
    dependencies = build["resolvedDependencies"]
    expected_dependency = {
        "uri": f"git+{identity['repositoryUrl']}@{identity['ref']}",
        "digest": {"gitCommit": commit},
    }
    if dependencies != [expected_dependency]:
        raise VerificationMismatch(
            "attestation resolved dependency does not match the peeled tag"
        )
    run_details = _exact_keys(
        predicate["runDetails"],
        {"builder", "metadata"},
        "attestation run details have an unexpected shape",
    )
    builder = _exact_keys(
        run_details["builder"],
        {"id"},
        "attestation builder has an unexpected shape",
    )
    if require_npm_statement:
        builder_valid = builder["id"] == GITHUB_HOSTED_BUILDER
    else:
        builder_valid = builder["id"] in {
            GITHUB_HOSTED_BUILDER,
            identity["workflowUri"],
        }
    metadata = _exact_keys(
        run_details["metadata"],
        {"invocationId"},
        "attestation invocation metadata has an unexpected shape",
    )
    if not builder_valid or metadata["invocationId"] != identity["invocation"]:
        raise VerificationMismatch("attestation run identity mismatch")
    return {
        "name": subject_name,
        "digestAlgorithm": digest_algorithm,
        "digest": expected_digest,
        "repository": repository,
        "workflowPath": workflow_path,
        "workflowRef": identity["ref"],
        "commit": commit,
        "workflowRunId": workflow_run_id,
        "workflowRunAttempt": workflow_run_attempt,
        "builder": builder["id"],
        "buildType": build["buildType"],
    }


def _decode_dsse_statement(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise VerificationMismatch("npm attestation bundle is malformed")
    envelope = bundle.get("dsseEnvelope")
    envelope = _exact_keys(
        envelope,
        {"payloadType", "payload", "signatures"},
        "npm DSSE envelope has an unexpected shape",
    )
    if envelope["payloadType"] != "application/vnd.in-toto+json":
        raise VerificationMismatch("npm DSSE payload type is invalid")
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or len(signatures) != 1:
        raise VerificationMismatch("npm keyless provenance signature is not singleton")
    signature = signatures[0]
    if not isinstance(signature, dict) or set(signature) not in (
        {"sig"},
        {"sig", "keyid"},
    ):
        raise VerificationMismatch("npm keyless provenance signature is malformed")
    if signature.get("keyid") not in (None, ""):
        raise VerificationMismatch("npm SLSA provenance bundle is not keyless")
    encoded_signature = signature.get("sig")
    if not isinstance(encoded_signature, str):
        raise VerificationMismatch("npm keyless provenance signature is malformed")
    try:
        signature_bytes = base64.b64decode(encoded_signature, validate=True)
    except (ValueError, binascii.Error) as error:
        raise VerificationMismatch(
            "npm keyless provenance signature is malformed"
        ) from error
    if (
        not signature_bytes
        or base64.b64encode(signature_bytes).decode("ascii") != encoded_signature
    ):
        raise VerificationMismatch("npm keyless provenance signature is malformed")
    encoded_payload = envelope["payload"]
    if not isinstance(encoded_payload, str):
        raise VerificationMismatch("npm DSSE payload is malformed")
    try:
        payload = base64.b64decode(encoded_payload, validate=True)
    except (ValueError, binascii.Error) as error:
        raise VerificationMismatch("npm DSSE payload is malformed") from error
    if (
        not payload
        or len(payload) > MAX_DSSE_STATEMENT_BYTES
        or base64.b64encode(payload).decode("ascii") != encoded_payload
    ):
        raise VerificationMismatch("npm DSSE payload is noncanonical or oversized")
    statement = _strict_json(payload, max_bytes=MAX_DSSE_STATEMENT_BYTES)
    if not isinstance(statement, dict):
        raise VerificationMismatch("npm DSSE statement must be an object")
    return statement


def parse_npm_audit_output(
    output: bytes,
    *,
    payload: bytes,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if workflow_sha != commit:
        raise VerificationMismatch("publish workflow SHA must equal the peeled commit")
    audit = _strict_json(output, max_bytes=MAX_ATTESTATION_JSON_BYTES)
    root = _exact_keys(
        audit,
        {"invalid", "missing", "verified"},
        "npm signature audit returned an unexpected npm 11.16.0 shape",
    )
    if not isinstance(root["invalid"], list) or root["invalid"]:
        raise VerificationMismatch("npm signature audit reported invalid signatures")
    if not isinstance(root["missing"], list):
        raise VerificationMismatch("npm signature audit missing field is malformed")
    if root["missing"]:
        raise VerificationUnavailable(
            "npm signature audit has not propagated attestations"
        )
    verified = root["verified"]
    if not isinstance(verified, list) or not verified:
        raise VerificationUnavailable("npm signature audit has not propagated packages")
    expected_keys = {
        "name",
        "version",
        "location",
        "registry",
        "attestations",
        "attestationBundles",
    }
    for entry in verified:
        _exact_keys(
            entry,
            expected_keys,
            "npm signature audit verified entry has an unexpected shape",
        )
    targets = [
        entry
        for entry in verified
        if entry["name"] == NPM_PACKAGE and entry["version"] == NPM_VERSION
    ]
    if not targets:
        raise VerificationUnavailable(
            "npm signature audit has not propagated the beta package"
        )
    if len(targets) != 1:
        raise VerificationMismatch(
            "npm signature audit returned duplicate beta entries"
        )
    target = targets[0]
    if (
        target["location"] != f"node_modules/{NPM_PACKAGE}"
        or target["registry"] != NPM_REGISTRY
    ):
        raise VerificationMismatch("npm signature audit target identity mismatch")
    attestations = target["attestations"]
    provenance_marker = (
        attestations.get("provenance") if isinstance(attestations, dict) else None
    )
    if (
        not isinstance(attestations, dict)
        or set(attestations) != {"url", "provenance"}
        or not isinstance(attestations.get("url"), str)
        or not isinstance(provenance_marker, dict)
        or set(provenance_marker) != {"predicateType"}
        or provenance_marker.get("predicateType") != SLSA_PROVENANCE_V1
    ):
        raise VerificationMismatch(
            "npm signature audit attestation pointer is malformed"
        )
    try:
        attestation_url = urllib.parse.urlparse(attestations["url"])
        attestation_port = attestation_url.port
    except ValueError as error:
        raise VerificationMismatch(
            "npm signature audit attestation pointer is malformed"
        ) from error
    if (
        attestation_url.scheme != "https"
        or attestation_url.hostname != "registry.npmjs.org"
        or attestation_port is not None
        or attestation_url.username is not None
        or attestation_url.password is not None
        or attestation_url.query
        or attestation_url.fragment
        or attestation_url.path != f"/-/npm/v1/attestations/{NPM_PACKAGE}@{NPM_VERSION}"
    ):
        raise VerificationMismatch("npm signature audit attestation pointer mismatch")
    bundles = target["attestationBundles"]
    if not isinstance(bundles, list):
        raise VerificationMismatch("npm signature audit bundles are malformed")
    for entry in bundles:
        bundle_entry = _exact_keys(
            entry,
            {"predicateType", "bundle", "signedAccessSignatureUrl"},
            "npm signature audit bundle entry has an unexpected shape",
        )
        if bundle_entry["signedAccessSignatureUrl"] != "":
            raise VerificationMismatch(
                "npm signature audit signed access signature URL is unexpected"
            )
    provenance = [
        entry for entry in bundles if entry["predicateType"] == SLSA_PROVENANCE_V1
    ]
    if not provenance:
        raise VerificationUnavailable(
            "npm signature audit has not propagated the beta attestation bundle"
        )
    if len(provenance) != 1:
        raise VerificationMismatch(
            "npm signature audit returned duplicate beta provenance bundles"
        )
    selected = provenance[0]["bundle"]
    statement = _decode_dsse_statement(selected)
    normalized = _validate_provenance_statement(
        statement,
        payload=payload,
        subject_name=NPM_PURL,
        digest_algorithm="sha512",
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        require_npm_statement=True,
    )
    return (
        {
            "verifiedEntries": len(verified),
            "packageVerified": True,
            "attestationsIncluded": True,
            "target": {
                "name": target["name"],
                "version": target["version"],
                "location": target["location"],
                "registry": target["registry"],
            },
            "provenance": normalized,
            "outputSha256": hashlib.sha256(output).hexdigest(),
        },
        selected,
        statement,
    )


def _run_npm_registry_command(command: list[str], *, cwd: Path) -> bytes:
    """Run npm propagation checks without downgrading invalid signatures."""
    completed = run_checked(
        command,
        cwd=cwd,
        budget=METADATA_BUDGET,
        capture=True,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    combined = completed.stdout + b"\n" + completed.stderr
    audit: Any = None
    try:
        audit = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    invalid = audit.get("invalid") if isinstance(audit, dict) else None
    if invalid or (b"invalid" in combined.lower() and b"signature" in combined.lower()):
        raise VerificationMismatch("npm signature audit reported invalid signatures")
    raise VerificationUnavailable(
        "npm registry signature evidence is not available yet"
    )


def validate_gh_attestation_output(
    output: bytes,
    *,
    payload: bytes,
    subject_name: str,
    digest_algorithm: str,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    require_npm_statement: bool,
) -> dict[str, Any]:
    if workflow_sha != commit:
        raise VerificationMismatch("publish workflow SHA must equal the peeled commit")
    decoded = _strict_json(output, max_bytes=MAX_ATTESTATION_JSON_BYTES)
    if not isinstance(decoded, list) or len(decoded) != 1:
        raise VerificationMismatch(
            "gh attestation verification must return exactly one result"
        )
    entry = _exact_keys(
        decoded[0],
        {"attestation", "verificationResult"},
        "gh attestation result has an unexpected shape",
    )
    if not isinstance(entry["attestation"], dict):
        raise VerificationMismatch("gh attestation result omits the verified bundle")
    result = entry["verificationResult"]
    if not isinstance(result, dict) or not {"statement", "signature"}.issubset(result):
        raise VerificationMismatch("gh attestation verification result is malformed")
    statement = _validate_provenance_statement(
        result["statement"],
        payload=payload,
        subject_name=subject_name,
        digest_algorithm=digest_algorithm,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        require_npm_statement=require_npm_statement,
    )
    signature = result["signature"]
    if not isinstance(signature, dict) or not isinstance(
        signature.get("certificate"), dict
    ):
        raise VerificationMismatch("gh attestation certificate is missing")
    certificate = signature["certificate"]
    identity = _statement_identity(
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )
    expected_certificate = {
        "subjectAlternativeName": identity["workflowUri"],
        "issuer": "https://token.actions.githubusercontent.com",
        "githubWorkflowSHA": workflow_sha,
        "githubWorkflowRepository": repository,
        "githubWorkflowRef": identity["ref"],
        "buildSignerURI": identity["workflowUri"],
        "buildSignerDigest": workflow_sha,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": identity["repositoryUrl"],
        "sourceRepositoryDigest": commit,
        "sourceRepositoryRef": identity["ref"],
        "buildConfigURI": identity["workflowUri"],
        "buildConfigDigest": workflow_sha,
        "runInvocationURI": identity["invocation"],
        "sourceRepositoryVisibilityAtSigning": "public",
    }
    if any(
        certificate.get(key) != value for key, value in expected_certificate.items()
    ):
        raise VerificationMismatch("gh attestation certificate identity mismatch")
    return {
        "statement": statement,
        "certificate": expected_certificate,
        "outputSha256": hashlib.sha256(output).hexdigest(),
    }


def _gh_attestation_command(
    downloaded: Path,
    *,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_sha: str,
    digest_algorithm: str,
    bundle_file: Path | None,
) -> list[str]:
    command = [
        "gh",
        "attestation",
        "verify",
        str(downloaded),
        "--repo",
        repository,
    ]
    if bundle_file is not None:
        command.extend(["--bundle", str(bundle_file)])
    command.extend(
        [
            "--digest-alg",
            digest_algorithm,
            "--signer-workflow",
            f"{repository}/{workflow_path}",
            "--signer-digest",
            workflow_sha,
            "--source-ref",
            f"refs/tags/{tag}",
            "--source-digest",
            commit,
            "--predicate-type",
            SLSA_PROVENANCE_V1,
            "--deny-self-hosted-runners",
            "--format",
            "json",
        ]
    )
    return command


def _verify_npm_audit(
    *,
    repository_dir: Path,
    evidence_file: Path,
    bundle_file: Path,
    payload: bytes,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> dict[str, Any]:
    (repository_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "kaji-registry-verification",
                "private": True,
                "dependencies": {NPM_PACKAGE: NPM_VERSION},
            }
        )
        + "\n"
    )
    (repository_dir / ".npmrc").write_text(
        f"registry={NPM_REGISTRY}\nignore-scripts=true\n"
    )
    _run_npm_registry_command(
        ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=repository_dir,
    )
    output = _run_npm_registry_command(
        ["npm", "audit", "signatures", "--json", "--include-attestations"],
        cwd=repository_dir,
    )
    evidence_file.write_bytes(output)
    summary, selected_bundle, _ = parse_npm_audit_output(
        output,
        payload=payload,
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_sha=workflow_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )
    bundle_file.write_bytes(
        json.dumps(selected_bundle, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    return {
        **summary,
        "evidenceFile": evidence_file.name,
        "bundleFile": bundle_file.name,
        "bundleSha256": hashlib.sha256(bundle_file.read_bytes()).hexdigest(),
    }


def verify_npm(
    entries: dict[str, dict[str, Any]],
    *,
    downloads_dir: Path,
    repository: str,
    commit: str,
    tag: str,
    workflow_path: str,
    workflow_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> dict[str, Any]:
    completed = run_checked(
        ["npm", "view", NPM_SPEC, "dist", "--json", f"--registry={NPM_REGISTRY}"],
        cwd=Path.cwd(),
        budget=METADATA_BUDGET,
        capture=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("npm metadata is not available yet")
    dist = _strict_json(completed.stdout, max_bytes=2 * 1024 * 1024)
    if not isinstance(dist, dict):
        raise VerificationMismatch("npm returned malformed dist metadata")
    tarball_url = dist.get("tarball")
    integrity = dist.get("integrity")
    if not isinstance(tarball_url, str):
        raise VerificationMismatch("npm dist tarball metadata is missing or malformed")
    if not isinstance(integrity, str):
        raise VerificationMismatch(
            "npm dist integrity metadata is missing or malformed"
        )
    try:
        parsed = urllib.parse.urlparse(tarball_url)
        tarball_port = parsed.port
    except ValueError as error:
        raise VerificationMismatch(
            "npm tarball URL is outside the expected registry"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "registry.npmjs.org"
        or tarball_port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != f"/{NPM_PACKAGE}/-/{NPM_TARBALL}"
    ):
        raise VerificationMismatch("npm tarball URL is outside the expected registry")
    entry = entries.get(NPM_TARBALL)
    if not isinstance(entry, dict):
        raise VerificationMismatch("release manifest omits the npm beta artifact")
    payload = fetch(
        tarball_url,
        allowed_host="registry.npmjs.org",
        max_bytes=entry["size"],
    )
    if (
        len(payload) != entry["size"]
        or hashlib.sha256(payload).hexdigest() != entry["sha256"]
    ):
        raise VerificationMismatch("downloaded npm tarball differs from manifest")
    algorithm, expected_integrity = parse_integrity(integrity)
    if hashlib.new(algorithm, payload).digest() != expected_integrity:
        raise VerificationMismatch("downloaded npm tarball fails registry integrity")
    shasum = validate_shasum(dist.get("shasum"), payload)

    downloaded = downloads_dir / f"registry-{entry['file']}"
    downloaded.write_bytes(payload)
    npm_audit_file = downloads_dir / "npm-signature-audit.json"
    npm_bundle_file = downloads_dir / "npm-provenance.sigstore.json"
    with tempfile.TemporaryDirectory(prefix="kaji-npm-signatures-") as temporary:
        signature_audit = _verify_npm_audit(
            repository_dir=Path(temporary),
            evidence_file=npm_audit_file,
            bundle_file=npm_bundle_file,
            payload=payload,
            repository=repository,
            commit=commit,
            tag=tag,
            workflow_path=workflow_path,
            workflow_sha=workflow_sha,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
    offline_output = _run_verifier(
        _gh_attestation_command(
            downloaded,
            repository=repository,
            commit=commit,
            tag=tag,
            workflow_path=workflow_path,
            workflow_sha=workflow_sha,
            digest_algorithm="sha512",
            bundle_file=npm_bundle_file,
        ),
        cwd=downloads_dir,
    )
    offline_file = downloads_dir / f"registry-{entry['file']}.npm-attestation.json"
    offline_file.write_bytes(offline_output)
    offline_attestation = validate_gh_attestation_output(
        offline_output,
        payload=payload,
        subject_name=NPM_PURL,
        digest_algorithm="sha512",
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_sha=workflow_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        require_npm_statement=True,
    )
    github_attestation_output = _run_verifier(
        _gh_attestation_command(
            downloaded,
            repository=repository,
            commit=commit,
            tag=tag,
            workflow_path=workflow_path,
            workflow_sha=workflow_sha,
            digest_algorithm="sha256",
            bundle_file=None,
        ),
        cwd=downloads_dir,
    )
    github_attestation_file = (
        downloads_dir / f"registry-{entry['file']}.github-attestation.json"
    )
    github_attestation_file.write_bytes(github_attestation_output)
    online_attestation = validate_gh_attestation_output(
        github_attestation_output,
        payload=payload,
        subject_name=entry["file"],
        digest_algorithm="sha256",
        repository=repository,
        commit=commit,
        tag=tag,
        workflow_path=workflow_path,
        workflow_sha=workflow_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        require_npm_statement=False,
    )
    return {
        "filename": entry["file"],
        "downloadedFile": downloaded.name,
        "integrity": integrity,
        "shasum": shasum,
        "tarball": tarball_url,
        "sha256": entry["sha256"],
        "size": entry["size"],
        "byteVerified": True,
        "githubAttestationVerified": True,
        "githubAttestationFile": github_attestation_file.name,
        "githubAttestation": online_attestation,
        "npmBundleAttestationVerified": True,
        "npmBundleAttestationFile": offline_file.name,
        "npmBundleAttestation": offline_attestation,
        "githubSourceCommit": commit,
        "signatureAudit": signature_audit,
    }


def _observed_state(
    pypi: RegistryObservation, npm: RegistryObservation
) -> PublicationState:
    if pypi == "present" and npm == "present":
        return "both_published"
    if pypi == "present":
        return "pypi_only"
    if npm == "present":
        return "npm_only"
    return "unpublished"


def _incident(state: PublicationState, code: str) -> PublicationDecision:
    return PublicationDecision(
        state=state,
        release_ready=False,
        install_recommendation=False,
        incident_code=code,
        recovery="fix_forward_next_beta",
    )


def reduce_publication_state(
    *,
    previous_state: PublicationState,
    pypi: RegistryObservation,
    npm: RegistryObservation,
    registry_verification: RegistryVerification,
    pypi_publish_result: PublishResult = "skipped",
    npm_publish_result: PublishResult = "skipped",
    target: PublicationTarget = "dual",
) -> PublicationDecision:
    if previous_state not in _PUBLISHED_BY_STATE:
        raise ValueError("unknown previous publication state")
    if target not in {"dual", "npm"}:
        raise ValueError("unknown publication target")
    if pypi not in {"present", "absent", "unknown"} or npm not in {
        "present",
        "absent",
        "unknown",
    }:
        raise ValueError("unknown registry observation")
    if registry_verification not in {
        "not_run",
        "failed",
        "byte_verified",
        "npm_byte_verified",
    }:
        raise ValueError("unknown registry verification state")
    publish_results = {pypi_publish_result, npm_publish_result}
    if not publish_results.issubset(
        {"success", "failure", "cancelled", "skipped", "unknown"}
    ):
        raise ValueError("unknown publish job result")

    expected_verification = "npm_byte_verified" if target == "npm" else "byte_verified"
    if (
        registry_verification in {"byte_verified", "npm_byte_verified"}
        and registry_verification != expected_verification
    ):
        return _incident(_observed_state(pypi, npm), "verification_state_mismatch")
    if target == "npm" and pypi == "present":
        return _incident(_observed_state(pypi, npm), "publication_target_mismatch")
    if registry_verification == expected_verification:
        observations_match = (
            pypi == "absent" and npm == "present"
            if target == "npm"
            else pypi == "present" and npm == "present"
        )
        if not observations_match:
            return _incident(_observed_state(pypi, npm), "verification_state_mismatch")
    if "unknown" in {pypi, npm}:
        return _incident(previous_state, "registry_state_unknown")

    observed = _observed_state(pypi, npm)
    previous_registries = _PUBLISHED_BY_STATE[previous_state]
    observed_registries = _PUBLISHED_BY_STATE[observed]
    if not previous_registries.issubset(observed_registries):
        if (
            previous_registries
            and observed_registries
            and not observed_registries.issubset(previous_registries)
        ):
            return _incident(previous_state, "state_branch_mismatch")
        return _incident(previous_state, "state_regression")

    if target == "npm":
        npm_state = (
            "npm_byte_verified" if previous_state == "npm_byte_verified" else observed
        )
        if pypi_publish_result != "skipped":
            return _incident(npm_state, "publish_target_mismatch")
        if (
            npm_publish_result == "skipped"
            and npm == "absent"
            and registry_verification == "not_run"
        ):
            return PublicationDecision("unpublished", False, False)
        if npm_publish_result != "success":
            if npm_publish_result == "unknown":
                return _incident(npm_state, "publish_outcome_unknown")
            if npm_publish_result == "failure":
                return _incident(npm_state, "publish_attempt_failed")
            if npm_publish_result == "cancelled":
                return _incident(npm_state, "publish_attempt_cancelled")
            return _incident(npm_state, "publish_target_mismatch")
        if npm != "present":
            return _incident(npm_state, "publish_success_registry_absent")
        if registry_verification == "failed":
            return _incident(npm_state, "registry_verification_failed")
        if registry_verification != "npm_byte_verified":
            return _incident(npm_state, "verification_incomplete")
        return PublicationDecision("npm_byte_verified", True, True)

    if previous_state == "byte_verified":
        if registry_verification != "byte_verified":
            code = (
                "registry_verification_failed"
                if registry_verification == "failed"
                else "verification_incomplete"
            )
            return _incident(previous_state, code)
        return PublicationDecision("byte_verified", True, True)
    if observed in {"pypi_only", "npm_only"}:
        return _incident(observed, "partial_publication")
    if observed == "both_published":
        if registry_verification == "byte_verified":
            return PublicationDecision("byte_verified", True, True)
        if registry_verification == "failed":
            return _incident(observed, "registry_verification_failed")
        return _incident(observed, "verification_incomplete")
    if "unknown" in publish_results:
        return _incident(observed, "publish_outcome_unknown")
    if "success" in publish_results:
        return _incident(observed, "publish_success_registry_absent")
    if "failure" in publish_results:
        return _incident(observed, "publish_attempt_failed")
    if "cancelled" in publish_results:
        return _incident(observed, "publish_attempt_cancelled")
    if registry_verification == "failed":
        return _incident(observed, "registry_verification_failed")
    return PublicationDecision("unpublished", False, False)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _publisher_artifact(
    *,
    name: str,
    artifact_id: int,
    digest: str,
    workflow_run: str,
    workflow_run_attempt: int,
) -> dict[str, Any]:
    workflow_run_id = _github_run_id(workflow_run)
    if (
        workflow_run_id is None
        or name != f"kaji-publisher-identity-{workflow_run_id}-{workflow_run_attempt}"
        or not _positive_safe_integer(artifact_id)
        or ARTIFACT_DIGEST_PATTERN.fullmatch(digest) is None
    ):
        raise ValueError("publisher artifact identity is invalid")
    return {"name": name, "id": artifact_id, "digest": digest}


def publisher_identity_projection(
    *,
    receipt: Path | None,
    artifact_name: str | None,
    artifact_id: int | None,
    artifact_digest: str | None,
    no_receipt_reason: str | None,
    expected_commit: str,
    expected_tag: str,
    expected_workflow_run: str,
    expected_workflow_run_attempt: int,
    expected_workflow_path: str,
    expected_workflow_sha: str,
    expected_publisher: str | None,
) -> dict[str, Any]:
    receipt_arm = (
        receipt,
        artifact_name,
        artifact_id,
        artifact_digest,
    )
    if receipt is None:
        if any(value is not None for value in receipt_arm[1:]):
            raise ValueError("publisher receipt artifact inputs are incomplete")
        if no_receipt_reason not in NO_RECEIPT_REASONS:
            raise ValueError("publisher no-receipt reason is invalid")
        return {
            "conclusion": "not_run",
            "reason": no_receipt_reason,
            "artifact": None,
            "receiptSha256": None,
            "identity": None,
        }
    if (
        no_receipt_reason is not None
        or artifact_name is None
        or artifact_id is None
        or artifact_digest is None
    ):
        raise ValueError("publisher receipt inputs are ambiguous or incomplete")
    artifact = _publisher_artifact(
        name=artifact_name,
        artifact_id=artifact_id,
        digest=artifact_digest,
        workflow_run=expected_workflow_run,
        workflow_run_attempt=expected_workflow_run_attempt,
    )
    try:
        identity, receipt_sha256 = validate_publisher_identity_receipt(
            receipt,
            expected_commit=expected_commit,
            expected_tag=expected_tag,
            expected_workflow_run=expected_workflow_run,
            expected_workflow_run_attempt=expected_workflow_run_attempt,
            expected_workflow_path=expected_workflow_path,
            expected_workflow_sha=expected_workflow_sha,
            expected_publisher=expected_publisher,
        )
    except PublisherIdentityError as error:
        return {
            "conclusion": "failed",
            "reason": "receipt_invalid",
            "artifact": artifact,
            "receiptSha256": error.receipt_sha256,
            "identity": None,
        }
    if identity["conclusion"] == "failed":
        return {
            "conclusion": "failed",
            "reason": "identity_check_failed",
            "artifact": artifact,
            "receiptSha256": receipt_sha256,
            "identity": identity,
        }
    return {
        "conclusion": "passed",
        "reason": None,
        "artifact": artifact,
        "receiptSha256": receipt_sha256,
        "identity": identity,
    }


def _write_verification_failure(
    *,
    output: Path,
    manifest: dict[str, Any],
    attempt: int,
    attempt_limit: int,
    checks: dict[str, Any],
    error: BaseException,
    target: PublicationTarget,
) -> None:
    _write_json(
        output,
        {
            "schemaVersion": 1,
            "target": target,
            "status": "verification_failed",
            "manifestCommit": manifest.get("commit"),
            "packages": manifest.get("packages"),
            "attempt": attempt,
            "attemptLimit": attempt_limit,
            "failureCode": (
                "verification_mismatch"
                if isinstance(error, VerificationMismatch)
                else "verification_unavailable"
            ),
            "failureType": type(error).__name__,
            "checks": checks,
        },
    )


def _fail_invalid_input(
    output: Path,
    message: str,
    error: BaseException,
    *,
    target: PublicationTarget,
) -> NoReturn:
    _write_json(
        output,
        {
            "schemaVersion": 1,
            "target": target,
            "status": "verification_failed",
            "manifestCommit": None,
            "failureCode": "invalid_release_input",
            "failureType": type(error).__name__,
            "checks": {
                "pypi": {"status": "not_targeted" if target == "npm" else "not_run"},
                "npm": {"status": "not_run"},
            },
        },
    )
    fail(message)


def verification_main(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--downloads-dir", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--target", choices=("dual", "npm"), default="dual")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--initial-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.attempts < 1 or args.initial_delay < 0 or args.max_delay < 0:
        _fail_invalid_input(
            args.output,
            "polling bounds must be non-negative and attempts must be positive",
            ValueError("invalid polling bounds"),
            target=args.target,
        )
    if not args.repository or args.repository.count("/") != 1:
        _fail_invalid_input(
            args.output,
            "--repository must be an owner/name GitHub repository",
            ValueError("invalid repository"),
            target=args.target,
        )
    if (
        TAG_PATTERN.fullmatch(args.tag) is None
        or args.workflow_path != WORKFLOW_PATH
        or COMMIT_PATTERN.fullmatch(args.workflow_sha) is None
        or not _positive_safe_integer(args.workflow_run_id)
        or args.workflow_run_attempt != 1
    ):
        _fail_invalid_input(
            args.output,
            "publish tag, workflow identity, run ID, or run attempt is invalid",
            ValueError("invalid publish workflow identity"),
            target=args.target,
        )
    try:
        manifest, entries = manifest_data(args.artifacts_dir)
    except (
        OSError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        _fail_invalid_input(
            args.output,
            "release manifest could not be loaded",
            error,
            target=args.target,
        )
    if COMMIT_PATTERN.fullmatch(str(manifest.get("commit", ""))) is None:
        _fail_invalid_input(
            args.output,
            "manifest commit must be exactly 40 lowercase hexadecimal characters",
            ValueError("invalid manifest commit"),
            target=args.target,
        )
    if args.workflow_sha != manifest["commit"]:
        _fail_invalid_input(
            args.output,
            "publish workflow SHA must equal the release manifest commit",
            ValueError("publish workflow SHA mismatch"),
            target=args.target,
        )
    downloads_dir = args.downloads_dir or args.output.parent / "downloaded"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    retryable = (
        OSError,
        RuntimeError,
        CommandError,
        urllib.error.URLError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    )
    for attempt in range(1, args.attempts + 1):
        checks: dict[str, Any] = {
            "pypi": {"status": "not_targeted" if args.target == "npm" else "not_run"},
            "npm": {"status": "not_run"},
        }
        try:
            if args.target == "dual":
                pypi = verify_pypi(
                    entries,
                    downloads_dir=downloads_dir,
                    repository=args.repository,
                    commit=manifest["commit"],
                )
                checks["pypi"] = {"status": "passed", "evidence": pypi}
            else:
                pypi = {"status": "not_targeted"}
            npm = verify_npm(
                entries,
                downloads_dir=downloads_dir,
                repository=args.repository,
                commit=manifest["commit"],
                tag=args.tag,
                workflow_path=args.workflow_path,
                workflow_sha=args.workflow_sha,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
            )
            checks["npm"] = {"status": "passed", "evidence": npm}
        except VerificationMismatch as error:
            failed_check = "pypi" if checks["pypi"]["status"] == "not_run" else "npm"
            checks[failed_check] = {
                "status": "failed",
                "failureType": type(error).__name__,
            }
            _write_verification_failure(
                output=args.output,
                manifest=manifest,
                attempt=attempt,
                attempt_limit=args.attempts,
                checks=checks,
                error=error,
                target=args.target,
            )
            fail(f"immutable registry verification mismatch: {error}")
        except retryable as error:
            failed_check = "pypi" if checks["pypi"]["status"] == "not_run" else "npm"
            checks[failed_check] = {
                "status": "unavailable",
                "failureType": type(error).__name__,
            }
            _write_verification_failure(
                output=args.output,
                manifest=manifest,
                attempt=attempt,
                attempt_limit=args.attempts,
                checks=checks,
                error=error,
                target=args.target,
            )
            if attempt == args.attempts:
                fail(
                    f"registry verification did not converge after {args.attempts} attempts: "
                    f"{type(error).__name__}: {error}"
                )
            delay = min(args.initial_delay * (2 ** (attempt - 1)), args.max_delay)
            print(
                f"Registry evidence unavailable (attempt {attempt}/{args.attempts}); "
                f"retrying in {delay:g}s"
            )
            time.sleep(delay)
            continue

        _write_json(
            args.output,
            {
                "schemaVersion": 1,
                "target": args.target,
                "status": (
                    "npm_byte_verified" if args.target == "npm" else "byte_verified"
                ),
                "manifestCommit": manifest["commit"],
                "tag": args.tag,
                "workflowPath": args.workflow_path,
                "workflowSha": args.workflow_sha,
                "workflowRunId": args.workflow_run_id,
                "workflowRunAttempt": args.workflow_run_attempt,
                "packages": manifest["packages"],
                "verifiedAt": datetime.now(UTC).isoformat(),
                "attempt": attempt,
                "attemptLimit": args.attempts,
                "pypi": pypi,
                "npm": npm,
            },
        )
        if args.target == "npm":
            print(
                "PASS: npm downloaded bytes, registry signatures, and GitHub "
                "attestations verified"
            )
        else:
            print(
                "PASS: PyPI/npm downloaded bytes, registry attestations, and GitHub "
                "attestations verified"
            )
        return


def state_main(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("dual", "npm"), default="dual")
    parser.add_argument(
        "--previous-state", required=True, choices=tuple(_PUBLISHED_BY_STATE)
    )
    parser.add_argument(
        "--pypi", required=True, choices=("present", "absent", "unknown")
    )
    parser.add_argument(
        "--npm", required=True, choices=("present", "absent", "unknown")
    )
    parser.add_argument(
        "--registry-verification",
        required=True,
        choices=("not_run", "failed", "byte_verified", "npm_byte_verified"),
    )
    parser.add_argument(
        "--pypi-publish-result",
        required=True,
        choices=("success", "failure", "cancelled", "skipped", "unknown"),
    )
    parser.add_argument(
        "--npm-publish-result",
        required=True,
        choices=("success", "failure", "cancelled", "skipped", "unknown"),
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--expected-publisher")
    parser.add_argument("--publisher-receipt", type=Path)
    parser.add_argument("--publisher-artifact-name")
    parser.add_argument("--publisher-artifact-id", type=int)
    parser.add_argument("--publisher-artifact-digest")
    parser.add_argument(
        "--publisher-no-receipt-reason",
        choices=tuple(sorted(NO_RECEIPT_REASONS)),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    if COMMIT_PATTERN.fullmatch(args.commit) is None:
        parser.error("--commit must be exactly 40 lowercase hexadecimal characters")
    if TAG_PATTERN.fullmatch(args.tag) is None:
        parser.error("--tag must name the exact beta.11 release")
    if _github_run_id(args.workflow_run) is None:
        parser.error("--workflow-run must identify the exact enkyuan/alloy run")
    if args.workflow_run_attempt != 1:
        parser.error("--workflow-run-attempt must be exactly 1")
    if args.workflow_path != WORKFLOW_PATH:
        parser.error("--workflow-path must identify the protected publish workflow")
    if (
        COMMIT_PATTERN.fullmatch(args.workflow_sha) is None
        or args.workflow_sha != args.commit
    ):
        parser.error("--workflow-sha must equal the exact release commit")
    if args.expected_publisher is not None and not _valid_publisher(
        args.expected_publisher
    ):
        parser.error("--expected-publisher is not a valid npm identity")
    receipt_inputs = (
        args.publisher_receipt,
        args.publisher_artifact_name,
        args.publisher_artifact_id,
        args.publisher_artifact_digest,
    )
    has_receipt_input = any(value is not None for value in receipt_inputs)
    has_complete_receipt = all(value is not None for value in receipt_inputs)
    if has_receipt_input != has_complete_receipt:
        parser.error(
            "publisher receipt path and artifact name, ID, and digest are all required"
        )
    if has_complete_receipt == (args.publisher_no_receipt_reason is not None):
        parser.error(
            "select exactly one complete publisher receipt or no-receipt reason"
        )
    if (
        args.publisher_no_receipt_reason == "publish_job_not_started"
        and args.npm_publish_result != "skipped"
    ):
        parser.error("publish_job_not_started requires a skipped npm publish job")
    if (
        args.publisher_no_receipt_reason
        in NO_RECEIPT_REASONS - {"publish_job_not_started"}
        and args.npm_publish_result == "skipped"
    ):
        parser.error(
            "publisher receipt output, metadata, or download failures require "
            "a non-skipped npm publish job"
        )
    if has_complete_receipt and args.npm_publish_result == "skipped":
        parser.error("a skipped npm publish job cannot produce a publisher receipt")
    try:
        publisher_identity = publisher_identity_projection(
            receipt=args.publisher_receipt,
            artifact_name=args.publisher_artifact_name,
            artifact_id=args.publisher_artifact_id,
            artifact_digest=args.publisher_artifact_digest,
            no_receipt_reason=args.publisher_no_receipt_reason,
            expected_commit=args.commit,
            expected_tag=args.tag,
            expected_workflow_run=args.workflow_run,
            expected_workflow_run_attempt=args.workflow_run_attempt,
            expected_workflow_path=args.workflow_path,
            expected_workflow_sha=args.workflow_sha,
            expected_publisher=args.expected_publisher,
        )
    except ValueError as error:
        parser.error(str(error))
    decision = reduce_publication_state(
        previous_state=args.previous_state,
        pypi=args.pypi,
        npm=args.npm,
        registry_verification=args.registry_verification,
        pypi_publish_result=args.pypi_publish_result,
        npm_publish_result=args.npm_publish_result,
        target=args.target,
    )
    if (
        args.target == "npm"
        and decision.state == "npm_byte_verified"
        and (
            publisher_identity["conclusion"] != "passed"
            or publisher_identity["receiptSha256"] is None
        )
    ):
        decision = _incident("npm_only", "publisher_identity_not_verified")
    payload = {
        "schemaVersion": 1,
        "target": args.target,
        "commit": args.commit,
        "tag": args.tag,
        "state": decision.state,
        "previousState": args.previous_state,
        "releaseReady": decision.release_ready,
        "installRecommendation": decision.install_recommendation,
        "registries": {"pypi": args.pypi, "npm": args.npm},
        "publishJobs": {
            "pypi": args.pypi_publish_result,
            "npm": args.npm_publish_result,
        },
        "registryVerification": args.registry_verification,
        "incident": (
            None
            if decision.incident_code is None
            else {
                "code": decision.incident_code,
                "recovery": decision.recovery,
            }
        ),
        "workflowRun": args.workflow_run,
        "workflowRunAttempt": args.workflow_run_attempt,
        "workflowPath": args.workflow_path,
        "workflowSha": args.workflow_sha,
        "expectedPublisher": args.expected_publisher,
        "publisherIdentity": publisher_identity,
    }
    _write_json(args.output, payload)
    recommendation = (
        "Eligible only from this byte-verified release evidence."
        if decision.install_recommendation
        else "WITHHELD: do not publish installation recommendations."
    )
    incident = (
        "None."
        if decision.incident_code is None
        else (
            f"{decision.incident_code}; preserve all evidence, do not rerun or reuse "
            "versions, and fix forward with the next beta."
        )
    )
    publisher_message = (
        f"`{publisher_identity['conclusion']}`"
        if publisher_identity["reason"] is None
        else (
            f"`{publisher_identity['conclusion']}` (`{publisher_identity['reason']}`)"
        )
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        "# Kaji beta publication status\n\n"
        f"- Commit: `{args.commit}`\n"
        f"- Target: `{args.target}`\n"
        f"- State: **{decision.state}**\n"
        f"- PyPI/npm: `{args.pypi}` / `{args.npm}`\n"
        f"- Publish jobs: `{args.pypi_publish_result}` / "
        f"`{args.npm_publish_result}`\n"
        f"- Registry verification: `{args.registry_verification}`\n"
        f"- Publisher identity: {publisher_message}\n"
        f"- Retained evidence: {args.workflow_run}\n"
        f"- Installation recommendation: {recommendation}\n"
        f"- Incident: {incident}\n"
    )
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as stream:
            stream.write(f"publication-state={decision.state}\n")
            stream.write(
                f"release-ready={'true' if decision.release_ready else 'false'}\n"
            )
    print(f"PUBLICATION_STATE: {json.dumps(payload, sort_keys=True)}")


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "state":
        state_main(sys.argv[2:])
    else:
        verification_main(sys.argv[1:])


if __name__ == "__main__":
    main()
