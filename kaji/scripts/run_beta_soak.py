#!/usr/bin/env python3
"""Run Python and TypeScript production-beta soak programs concurrently."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import shutil
import sys

from process_runner import (
    LOCAL_COMMAND_BUDGET,
    CommandBudget,
    CommandError,
    CommandExitError,
    CommandInterruptedError,
    CommandSpec,
    run_checked,
    run_parallel_checked,
)


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji" / "sdk"
GATE = Path(__file__).with_name("beta_soak_gate.py")


def python_command() -> list[str] | None:
    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "run", "--project", str(SDK), "python"]
    python = SDK / ".venv" / "bin" / "python"
    return [str(python)] if python.is_file() else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", default="30")
    return parser.parse_args()


def soak_minutes(value: str) -> float:
    try:
        minutes = float(value)
    except ValueError as error:
        raise ValueError("minutes must be a positive finite number") from error
    if not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("minutes must be a positive finite number")
    return minutes


def main() -> int:
    args = parse_args()
    try:
        minutes = soak_minutes(args.minutes)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    python = python_command()
    if python is None:
        print("uv or kaji/sdk/.venv is required", file=sys.stderr)
        return 2

    artifacts = ROOT / ".artifacts" / "kaji-soak"
    artifacts.mkdir(parents=True, exist_ok=True)
    python_result = artifacts / "python.json"
    typescript_result = artifacts / "typescript.json"
    soak_budget = CommandBudget(
        timeout_seconds=minutes * 60 + 120,
        max_output_bytes=4 * 1024 * 1024,
    )
    try:
        python_completed, typescript_completed = run_parallel_checked(
            (
                CommandSpec(
                    [
                        *python,
                        str(SDK / "benchmarks" / "runtime_soak.py"),
                        "--minutes",
                        args.minutes,
                        "--minimum-turns",
                        "10000",
                        "--seed",
                        "13",
                        "--artifacts-dir",
                        str(artifacts),
                        "--json",
                    ],
                    cwd=ROOT,
                    budget=soak_budget,
                    capture=True,
                ),
                CommandSpec(
                    [
                        "bun",
                        str(ROOT / "kaji" / "ts" / "benchmarks" / "runtime-soak.ts"),
                        "--minutes",
                        args.minutes,
                        "--seed",
                        "13",
                        "--artifacts-dir",
                        str(artifacts),
                        "--json",
                    ],
                    cwd=ROOT,
                    budget=soak_budget,
                    capture=True,
                ),
            )
        )
        python_result.write_bytes(python_completed.stdout)
        typescript_result.write_bytes(typescript_completed.stdout)
    except KeyboardInterrupt:
        return 130
    except CommandInterruptedError as error:
        return 128 + error.signum
    except CommandExitError:
        return 1
    except CommandError as error:
        print(f"FAIL: soak child process failed: {error}", file=sys.stderr)
        return 1

    try:
        run_checked(
            [
                *python,
                str(GATE),
                "--minutes",
                args.minutes,
                "--python",
                str(python_result),
                "--typescript",
                str(typescript_result),
                "--output",
                str(artifacts / "results.json"),
            ],
            cwd=ROOT,
            budget=LOCAL_COMMAND_BUDGET,
        )
    except CommandExitError:
        return 1
    except CommandError:
        return 127

    print("PASS: Python and TypeScript soak budgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
