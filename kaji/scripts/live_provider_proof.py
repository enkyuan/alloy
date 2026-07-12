#!/usr/bin/env python3
"""Run the protected keyed provider proofs and retain their status."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from process_runner import (
    PROVIDER_ORCHESTRATOR_BUDGET,
    PROVIDER_PROOF_BUDGET,
    CommandBudget,
    CommandExitError,
    CommandStartError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
OPENAI_LOOP_CHECK = Path(__file__).with_name("verify_openai_loop.py")


def run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    budget: CommandBudget = PROVIDER_PROOF_BUDGET,
) -> int:
    try:
        run_checked(
            command,
            cwd=cwd,
            env=environment,
            budget=budget,
        )
        return 0
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    except CommandStartError:
        print("FAIL: command could not be started", file=sys.stderr)
        return 127


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "FAIL: OPENAI_API_KEY is required for keyed provider proof",
            file=sys.stderr,
        )
        return 2

    environment = os.environ.copy()
    openai_environment = environment.copy()
    openai_environment["KAJI_REQUIRE_LIVE_KEYS"] = "1"
    status = run(
        [sys.executable, str(OPENAI_LOOP_CHECK)],
        cwd=ROOT,
        environment=openai_environment,
        budget=PROVIDER_ORCHESTRATOR_BUDGET,
    )
    if status != 0:
        return status

    anthropic_status = "not_configured"
    if environment.get("ANTHROPIC_API_KEY"):
        print("Running Python Anthropic normalized tool-call proof", flush=True)
        status = run(
            [
                "uv",
                "run",
                "--extra",
                "anthropic",
                "pytest",
                "-m",
                "integration",
                "tests/integration/test_anthropic_provider.py",
                "-k",
                "normalized_tool_call",
                "-q",
            ],
            cwd=ROOT / "kaji" / "sdk",
            environment=environment,
        )
        if status != 0:
            return status

        print("Running TypeScript Anthropic normalized tool-call proof", flush=True)
        status = run(
            [
                "bun",
                "run",
                "test:integration",
                "tests/integration/anthropic-live.test.ts",
                "-t",
                "normalized tool call",
            ],
            cwd=ROOT / "kaji" / "ts",
            environment=environment,
        )
        if status != 0:
            return status
        anthropic_status = "passed"

    retained_status = f"STATUS: openai=passed\nSTATUS: anthropic={anthropic_status}"
    print(retained_status)
    status_file = environment.get("KAJI_PROVIDER_STATUS_FILE")
    if status_file:
        Path(status_file).write_text(retained_status + "\n", encoding="utf-8")
    summary_file = environment.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as stream:
            stream.write(
                f"## Keyed provider proof\n\n```text\n{retained_status}\n```\n"
            )

    print("PASS: required OpenAI keyed provider proof completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
