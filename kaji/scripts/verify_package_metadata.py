#!/usr/bin/env python3
"""Verify beta package metadata and emit deterministic artifact checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tomllib
import zipfile
from pathlib import Path
from typing import NoReturn

from verify_npm_package import verify_npm_tarball
from process_runner import METADATA_BUDGET, CommandError, run_checked

PYTHON_PROJECT = "kaji-sdk"
PYTHON_DISTRIBUTION = "kaji_sdk"
PYTHON_VERSION = "0.2.0b1"
TYPESCRIPT_VERSION = "0.2.0-beta.2"
PYTHON_BUILD_REQUIREMENTS = {"setuptools==83.0.0", "editables==0.6"}
UV_VERSION = "0.11.25"
BUN_VERSION = "1.3.11"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_one(directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        fail(f"expected exactly one {label} under {directory}, found {len(matches)}")
    return matches[0]


def tool_version(command: str, *args: str) -> str:
    try:
        completed = run_checked(
            [command, *args],
            cwd=Path.cwd(),
            budget=METADATA_BUDGET,
            capture=True,
        )
    except (OSError, CommandError) as error:
        fail(f"could not query {command} version: {type(error).__name__}")
    output = (completed.stdout or completed.stderr).decode("utf-8").strip().splitlines()
    if not output:
        fail(f"{command} version command returned no output")
    match = re.search(r"\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?", output[0])
    if match is None:
        fail(f"could not parse {command} version output")
    return match.group(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifacts-dir", type=Path, default=Path(".artifacts/kaji-release")
    )
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--commit")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    sdk = repo / "kaji"
    ts = repo / "kaji/ts"
    artifacts = args.artifacts_dir
    if not artifacts.is_absolute():
        artifacts = repo / artifacts
    artifacts.mkdir(parents=True, exist_ok=True)

    python_metadata = tomllib.loads((sdk / "pyproject.toml").read_text())
    python_source = (sdk / "src/kaji/__init__.py").read_text()
    source_match = re.search(r'^__version__ = "([^"]+)"$', python_source, re.MULTILINE)
    typescript_metadata = json.loads((ts / "package.json").read_text())
    typescript_source = (ts / "src/index.ts").read_text()
    ts_match = re.search(r'export const VERSION = "([^"]+)"', typescript_source)

    python_version = python_metadata["project"]["version"]
    python_project = python_metadata["project"]["name"]
    typescript_version = typescript_metadata["version"]
    if source_match is None or source_match.group(1) != python_version:
        fail("Python source and project versions differ")
    if ts_match is None or ts_match.group(1) != typescript_version:
        fail("TypeScript source and package versions differ")
    if python_project != PYTHON_PROJECT:
        fail("Python project name is not the approved PyPI project")
    if python_version != PYTHON_VERSION or typescript_version != TYPESCRIPT_VERSION:
        fail("package versions are not the approved beta versions")
    if set(python_metadata["build-system"]["requires"]) != PYTHON_BUILD_REQUIREMENTS:
        fail("Python build requirements are not exactly pinned")
    build_requirements = (sdk / "build-requirements.txt").read_text()
    for requirement in PYTHON_BUILD_REQUIREMENTS:
        if requirement not in build_requirements:
            fail(f"hashed build audit requirements omit {requirement}")
    if build_requirements.count("--hash=sha256:") < 4:
        fail("build audit requirements do not pin wheel and sdist hashes")
    setup_action = (repo / ".github/actions/setup-python-uv/action.yml").read_text()
    if f'version: "{UV_VERSION}"' not in setup_action:
        fail("release uv version is not exactly pinned")

    contract_version = json.loads(
        (repo / "kaji/contracts/beta-core-v1.json").read_text()
    )["contractVersion"]
    if f"## [{python_version}]" not in (sdk / "CHANGELOG.md").read_text():
        fail("Python beta version is missing from its changelog")
    if (
        f"shared contract version `{contract_version}`"
        not in (sdk / "CHANGELOG.md").read_text()
    ):
        fail("Python changelog does not name the shared contract version")
    if f"## [{typescript_version}]" not in (ts / "CHANGELOG.md").read_text():
        fail("TypeScript beta version is missing from its changelog")
    if (
        f"shared contract version `{contract_version}`"
        not in (ts / "CHANGELOG.md").read_text()
    ):
        fail("TypeScript changelog does not name the shared contract version")

    root_license = (repo / "LICENSE").read_bytes()
    if (sdk / "LICENSE").read_bytes() != root_license:
        fail("Python package license differs from root LICENSE")
    if (ts / "LICENSE").read_bytes() != root_license:
        fail("TypeScript package license differs from root LICENSE")
    if python_metadata["project"].get("license") != "FSL-1.1-ALv2" or python_metadata[
        "project"
    ].get("license-files") != ["LICENSE"]:
        fail("Python metadata does not declare its SPDX license and packaged file")
    if typescript_metadata.get("license") != "FSL-1.1-ALv2":
        fail("TypeScript metadata does not declare its SPDX license")

    dev = set(python_metadata["dependency-groups"]["dev"])
    if not {"twine==6.2.0", "pip-audit==2.10.1"}.issubset(dev):
        fail("Python release audit tools are not exactly pinned")
    ts_dev = typescript_metadata.get("devDependencies", {})
    if (
        ts_dev.get("publint") != "0.3.21"
        or ts_dev.get("@arethetypeswrong/cli") != "0.18.4"
    ):
        fail("TypeScript release audit tools are not exactly pinned")
    if "zod" in typescript_metadata.get("dependencies", {}):
        fail("Zod must not be a bundled runtime dependency")
    if typescript_metadata.get("peerDependencies", {}).get("zod") != ">=4.3 <5":
        fail("Zod 4 peer ownership is not declared")

    uv_lock = (sdk / "uv.lock").read_text()
    if not re.search(
        rf'\[\[package\]\]\s+name = "{re.escape(PYTHON_PROJECT)}"\s+'
        rf'version = "{re.escape(python_version)}"',
        uv_lock,
    ):
        fail("Python lockfile does not contain the beta package version")
    for tool, version in (("pip-audit", "2.10.1"), ("twine", "6.2.0")):
        if not re.search(
            rf'\[\[package\]\]\s+name = "{tool}"\s+version = "{re.escape(version)}"',
            uv_lock,
        ):
            fail(f"Python lockfile does not pin {tool} {version}")
    bun_lock = (repo / "bun.lock").read_text()
    if f'"version": "{typescript_version}"' not in bun_lock:
        fail("Bun lockfile does not contain the beta package version")
    for tool, version in (("publint", "0.3.21"), ("@arethetypeswrong/cli", "0.18.4")):
        if f'"{tool}": "{version}"' not in bun_lock:
            fail(f"Bun lockfile does not pin {tool} {version}")

    commit = args.commit or os.environ.get("GITHUB_SHA")
    if args.release and commit is None:
        fail("release verification requires --commit or GITHUB_SHA")
    if commit is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        fail("release commit must be exactly 40 hexadecimal characters")
    commit = commit.lower() if commit is not None else "uncommitted-local-verification"

    actual_tools = {
        "bun": tool_version("bun", "--version"),
        "node": tool_version("node", "--version"),
        "npm": tool_version("npm", "--version"),
        "uv": tool_version("uv", "--version"),
    }
    if args.release and actual_tools["uv"] != UV_VERSION:
        fail(f"release requires uv {UV_VERSION}, found {actual_tools['uv']}")
    if args.release and actual_tools["bun"] != BUN_VERSION:
        fail(f"release requires Bun {BUN_VERSION}, found {actual_tools['bun']}")

    wheel = find_one(
        sdk / "dist", f"{PYTHON_DISTRIBUTION}-{python_version}-*.whl", "Python wheel"
    )
    sdist = find_one(
        sdk / "dist", f"{PYTHON_DISTRIBUTION}-{python_version}.tar.gz", "Python sdist"
    )
    tarballs = sorted(artifacts.glob("kaji-sdk-*.tgz"))
    if not tarballs:
        tarballs = sorted(ts.glob("kaji-sdk-*.tgz"))
    if len(tarballs) != 1:
        fail(f"expected exactly one TypeScript tarball, found {len(tarballs)}")
    npm_tarball = tarballs[0]
    verify_npm_tarball(npm_tarball, repo)

    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if (
            len(metadata_names) != 1
            or f"Name: {PYTHON_PROJECT}\n"
            not in archive.read(metadata_names[0]).decode()
            or f"Version: {python_version}\n"
            not in archive.read(metadata_names[0]).decode()
        ):
            fail("wheel project name or version is incorrect")
    with tarfile.open(sdist, "r:gz") as archive:
        pkg_info = [
            member
            for member in archive.getmembers()
            if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
        ]
        if len(pkg_info) != 1:
            fail("sdist has no unique PKG-INFO")
        stream = archive.extractfile(pkg_info[0])
        if stream is None:
            fail("sdist PKG-INFO is missing")
        pkg_info_text = stream.read().decode()
        if (
            f"Name: {PYTHON_PROJECT}\n" not in pkg_info_text
            or f"Version: {python_version}\n" not in pkg_info_text
        ):
            fail("sdist project name or version is incorrect")
    copied: list[Path] = []
    for source in (wheel, sdist, npm_tarball):
        target = artifacts / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        copied.append(target)

    entries = []
    for path in sorted(copied, key=lambda item: item.name):
        package = "typescript" if path.suffix == ".tgz" else "python"
        version = typescript_version if package == "typescript" else python_version
        entries.append(
            {
                "commit": commit,
                "contractVersion": contract_version,
                "file": path.name,
                "package": package,
                "sha256": sha256(path),
                "size": path.stat().st_size,
                "version": version,
            }
        )
    build_audit = sdk / "build-requirements.txt"
    manifest = {
        "schemaVersion": 1,
        "commit": commit,
        "buildTools": {
            "bun": actual_tools["bun"],
            "editables": "0.6",
            "node": actual_tools["node"],
            "npm": actual_tools["npm"],
            "setuptools": "83.0.0",
            "uv": actual_tools["uv"],
        },
        "buildAudit": {
            "file": "kaji/build-requirements.txt",
            "sha256": sha256(build_audit),
        },
        "packages": {
            "contract": contract_version,
            "python": python_version,
            "typescript": typescript_version,
        },
        "artifacts": entries,
    }
    (artifacts / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (artifacts / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in entries)
    )
    mode = "release" if args.release else "verification"
    print(f"PASS: package metadata and {mode} artifacts verified in {artifacts}")


if __name__ == "__main__":
    main()
