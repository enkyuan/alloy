#!/usr/bin/env python3
"""Run the keyed OpenAI tool-loop readiness checks for both SDKs."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gpt-5.4-mini"


def run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> int:
    try:
        status = subprocess.run(
            command, cwd=cwd, env=environment, check=False
        ).returncode
        return status if status >= 0 else 128 - status
    except FileNotFoundError as error:
        print(f"FAIL: command not found: {error.filename}", file=sys.stderr)
        return 127


def main() -> int:
    model = os.environ.get("KAJI_LIVE_OPENAI_MODEL") or DEFAULT_MODEL
    if not os.environ.get("OPENAI_API_KEY"):
        if os.environ.get("KAJI_REQUIRE_LIVE_KEYS") == "1":
            print(
                "FAIL: OPENAI_API_KEY required for live readiness",
                file=sys.stderr,
            )
            return 2
        print("SKIP: OPENAI_API_KEY not set")
        return 0

    environment = os.environ.copy()
    environment["KAJI_LIVE_OPENAI_MODEL"] = model

    print(f"Running Python OpenAI live tool-loop with {model}", flush=True)
    status = run(
        [
            "uv",
            "run",
            "pytest",
            "-m",
            "integration",
            "tests/integration/test_openai_tools.py",
            "-q",
        ],
        cwd=ROOT / "kaji" / "sdk",
        environment=environment,
    )
    if status != 0:
        return status

    print(f"Running TypeScript OpenAI live tool-loop with {model}", flush=True)
    status = run(
        [
            "bun",
            "run",
            "test:integration",
            "tests/integration/openai-tools.test.ts",
        ],
        cwd=ROOT / "kaji" / "ts",
        environment=environment,
    )
    if status != 0:
        return status

    print("PASS: OpenAI live tool-loop readiness verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
