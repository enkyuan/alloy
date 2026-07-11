#!/usr/bin/env python3
"""Remove generated Python artifacts from the SDK checkout."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


SDK_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATHS = (
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".ty",
    ".coverage",
    "htmlcov",
)


def remove_path(path: Path) -> None:
    """Remove one file, symlink, or directory if it exists."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def clean_generated(root: Path) -> None:
    """Remove caches under source/test trees and known project-root caches."""
    for tree_name in ("src", "tests", "scripts"):
        tree = root / tree_name
        if not tree.is_dir():
            continue

        cache_dirs = sorted(
            (
                path
                for path in tree.rglob("__pycache__")
                if path.is_dir() and not path.is_symlink()
            ),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for cache_dir in cache_dirs:
            shutil.rmtree(cache_dir)

        for suffix in ("*.pyc", "*.pyo"):
            for artifact in tree.rglob(suffix):
                if artifact.is_file() or artifact.is_symlink():
                    artifact.unlink(missing_ok=True)

    for relative in CACHE_PATHS:
        remove_path(root / relative)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=SDK_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    clean_generated(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
