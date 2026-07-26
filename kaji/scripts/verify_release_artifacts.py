#!/usr/bin/env python3
"""Fail closed when downloaded Kaji beta artifacts differ from their manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, NoReturn


EXPECTED_ARTIFACTS = {
    "kaji_sdk-0.2.0b1-py3-none-any.whl": ("python", "0.2.0b1"),
    "kaji_sdk-0.2.0b1.tar.gz": ("python", "0.2.0b1"),
    "kaji-sdk-0.2.0-beta.3.tgz": ("typescript", "0.2.0-beta.3"),
}
EXPECTED_PACKAGES = {
    "contract": "1.0.0",
    "python": "0.2.0b1",
    "typescript": "0.2.0-beta.3",
}
EXPECTED_BUILD_TOOL_KEYS = {"bun", "editables", "node", "npm", "setuptools", "uv"}
EXPECTED_FIXED_BUILD_TOOLS = {
    "bun": "1.3.11",
    "editables": "0.6",
    "setuptools": "83.0.0",
    "uv": "0.11.25",
}
EXPECTED_BUILD_AUDIT = "kaji/build-requirements.txt"
ENTRY_KEYS = {
    "commit",
    "contractVersion",
    "file",
    "package",
    "sha256",
    "size",
    "version",
}


@dataclass(frozen=True)
class VerifiedReleaseArtifacts:
    root: Path
    commit: str
    manifest_sha256: str
    python_wheel: Path
    python_sdist: Path
    npm_tarball: Path
    artifact_sha256: Mapping[str, str]


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(artifacts: Path, expected_commit: str) -> VerifiedReleaseArtifacts:
    commit = expected_commit.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail("expected commit must be exactly 40 hexadecimal characters")
    if not artifacts.is_dir():
        fail(f"artifact directory does not exist: {artifacts}")

    required = set(EXPECTED_ARTIFACTS) | {"manifest.json", "SHA256SUMS"}
    children = list(artifacts.iterdir())
    actual = {path.name for path in children}
    if actual != required:
        fail(
            f"artifact file set mismatch: expected {sorted(required)}, got {sorted(actual)}"
        )
    if any(not path.is_file() or path.is_symlink() for path in children):
        fail("artifact directory contains a non-regular file or symlink")

    try:
        manifest = json.loads((artifacts / "manifest.json").read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"invalid manifest: {type(error).__name__}")
    if manifest.get("schemaVersion") != 1 or manifest.get("commit") != commit:
        fail("manifest schema or commit mismatch")
    if manifest.get("packages") != EXPECTED_PACKAGES:
        fail("manifest package versions mismatch")

    build_tools = manifest.get("buildTools")
    if (
        not isinstance(build_tools, dict)
        or set(build_tools) != EXPECTED_BUILD_TOOL_KEYS
    ):
        fail("manifest build tool set mismatch")
    for tool, version in EXPECTED_FIXED_BUILD_TOOLS.items():
        if build_tools.get(tool) != version:
            fail(f"manifest build tool mismatch for {tool}")
    for tool in ("node", "npm"):
        if not isinstance(build_tools.get(tool), str) or not re.fullmatch(
            r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", build_tools[tool]
        ):
            fail(f"manifest has an invalid {tool} version")

    build_audit = manifest.get("buildAudit")
    if not isinstance(build_audit, dict) or set(build_audit) != {"file", "sha256"}:
        fail("manifest build audit binding is malformed")
    if build_audit["file"] != EXPECTED_BUILD_AUDIT:
        fail("manifest build audit names an unexpected file")
    audit_path = Path(__file__).resolve().parents[2] / EXPECTED_BUILD_AUDIT
    if not audit_path.is_file() or audit_path.is_symlink():
        fail("manifest build audit file is missing or unsafe")
    if build_audit["sha256"] != sha256(audit_path):
        fail("manifest build audit hash mismatch")

    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or len(entries) != len(EXPECTED_ARTIFACTS):
        fail("manifest artifact count mismatch")
    if any(
        not isinstance(entry, dict) or set(entry) != ENTRY_KEYS for entry in entries
    ):
        fail("manifest artifact entry shape mismatch")
    if {entry["file"] for entry in entries} != set(EXPECTED_ARTIFACTS):
        fail("manifest artifact names mismatch")

    manifest_hashes: dict[str, str] = {}
    for entry in entries:
        name = entry["file"]
        path = artifacts / name
        digest = sha256(path)
        package, version = EXPECTED_ARTIFACTS[name]
        if (entry["package"], entry["version"]) != (package, version):
            fail(f"package metadata mismatch for {name}")
        if entry["commit"] != commit or entry["contractVersion"] != "1.0.0":
            fail(f"provenance mismatch for {name}")
        if entry["size"] != path.stat().st_size or entry["sha256"] != digest:
            fail(f"size/hash mismatch for {name}")
        manifest_hashes[name] = digest

    checksum_hashes: dict[str, str] = {}
    for line in (artifacts / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/]+)", line)
        if match is None or match.group(2) in checksum_hashes:
            fail("malformed or duplicate checksum entry")
        checksum_hashes[match.group(2)] = match.group(1)
    if checksum_hashes != manifest_hashes:
        fail("SHA256SUMS does not exactly match manifest")

    root = artifacts.resolve()
    return VerifiedReleaseArtifacts(
        root=root,
        commit=commit,
        manifest_sha256=sha256(artifacts / "manifest.json"),
        python_wheel=(root / "kaji_sdk-0.2.0b1-py3-none-any.whl"),
        python_sdist=(root / "kaji_sdk-0.2.0b1.tar.gz"),
        npm_tarball=(root / "kaji-sdk-0.2.0-beta.3.tgz"),
        artifact_sha256=MappingProxyType(dict(sorted(manifest_hashes.items()))),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", default=os.environ.get("EXPECTED_COMMIT"))
    args = parser.parse_args()
    if args.expected_commit is None:
        fail("--expected-commit or EXPECTED_COMMIT is required")
    verify(args.artifacts_dir, args.expected_commit)
    print("PASS: release filenames, build tools, sizes, hashes, and commit verified")


if __name__ == "__main__":
    main()
