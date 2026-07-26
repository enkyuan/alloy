#!/usr/bin/env python3
"""Verify the exact npm tarball intended for release against the tagged checkout."""

from __future__ import annotations

import argparse
import json
import posixpath
import tarfile
from pathlib import Path, PurePosixPath
from typing import NoReturn

MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def checked_path(raw_name: str) -> str:
    if not raw_name or raw_name.startswith("/") or "\\" in raw_name:
        fail(f"npm tarball contains unsafe path: {raw_name!r}")
    name = raw_name.rstrip("/")
    parts = name.split("/")
    if not name or any(part in {"", ".", ".."} for part in parts):
        fail(f"npm tarball contains unsafe path: {raw_name!r}")
    if posixpath.normpath(name) != name:
        fail(f"npm tarball contains non-canonical path: {raw_name!r}")
    return name


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != ".DS_Store"
        and not any(
            part in {"__pycache__", ".cache", ".turbo", "logs"} for part in path.parts
        )
        and path.suffix not in {".pyc", ".pyo", ".log"}
    }


def export_targets(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        targets: list[str] = []
        for child in value.values():
            targets.extend(export_targets(child))
        return targets
    return []


def registry_path(base: str, relative: str) -> str:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        fail(f"npm registry manifest declares unsafe path: {relative!r}")
    joined = posixpath.normpath(posixpath.join(base, relative))
    if not joined.startswith("registry/"):
        fail(f"npm registry path escapes registry root: {relative!r}")
    return joined


def expected_package_bytes(ts_root: Path) -> tuple[dict[str, object], dict[str, bytes]]:
    package_payload = (ts_root / "package.json").read_bytes()
    package = json.loads(package_payload)
    if not isinstance(package, dict):
        fail("npm package metadata must be an object")

    expected = {
        "LICENSE": (ts_root / "LICENSE").read_bytes(),
        "README.md": (ts_root / "README.md").read_bytes(),
        "package.json": package_payload,
    }
    files = package.get("files")
    if not isinstance(files, list) or not files:
        fail("npm package files allowlist is missing")
    for raw_path in files:
        if not isinstance(raw_path, str):
            fail("npm package files allowlist contains a non-string entry")
        relative = checked_path(f"package/{raw_path}").removeprefix("package/")
        source = ts_root / relative
        if source.is_file():
            expected[relative] = source.read_bytes()
        elif source.is_dir():
            expected.update(
                {
                    f"{relative}/{child}": payload
                    for child, payload in tree_bytes(source).items()
                }
            )
        else:
            fail(f"npm package files allowlist entry does not exist: {raw_path}")
    return package, expected


def verify_npm_tarball(tarball: Path, repo: Path) -> None:
    ts_root = repo / "kaji/ts"
    canonical_contracts_root = repo / "kaji/contracts"
    if not tarball.is_file():
        fail(f"npm tarball does not exist: {tarball}")
    if not (ts_root / "dist").is_dir():
        fail("TypeScript dist/ must be built before npm artifact verification")

    package, expected = expected_package_bytes(ts_root)

    members: dict[str, tarfile.TarInfo] = {}
    total_size = 0
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive:
            if len(members) >= MAX_ARCHIVE_MEMBERS:
                fail("npm tarball contains too many members")
            name = checked_path(member.name)
            if name in members:
                fail(f"npm tarball contains duplicate path: {name}")
            if member.issym() or member.islnk():
                fail(f"npm tarball contains link member: {name}")
            if not (member.isfile() or member.isdir()):
                fail(f"npm tarball contains non-file member: {name}")
            if member.size > MAX_ARCHIVE_MEMBER_BYTES:
                fail(f"npm tarball member exceeds size limit: {name}")
            total_size += member.size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                fail("npm tarball exceeds total uncompressed size limit")
            if member.isfile() and member.mode & 0o111:
                relative = name.removeprefix("package/")
                if not (relative.startswith("dist/cli/") and relative.endswith(".js")):
                    fail(f"npm tarball contains unexpected executable: {name}")
            members[name] = member

        file_names = {name for name, member in members.items() if member.isfile()}
        expected_names = {f"package/{relative}" for relative in expected}
        if file_names != expected_names:
            fail(
                "npm tarball member set differs from checkout; "
                f"missing={sorted(expected_names - file_names)[:10]}, "
                f"extra={sorted(file_names - expected_names)[:10]}"
            )
        expected_dirs = {"package"}
        for name in expected_names:
            parent = posixpath.dirname(name)
            while parent:
                expected_dirs.add(parent)
                parent = posixpath.dirname(parent)
        actual_dirs = {name for name, member in members.items() if member.isdir()}
        if actual_dirs - expected_dirs:
            fail(
                f"npm tarball contains unexpected directories: {sorted(actual_dirs - expected_dirs)[:10]}"
            )

        for relative, expected_payload in expected.items():
            name = f"package/{relative}"
            member = members[name]
            if member.size != len(expected_payload):
                fail(f"npm tarball file size differs from checkout: {relative}")
            stream = archive.extractfile(member)
            if stream is None or stream.read() != expected_payload:
                fail(f"npm tarball file differs from checkout: {relative}")

    if package.get("name") != "kaji-sdk" or package.get("version") != "0.2.0-beta.3":
        fail("npm package name/version are not the approved beta coordinates")
    if package.get("license") != "FSL-1.1-ALv2":
        fail("npm package license metadata is not canonical")
    for target in export_targets(package.get("exports")) + list(
        (package.get("bin") or {}).values()
    ):
        relative = target.removeprefix("./")
        if not relative.startswith("dist/") or relative not in expected:
            fail(f"npm package target is missing or outside dist/: {target}")

    canonical_contracts = {
        relative: payload
        for relative, payload in tree_bytes(canonical_contracts_root).items()
        if Path(relative).suffix in {".json", ".md"}
    }
    packaged_contracts = {
        relative.removeprefix("contracts/"): payload
        for relative, payload in expected.items()
        if relative.startswith("contracts/")
        and Path(relative).suffix in {".json", ".md"}
    }
    if packaged_contracts != canonical_contracts:
        fail("npm packaged contracts differ from canonical shared contracts")

    registry_index = json.loads(expected.get("registry/index.json", b"{}"))
    integrations = registry_index.get("integrations") or {}
    if not integrations:
        fail("npm registry index declares no integrations")
    for name, entry in integrations.items():
        manifest_relative = entry.get("manifest") if isinstance(entry, dict) else entry
        if not isinstance(manifest_relative, str) or not manifest_relative:
            fail(f"{name}: npm registry entry has no manifest")
        manifest_path = registry_path("registry", manifest_relative)
        if manifest_path not in expected:
            fail(f"{name}: npm registry manifest is missing: {manifest_path}")
        manifest = json.loads(expected[manifest_path])
        for relative in manifest.get("files") or []:
            file_path = registry_path(posixpath.dirname(manifest_path), relative)
            if file_path not in expected:
                fail(f"{name}: npm registry file is missing: {file_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tarball", type=Path)
    parser.add_argument("--repo", type=Path)
    args = parser.parse_args()
    repo = args.repo or Path(__file__).resolve().parents[2]
    verify_npm_tarball(args.tarball.resolve(), repo.resolve())
    print(f"PASS: verified exact npm artifact {args.tarball.name}")


if __name__ == "__main__":
    main()
