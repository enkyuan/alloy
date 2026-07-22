#!/usr/bin/env python3
"""Validate exact-commit Kaji TTHW evidence without exposing user content."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import statistics
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "kaji" / "contracts" / "release" / "tthw-evidence-v1.schema.json"
EXPECTED_ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.2.tgz": ("typescript", "0.2.0-beta.2"),
}
PATH_ARTIFACTS = {
    "python": "kaji_sdk-0.2.0b1-py3-none-any.whl",
    "npm": "kaji-sdk-0.2.0-beta.2.tgz",
    "bun": "kaji-sdk-0.2.0-beta.2.tgz",
}
MAX_RELEASE_MANIFEST_BYTES = 1024 * 1024
STEP_ORDER = (
    "artifact-install",
    "scaffold-init",
    "no-key-run",
    "echo-setup",
    "echo-run",
)
SENSITIVE_TEXT = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{8,})",
    re.IGNORECASE,
)


class EvidenceError(RuntimeError):
    pass


def fail(location: str, message: str) -> NoReturn:
    raise EvidenceError(f"{location}: {message}")


def pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(encoded: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError):
        fail("/", f"invalid {label}")
    if not isinstance(document, dict):
        fail("/", f"{label} must be an object")
    return document


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
    except OSError:
        fail("/", f"invalid {label}")
    return _json_object(encoded, label)


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


def _release_manifest_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > MAX_RELEASE_MANIFEST_BYTES
            ):
                raise OSError
            encoded = stream.read(MAX_RELEASE_MANIFEST_BYTES + 1)
            after = os.fstat(stream.fileno())
        if len(encoded) > MAX_RELEASE_MANIFEST_BYTES or not _same_file(before, after):
            raise OSError
        return encoded
    except OSError:
        fail("/", "invalid release manifest")


def _artifact_identity(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OSError
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        if size != before.st_size or not _same_file(before, after):
            raise OSError
        return size, digest.hexdigest()
    except OSError:
        fail("/artifacts", "artifact file is missing or unsafe")


def release_identity(
    release_manifest: Path, artifacts_dir: Path
) -> tuple[str, str, list[dict[str, Any]]]:
    manifest_bytes = _release_manifest_bytes(release_manifest)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = _json_object(manifest_bytes, "release manifest")
    commit = manifest.get("commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        fail("/commit", "release manifest commit is invalid")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        fail("/artifacts", "release manifest artifact list is missing")
    manifest_by_name = {
        entry.get("file"): entry for entry in entries if isinstance(entry, dict)
    }
    if (
        len(entries) != len(EXPECTED_ARTIFACTS)
        or len(manifest_by_name) != len(entries)
        or set(manifest_by_name) != set(EXPECTED_ARTIFACTS)
    ):
        fail("/artifacts", "release manifest artifact names differ")

    rows: list[dict[str, Any]] = []
    for name in sorted(EXPECTED_ARTIFACTS):
        package, version = EXPECTED_ARTIFACTS[name]
        artifact = artifacts_dir / name
        size, artifact_hash = _artifact_identity(artifact)
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
    return commit, manifest_hash, rows


def validate_document(document: dict[str, Any]) -> dict[str, int]:
    schema = load_json(SCHEMA, "TTHW schema")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (list(error.absolute_path), list(error.absolute_schema_path)),
    )
    if errors:
        fail(pointer(errors[0].absolute_path), "schema validation failed")

    artifacts = document["artifacts"]
    by_name = {entry["name"]: entry for entry in artifacts}
    if set(by_name) != set(EXPECTED_ARTIFACTS):
        fail("/artifacts", "exact artifact names are required")
    for name, (package, version) in EXPECTED_ARTIFACTS.items():
        if (by_name[name]["package"], by_name[name]["version"]) != (
            package,
            version,
        ):
            fail("/artifacts", "artifact package/version binding differs")

    runs = document["humanRuns"]
    participant_ids = [run["participantId"] for run in runs]
    if len(participant_ids) != len(set(participant_ids)):
        fail("/humanRuns", "participant pseudonyms must be distinct")
    if any(run["os"] != "macos" or run["architecture"] != "arm64" for run in runs):
        fail("/humanRuns", "every beta TTHW run must use arm64 macOS")
    if {run["path"] for run in runs} != {"python", "npm", "bun"}:
        fail("/humanRuns", "Python, npm, and Bun coverage is required")

    artifacts_by_name = {entry["name"]: entry for entry in artifacts}
    no_key_totals: list[int] = []
    echo_totals: list[int] = []
    for index, run in enumerate(runs):
        if run["commit"] != document["commit"]:
            fail(f"/humanRuns/{index}/commit", "participant commit differs")
        if run["releaseManifestSha256"] != document["releaseManifestSha256"]:
            fail(
                f"/humanRuns/{index}/releaseManifestSha256",
                "participant release manifest differs",
            )
        expected_artifact = artifacts_by_name[PATH_ARTIFACTS[run["path"]]]
        for field in ("name", "package", "version", "sha256"):
            if run["artifact"][field] != expected_artifact[field]:
                fail(
                    f"/humanRuns/{index}/artifact/{field}",
                    "participant artifact binding differs",
                )
        names = tuple(step["name"] for step in run["steps"])
        if names != STEP_ORDER:
            fail(f"/humanRuns/{index}/steps", "step order differs")
        durations = [step["durationMs"] for step in run["steps"]]
        if run["noKeyTotalMs"] != sum(durations[:3]):
            fail(f"/humanRuns/{index}/noKeyTotalMs", "total differs from steps")
        if run["echoTotalMs"] != sum(durations):
            fail(f"/humanRuns/{index}/echoTotalMs", "total differs from steps")
        if run["followUpDate"] < run["reviewDate"]:
            fail(f"/humanRuns/{index}/followUpDate", "must not precede review date")
        for item in run["confusion"]:
            if SENSITIVE_TEXT.search(item["summary"]) or SENSITIVE_TEXT.search(
                item["remediation"]
            ):
                fail(f"/humanRuns/{index}/confusion", "sensitive text is not redacted")
        no_key_totals.append(run["noKeyTotalMs"])
        echo_totals.append(run["echoTotalMs"])

    computed = {
        "noKeyMedianMs": int(statistics.median(no_key_totals)),
        "noKeyMaxMs": max(no_key_totals),
        "echoMedianMs": int(statistics.median(echo_totals)),
        "echoMaxMs": max(echo_totals),
    }
    if document["summary"] != computed:
        fail("/summary", "summary differs from recomputed median/maximum")
    if computed["noKeyMedianMs"] >= 300_000:
        fail("/summary/noKeyMedianMs", "must be under 300000")
    if computed["noKeyMaxMs"] >= 600_000:
        fail("/summary/noKeyMaxMs", "every run must be under 600000")
    if computed["echoMedianMs"] >= 600_000:
        fail("/summary/echoMedianMs", "must be under 600000")
    if computed["echoMaxMs"] >= 1_200_000:
        fail("/summary/echoMaxMs", "every run must be under 1200000")
    return computed


def validate_bindings(
    document: dict[str, Any], release_manifest: Path, artifacts_dir: Path
) -> None:
    commit, manifest_hash, canonical_artifacts = release_identity(
        release_manifest, artifacts_dir
    )
    if manifest_hash != document["releaseManifestSha256"]:
        fail("/releaseManifestSha256", "release manifest hash differs")
    if commit != document["commit"]:
        fail("/commit", "release manifest commit differs")
    evidence_by_name = {entry["name"]: entry for entry in document["artifacts"]}
    canonical_by_name = {entry["name"]: entry for entry in canonical_artifacts}
    if set(evidence_by_name) != set(canonical_by_name):
        fail("/artifacts", "exact artifact names are required")
    for name, evidence in evidence_by_name.items():
        canonical = canonical_by_name[name]
        if any(evidence[field] != canonical[field] for field in ("size", "sha256")):
            fail("/artifacts", "retained artifact size/hash differs")
        if any(evidence[field] != canonical[field] for field in ("package", "version")):
            fail("/artifacts", "artifact package/version binding differs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        document = load_json(args.evidence, "TTHW evidence")
        summary = validate_document(document)
        validate_bindings(document, args.release_manifest, args.artifacts_dir)
    except EvidenceError as error:
        print(f"FAIL: {error}")
        return 1
    print(
        "PASS: exact-commit five-user TTHW evidence validated "
        f"no_key_median_ms={summary['noKeyMedianMs']} "
        f"no_key_max_ms={summary['noKeyMaxMs']} "
        f"echo_median_ms={summary['echoMedianMs']} "
        f"echo_max_ms={summary['echoMaxMs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
