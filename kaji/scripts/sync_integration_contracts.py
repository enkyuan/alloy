#!/usr/bin/env python3
"""Synchronize canonical integration schemas into both SDK registries."""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "kaji" / "contracts" / "integrations"
COPIES = {
    CONTRACTS / "manifest.schema.json": (
        ROOT / "kaji" / "sdk" / "src" / "integrations" / "registry" / "schema.json",
        ROOT / "kaji" / "ts" / "registry" / "schema.json",
    ),
    CONTRACTS / "index.schema.json": (
        ROOT
        / "kaji"
        / "sdk"
        / "src"
        / "integrations"
        / "registry"
        / "index.schema.json",
        ROOT / "kaji" / "ts" / "registry" / "index.schema.json",
    ),
}
ECHO_ABI = CONTRACTS / "echo-tool-abi-v1.json"
ECHO_MANIFESTS = (
    ROOT
    / "kaji"
    / "sdk"
    / "src"
    / "integrations"
    / "registry"
    / "echo"
    / "manifest.json",
    ROOT / "kaji" / "ts" / "registry" / "echo" / "manifest.json",
)
ECHO_TYPESCRIPT_SOURCE = ROOT / "kaji" / "ts" / "registry" / "echo" / "index.ts"
ECHO_TYPESCRIPT_COPY = (
    ROOT / "kaji" / "sdk" / "src" / "integrations" / "registry" / "echo" / "echo.ts"
)


def _echo_abi() -> tuple[str, list[dict[str, Any]]]:
    document = json.loads(ECHO_ABI.read_text())
    return document["namespace"], document["tools"]


def _expected_manifest(path: Path) -> str:
    namespace, tools = _echo_abi()
    document = json.loads(path.read_text())
    document["namespace"] = namespace
    document["tools"] = tools
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write() -> None:
    for source, targets in COPIES.items():
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for manifest in ECHO_MANIFESTS:
        manifest.write_text(_expected_manifest(manifest))
    shutil.copyfile(ECHO_TYPESCRIPT_SOURCE, ECHO_TYPESCRIPT_COPY)


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
    for manifest in ECHO_MANIFESTS:
        expected = _expected_manifest(manifest).encode()
        actual = manifest.read_bytes()
        diffs.extend(_diff_bytes(actual, expected, manifest, ECHO_ABI))
    expected_source = ECHO_TYPESCRIPT_SOURCE.read_bytes()
    actual_source = (
        ECHO_TYPESCRIPT_COPY.read_bytes() if ECHO_TYPESCRIPT_COPY.exists() else b""
    )
    diffs.extend(
        _diff_bytes(
            actual_source,
            expected_source,
            ECHO_TYPESCRIPT_COPY,
            ECHO_TYPESCRIPT_SOURCE,
        )
    )
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.write:
        write()
        print("OK: integration schemas, Echo ABI, and source copies updated")
        return 0

    diffs = check()
    if diffs:
        print("FAIL: integration schema package copies are stale")
        print("".join(diffs), end="")
        return 1
    print("OK: integration schemas, Echo ABI, and source copies are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
