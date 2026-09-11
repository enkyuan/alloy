#!/usr/bin/env python3
"""Synchronize canonical beta contracts into package-specific projections."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


_PROJECTION_PATH = Path(__file__).resolve().parents[2] / "contracts" / "projection.py"
_PROJECTION_SPEC = importlib.util.spec_from_file_location(
    "kaji_contract_projection", _PROJECTION_PATH
)
if _PROJECTION_SPEC is None or _PROJECTION_SPEC.loader is None:
    raise RuntimeError(f"unable to load contract projection helper: {_PROJECTION_PATH}")
_PROJECTION = importlib.util.module_from_spec(_PROJECTION_SPEC)
_PROJECTION_SPEC.loader.exec_module(_PROJECTION)

PYTHON_LEGACY_CONTRACTS = _PROJECTION.PYTHON_LEGACY_CONTRACTS
TYPESCRIPT_PROJECTED_CONTRACTS = _PROJECTION.TYPESCRIPT_PROJECTED_CONTRACTS
typescript_contract_projection = _PROJECTION.typescript_contract_projection


ROOT = (
    next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "contracts").is_dir() and (parent / "packages").is_dir()
    )
).parent
SOURCE = ROOT / "kaji" / "contracts"
TARGETS = (
    ROOT / "kaji" / "packages" / "py" / "src" / "contracts",
    ROOT / "kaji" / "packages" / "ts" / "contracts",
)
TYPESCRIPT_PACKAGE_CONTRACTS = TARGETS[1]


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


def expected_contract_files(target: Path) -> set[Path]:
    expected = set(contract_files())
    if target == TYPESCRIPT_PACKAGE_CONTRACTS:
        expected -= {Path(relative) for relative in PYTHON_LEGACY_CONTRACTS}
    return expected


def expected_contract_bytes(target: Path, relative: Path) -> bytes:
    source = SOURCE / relative
    if (
        target == TYPESCRIPT_PACKAGE_CONTRACTS
        and relative.as_posix() in TYPESCRIPT_PROJECTED_CONTRACTS
    ):
        return typescript_contract_projection(relative, source)
    return source.read_bytes()


def write() -> None:
    for target in TARGETS:
        expected = expected_contract_files(target)
        for relative in packaged_contract_files(target) - expected:
            (target / relative).unlink()
        for relative in expected:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(expected_contract_bytes(target, relative))


def check() -> list[str]:
    errors: list[str] = []
    for target in TARGETS:
        expected = expected_contract_files(target)
        actual = packaged_contract_files(target)
        for relative in sorted(expected - actual):
            errors.append(f"missing: {target / relative}")
        for relative in sorted(actual - expected):
            errors.append(f"unexpected: {target / relative}")
        for relative in sorted(expected & actual):
            destination = target / relative
            if destination.read_bytes() != expected_contract_bytes(target, relative):
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
