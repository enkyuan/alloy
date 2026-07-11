#!/usr/bin/env python3
"""Copy canonical beta contracts into the Python and TypeScript packages."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "kaji" / "contracts"
TARGETS = (
    ROOT / "kaji" / "sdk" / "src" / "contracts",
    ROOT / "kaji" / "ts" / "contracts",
)


def contract_files() -> list[Path]:
    return sorted(
        path.relative_to(SOURCE)
        for path in SOURCE.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    )


def packaged_contract_files(target: Path) -> set[Path]:
    if not target.exists():
        return set()
    return {
        path.relative_to(target)
        for path in target.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    }


def write() -> None:
    expected = set(contract_files())
    for target in TARGETS:
        for relative in packaged_contract_files(target) - expected:
            (target / relative).unlink()
        for relative in expected:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)


def check() -> list[str]:
    errors: list[str] = []
    expected = set(contract_files())
    for target in TARGETS:
        actual = packaged_contract_files(target)
        for relative in sorted(expected - actual):
            errors.append(f"missing: {target / relative}")
        for relative in sorted(actual - expected):
            errors.append(f"unexpected: {target / relative}")
        for relative in sorted(expected & actual):
            source = SOURCE / relative
            destination = target / relative
            if destination.read_bytes() != source.read_bytes():
                errors.append(f"out of sync: {destination}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.write:
        write()
        print("OK: beta contract package copies updated")
        return 0

    errors = check()
    if errors:
        print("FAIL: beta contract package copies are stale")
        for error in errors:
            print(f"  {error}")
        return 1
    print("OK: beta contract package copies match canonical files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
