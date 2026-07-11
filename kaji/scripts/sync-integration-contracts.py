#!/usr/bin/env python3
"""Synchronize canonical integration schemas into both SDK registries."""

from __future__ import annotations

import argparse
import difflib
import shutil
from pathlib import Path


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


def write() -> None:
    for source, targets in COPIES.items():
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def check() -> list[str]:
    diffs: list[str] = []
    for source, targets in COPIES.items():
        expected = source.read_text().splitlines(keepends=True)
        for target in targets:
            actual = target.read_text().splitlines(keepends=True) if target.exists() else []
            if actual == expected:
                continue
            diffs.extend(
                difflib.unified_diff(
                    actual,
                    expected,
                    fromfile=str(target),
                    tofile=str(source),
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
        print("OK: integration schema package copies updated")
        return 0

    diffs = check()
    if diffs:
        print("FAIL: integration schema package copies are stale")
        print("".join(diffs), end="")
        return 1
    print("OK: integration schema package copies match canonical schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
