#!/usr/bin/env python3
"""Run the keyed OpenAI tool-loop readiness checks for both SDKs."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from process_runner import (
    PROVIDER_PROOF_BUDGET,
    CommandExitError,
    CommandStartError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gpt-5.4-mini"


def run_command(command: list[str], *, cwd: Path, environment: dict[str, str]) -> int:
    try:
        run_checked(
            command,
            cwd=cwd,
            env=environment,
            budget=PROVIDER_PROOF_BUDGET,
        )
        return 0
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    except CommandStartError:
        print("FAIL: command could not be started", file=sys.stderr)
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
    status = run_command(
        [
            "uv",
            "run",
            "pytest",
            "-m",
            "integration",
            "tests/integration/test_openai_tools.py",
            "-q",
        ],
        cwd=ROOT / "kaji",
        environment=environment,
    )
    if status != 0:
        return status

    print(f"Running TypeScript OpenAI live tool-loop with {model}", flush=True)
    status = run_command(
        [
            "bun",
            "run",
            "test:integration",
            "tests/integration/openai-tools.test.ts",
        ],
        cwd=ROOT / "kaji" / "packages" / "typescript",
        environment=environment,
    )
    if status != 0:
        return status

    print("PASS: OpenAI live tool-loop readiness verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
