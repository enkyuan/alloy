#!/usr/bin/env python3
"""Synchronize canonical integration schemas into both SDK registries."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts" / "integrations"
COPIES = {
    CONTRACTS / "manifest.schema.json": (
        ROOT
        / "kaji"
        / "packages"
        / "python"
        / "src"
        / "kaji"
        / "integrations"
        / "registry"
        / "schema.json",
        ROOT / "kaji" / "packages" / "typescript" / "registry" / "schema.json",
    ),
    CONTRACTS / "index.schema.json": (
        ROOT
        / "kaji"
        / "packages"
        / "python"
        / "src"
        / "kaji"
        / "integrations"
        / "registry"
        / "index.schema.json",
        ROOT / "kaji" / "packages" / "typescript" / "registry" / "index.schema.json",
    ),
    ROOT / "LICENSE": (
        ROOT
        / "kaji"
        / "packages"
        / "python"
        / "src"
        / "kaji"
        / "integrations"
        / "registry"
        / "github"
        / "LICENSE",
        ROOT / "kaji" / "packages" / "typescript" / "registry" / "github" / "LICENSE",
    ),
    ROOT
    / "kaji"
    / "packages"
    / "typescript"
    / "registry"
    / "github"
    / "owner-fixtures.json": (
        ROOT
        / "kaji"
        / "packages"
        / "python"
        / "src"
        / "kaji"
        / "integrations"
        / "registry"
        / "github"
        / "owner-fixtures.json",
    ),
}
ABI_INDEX = CONTRACTS / "abi-index-v1.json"
PYTHON_REGISTRY = (
    ROOT / "kaji" / "packages" / "python" / "src" / "kaji" / "integrations" / "registry"
)
TYPESCRIPT_REGISTRY = ROOT / "kaji" / "packages" / "typescript" / "registry"
_INTEGRATION_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


def _abi_contracts() -> dict[str, Path]:
    document = json.loads(ABI_INDEX.read_text())
    if set(document) != {"schemaVersion", "integrations"}:
        raise ValueError("ABI index must be a closed object")
    if document["schemaVersion"] != "1.0.0":
        raise ValueError("ABI index schemaVersion must be 1.0.0")
    integrations = document["integrations"]
    if not isinstance(integrations, dict) or not integrations:
        raise ValueError("ABI index integrations must be a non-empty object")
    contracts: dict[str, Path] = {}
    root = CONTRACTS.resolve()
    for name, relative in sorted(integrations.items()):
        if not isinstance(name, str) or _INTEGRATION_NAME.fullmatch(name) is None:
            raise ValueError("ABI index contains an invalid integration name")
        if not isinstance(relative, str):
            raise ValueError("ABI index path must be a string")
        path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or path.is_absolute()
            or re.match(r"^[A-Za-z]:", relative) is not None
            or any(part in {"", ".", ".."} for part in relative.split("/"))
        ):
            raise ValueError("ABI index path must be safe and relative")
        candidate = (CONTRACTS / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError("ABI index path escapes the contract root") from None
        if not candidate.is_file():
            raise ValueError("ABI index references a missing contract")
        contracts[name] = candidate
    return contracts


def _expected_manifest(path: Path, abi_path: Path) -> str:
    abi = json.loads(abi_path.read_text())
    document = json.loads(path.read_text())
    document["namespace"] = abi["namespace"]
    document["tools"] = abi["tools"]
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _manifests(name: str) -> tuple[Path, Path]:
    return (
        PYTHON_REGISTRY / name / "manifest.json",
        TYPESCRIPT_REGISTRY / name / "manifest.json",
    )


def write() -> None:
    for source, targets in COPIES.items():
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for name, abi_path in _abi_contracts().items():
        for manifest in _manifests(name):
            manifest.write_text(_expected_manifest(manifest, abi_path))


def _diff_bytes(
    actual: bytes, expected: bytes, actual_path: Path, source: Path
) -> list[str]:
    if actual == expected:
        return []
    diff = list(
        difflib.unified_diff(
            actual.decode("utf-8", errors="replace").splitlines(keepends=True),
            expected.decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=str(actual_path),
            tofile=str(source),
        )
    )
    return diff or [f"byte mismatch: {actual_path} != {source}\n"]


def check() -> list[str]:
    diffs: list[str] = []
    for source, targets in COPIES.items():
        expected = source.read_bytes()
        for target in targets:
            actual = target.read_bytes() if target.exists() else b""
            diffs.extend(_diff_bytes(actual, expected, target, source))
    for name, abi_path in _abi_contracts().items():
        for manifest in _manifests(name):
            expected = _expected_manifest(manifest, abi_path).encode()
            actual = manifest.read_bytes() if manifest.exists() else b""
            diffs.extend(_diff_bytes(actual, expected, manifest, abi_path))
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.write:
        write()
        print("OK: integration schemas, indexed ABIs, and shared assets updated")
        return 0

    diffs = check()
    if diffs:
        print("FAIL: integration schema package copies are stale")
        print("".join(diffs), end="")
        return 1
    print("OK: integration schemas, indexed ABIs, and shared assets are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
