#!/usr/bin/env python3
"""Verify published beta bytes and reduce the monotonic publication state."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, NoReturn, Sequence

from process_runner import METADATA_BUDGET, CommandError, run_checked


PYPI_PROJECT = "kaji-sdk"
PYPI_VERSION = "0.2.0b1"
PYPI_URL = f"https://pypi.org/pypi/{PYPI_PROJECT}/{PYPI_VERSION}/json"
NPM_PACKAGE = "@kaji/sdk"
NPM_VERSION = "0.2.0-beta.2"
NPM_SPEC = f"{NPM_PACKAGE}@{NPM_VERSION}"
NPM_REGISTRY = "https://registry.npmjs.org/"
USER_AGENT = "kaji-beta-release-verifier/1"
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")

PublicationState = Literal[
    "unpublished", "pypi_only", "npm_only", "both_published", "byte_verified"
]
RegistryObservation = Literal["present", "absent", "unknown"]
RegistryVerification = Literal["not_run", "failed", "byte_verified"]
PublishResult = Literal["success", "failure", "cancelled", "skipped", "unknown"]

_PUBLISHED_BY_STATE: dict[PublicationState, frozenset[str]] = {
    "unpublished": frozenset(),
    "pypi_only": frozenset({"pypi"}),
    "npm_only": frozenset({"npm"}),
    "both_published": frozenset({"pypi", "npm"}),
    "byte_verified": frozenset({"pypi", "npm"}),
}


class VerificationMismatch(RuntimeError):
    """Published immutable metadata, bytes, or attestations do not match."""


class VerificationUnavailable(RuntimeError):
    """Expected registry metadata or attestations have not propagated yet."""


class _SameHostHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host: str) -> None:
        super().__init__()
        self.allowed_host = allowed_host

    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Any:
        target = urllib.parse.urlparse(urllib.parse.urljoin(request.full_url, new_url))
        if target.scheme != "https" or target.hostname != self.allowed_host:
            raise VerificationMismatch(
                "registry download redirect attempted to leave the expected host"
            )
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    state: PublicationState
    release_ready: bool
    install_recommendation: bool
    incident_code: str | None = None
    recovery: str | None = None


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def fetch(
    url: str, *, allowed_host: str | None = None, max_bytes: int = 2 * 1024 * 1024
) -> bytes:
    initial = urllib.parse.urlparse(url)
    if allowed_host is not None and (
        initial.scheme != "https" or initial.hostname != allowed_host
    ):
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
        final = urllib.parse.urlparse(response.geturl())
        if allowed_host is not None and (
            final.scheme != "https" or final.hostname != allowed_host
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
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            raise VerificationMismatch("PyPI returned malformed file metadata")
        name = item["filename"]
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
    tokens = integrity.split()
    if not tokens:
        raise VerificationMismatch("npm returned an empty integrity value")
    token = tokens[0]
    algorithm, separator, encoded = token.partition("-")
    if not separator or algorithm not in hashlib.algorithms_available:
        raise VerificationMismatch("npm returned an unsupported integrity value")
    try:
        return algorithm, base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise VerificationMismatch(
            "npm returned malformed integrity metadata"
        ) from error


def _is_expected_npm_entry(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("name") == NPM_PACKAGE
        and value.get("version") == NPM_VERSION
    )


def _has_attestation_bundle(value: Any) -> bool:
    return isinstance(value, dict) and any(
        value.get(key)
        for key in {"attestation", "attestations", "attestationBundle", "bundle"}
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


def _verify_npm_audit(*, repository_dir: Path, evidence_file: Path) -> dict[str, Any]:
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
        f"registry={NPM_REGISTRY}\n@kaji:registry={NPM_REGISTRY}\nignore-scripts=true\n"
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
    audit = json.loads(output)
    verified = audit.get("verified") if isinstance(audit, dict) else None
    invalid = audit.get("invalid") if isinstance(audit, dict) else None
    if invalid:
        raise VerificationMismatch("npm signature audit reported invalid signatures")
    missing = audit.get("missing") if isinstance(audit, dict) else None
    if missing:
        raise VerificationUnavailable(
            "npm signature audit has not propagated attestations"
        )
    if not isinstance(verified, list):
        raise VerificationMismatch("npm signature audit returned malformed evidence")
    if not verified:
        raise VerificationUnavailable("npm signature audit has not propagated packages")
    package_entries = [entry for entry in verified if _is_expected_npm_entry(entry)]
    if not package_entries:
        raise VerificationUnavailable(
            "npm signature audit has not propagated the beta package"
        )
    if len(package_entries) != 1:
        raise VerificationMismatch(
            "npm signature audit returned duplicate beta entries"
        )
    package_entry = next(
        (entry for entry in package_entries if _has_attestation_bundle(entry)),
        None,
    )
    if package_entry is None:
        raise VerificationUnavailable(
            "npm signature audit has not propagated the beta attestation bundle"
        )
    return {
        "verifiedEntries": len(verified),
        "packageVerified": True,
        "attestationsIncluded": True,
        "evidenceFile": evidence_file.name,
        "outputSha256": hashlib.sha256(output).hexdigest(),
    }


def verify_npm(
    entries: dict[str, dict[str, Any]],
    *,
    downloads_dir: Path,
    repository: str,
    commit: str,
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
    dist = json.loads(completed.stdout.decode("utf-8"))
    if not isinstance(dist, dict):
        raise VerificationMismatch("npm returned malformed dist metadata")
    tarball_url = dist.get("tarball")
    integrity = dist.get("integrity")
    if not isinstance(tarball_url, str) or not isinstance(integrity, str):
        raise VerificationUnavailable("npm dist metadata has not propagated completely")
    parsed = urllib.parse.urlparse(tarball_url)
    if parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org":
        raise VerificationMismatch("npm tarball URL is outside the expected registry")
    entry = entries.get("kaji-sdk-0.2.0-beta.2.tgz")
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
    shasum = dist.get("shasum")
    if isinstance(shasum, str) and hashlib.sha1(payload).hexdigest() != shasum:  # noqa: S324
        raise VerificationMismatch("downloaded npm tarball fails registry shasum")

    downloaded = downloads_dir / f"registry-{entry['file']}"
    downloaded.write_bytes(payload)
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
        downloads_dir / f"registry-{entry['file']}.github-attestation.json"
    )
    github_attestation_file.write_bytes(github_attestation_output)
    npm_audit_file = downloads_dir / "npm-signature-audit.json"
    with tempfile.TemporaryDirectory(prefix="kaji-npm-signatures-") as temporary:
        signature_audit = _verify_npm_audit(
            repository_dir=Path(temporary), evidence_file=npm_audit_file
        )
    return {
        "filename": entry["file"],
        "downloadedFile": downloaded.name,
        "integrity": integrity,
        "tarball": tarball_url,
        "sha256": entry["sha256"],
        "size": entry["size"],
        "byteVerified": True,
        "githubAttestationVerified": True,
        "githubAttestationFile": github_attestation_file.name,
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
) -> PublicationDecision:
    if previous_state not in _PUBLISHED_BY_STATE:
        raise ValueError("unknown previous publication state")
    if pypi not in {"present", "absent", "unknown"} or npm not in {
        "present",
        "absent",
        "unknown",
    }:
        raise ValueError("unknown registry observation")
    if registry_verification not in {"not_run", "failed", "byte_verified"}:
        raise ValueError("unknown registry verification state")
    publish_results = {pypi_publish_result, npm_publish_result}
    if not publish_results.issubset(
        {"success", "failure", "cancelled", "skipped", "unknown"}
    ):
        raise ValueError("unknown publish job result")
    if registry_verification == "byte_verified" and (
        pypi != "present" or npm != "present"
    ):
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


def _write_verification_failure(
    *,
    output: Path,
    manifest: dict[str, Any],
    attempt: int,
    attempt_limit: int,
    checks: dict[str, Any],
    error: BaseException,
) -> None:
    _write_json(
        output,
        {
            "schemaVersion": 1,
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


def _fail_invalid_input(output: Path, message: str, error: BaseException) -> NoReturn:
    _write_json(
        output,
        {
            "schemaVersion": 1,
            "status": "verification_failed",
            "manifestCommit": None,
            "failureCode": "invalid_release_input",
            "failureType": type(error).__name__,
            "checks": {
                "pypi": {"status": "not_run"},
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
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--initial-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.attempts < 1 or args.initial_delay < 0 or args.max_delay < 0:
        _fail_invalid_input(
            args.output,
            "polling bounds must be non-negative and attempts must be positive",
            ValueError("invalid polling bounds"),
        )
    if not args.repository or args.repository.count("/") != 1:
        _fail_invalid_input(
            args.output,
            "--repository must be an owner/name GitHub repository",
            ValueError("invalid repository"),
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
        _fail_invalid_input(args.output, "release manifest could not be loaded", error)
    if COMMIT_PATTERN.fullmatch(str(manifest.get("commit", ""))) is None:
        _fail_invalid_input(
            args.output,
            "manifest commit must be exactly 40 lowercase hexadecimal characters",
            ValueError("invalid manifest commit"),
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
            "pypi": {"status": "not_run"},
            "npm": {"status": "not_run"},
        }
        try:
            pypi = verify_pypi(
                entries,
                downloads_dir=downloads_dir,
                repository=args.repository,
                commit=manifest["commit"],
            )
            checks["pypi"] = {"status": "passed", "evidence": pypi}
            npm = verify_npm(
                entries,
                downloads_dir=downloads_dir,
                repository=args.repository,
                commit=manifest["commit"],
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
                "status": "byte_verified",
                "manifestCommit": manifest["commit"],
                "packages": manifest["packages"],
                "verifiedAt": datetime.now(UTC).isoformat(),
                "attempt": attempt,
                "attemptLimit": args.attempts,
                "pypi": pypi,
                "npm": npm,
            },
        )
        print(
            "PASS: PyPI/npm downloaded bytes, registry attestations, and GitHub "
            "attestations verified"
        )
        return


def state_main(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser()
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
        choices=("not_run", "failed", "byte_verified"),
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
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    if COMMIT_PATTERN.fullmatch(args.commit) is None:
        fail("--commit must be exactly 40 lowercase hexadecimal characters")
    decision = reduce_publication_state(
        previous_state=args.previous_state,
        pypi=args.pypi,
        npm=args.npm,
        registry_verification=args.registry_verification,
        pypi_publish_result=args.pypi_publish_result,
        npm_publish_result=args.npm_publish_result,
    )
    payload = {
        "schemaVersion": 1,
        "commit": args.commit,
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
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        "# Kaji beta publication status\n\n"
        f"- Commit: `{args.commit}`\n"
        f"- State: **{decision.state}**\n"
        f"- PyPI/npm: `{args.pypi}` / `{args.npm}`\n"
        f"- Publish jobs: `{args.pypi_publish_result}` / "
        f"`{args.npm_publish_result}`\n"
        f"- Registry verification: `{args.registry_verification}`\n"
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
