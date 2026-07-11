#!/usr/bin/env python3
"""Build, verify, and smoke-test the Python SDK release archives."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


SDK_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SDK_ROOT / "scripts"


def run(command: list[str]) -> None:
    """Run one release command from the SDK root and fail on any error."""
    status = subprocess.run(command, cwd=SDK_ROOT, check=False).returncode
    if status != 0:
        raise SystemExit(status if status >= 0 else 128 - status)


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def release_smoke(dist_dir: Path) -> None:
    dist_dir = dist_dir if dist_dir.is_absolute() else SDK_ROOT / dist_dir

    run([sys.executable, str(SCRIPTS / "clean_caches.py")])
    shutil.rmtree(SDK_ROOT / "build", ignore_errors=True)
    run(
        [
            "uv",
            "build",
            "--sdist",
            "--wheel",
            "--clear",
            "--out-dir",
            str(dist_dir),
            "--build-constraints",
            "build-requirements.txt",
            "--require-hashes",
        ]
    )
    run([sys.executable, str(SCRIPTS / "verify_archives.py"), str(dist_dir)])
    run(
        [
            sys.executable,
            str(SCRIPTS / "test_archive_verifier.py"),
            str(dist_dir),
        ]
    )

    temporary_parent = Path(os.environ.get("TMPDIR") or "/tmp")
    with TemporaryDirectory(
        prefix="kaji-sdk-release-smoke.",
        dir=temporary_parent,
    ) as temporary:
        workdir = Path(temporary)
        runtime_requirements = workdir / "runtime-requirements.txt"
        run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--extra",
                "openai",
                "--extra",
                "anthropic",
                "--output-file",
                str(runtime_requirements),
            ]
        )

        wheel = next(dist_dir.glob("*.whl"), None)
        sdist = next(dist_dir.glob("*.tar.gz"), None)
        if wheel is None or sdist is None:
            raise SystemExit(f"FAIL: expected wheel and sdist under {dist_dir}")

        for package in (wheel, sdist):
            safe_name = re.sub(r"[^a-zA-Z0-9]", "-", package.name)
            venv = workdir / f"venv-{safe_name}"
            run([sys.executable, "-m", "venv", str(venv)])
            python = venv_python(venv)
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "--requirement",
                    "build-requirements.txt",
                ]
            )
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "--requirement",
                    str(runtime_requirements),
                ]
            )
            run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--no-build-isolation",
                    str(package),
                ]
            )
            run([str(python), str(SCRIPTS / "smoke_install.py")])

    run([sys.executable, str(SCRIPTS / "verify_archives.py"), str(dist_dir)])
    print("PASS: release smoke verified")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path(os.environ.get("DIST_DIR") or "dist"),
        help="artifact output directory (default: DIST_DIR or dist)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    release_smoke(args.dist_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
