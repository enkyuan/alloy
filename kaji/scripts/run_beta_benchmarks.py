#!/usr/bin/env python3
"""Run the quick, full, or calibration production-beta benchmark gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji" / "sdk"
TYPESCRIPT = ROOT / "kaji" / "ts"
GATE = Path(__file__).with_name("beta_benchmark_gate.py")


def commands() -> tuple[list[str], list[str]] | None:
    uv = shutil.which("uv")
    if uv is not None:
        prefix = [uv, "run", "--project", str(SDK)]
        return [*prefix, "python"], [*prefix, "pytest"]
    python = SDK / ".venv" / "bin" / "python"
    pytest = SDK / ".venv" / "bin" / "pytest"
    if python.is_file() and pytest.is_file():
        return [str(python)], [str(pytest)]
    return None


def run(command: list[str], *, cwd: Path = ROOT) -> int:
    try:
        status = subprocess.run(command, cwd=cwd, check=False).returncode
        return status if status >= 0 else 128 - status
    except FileNotFoundError as error:
        print(f"FAIL: command not found: {error.filename}", file=sys.stderr)
        return 127


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_const", const="quick", dest="mode")
    mode.add_argument("--full", action="store_const", const="full", dest="mode")
    mode.add_argument(
        "--calibrate", action="store_const", const="calibrate", dest="mode"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = commands()
    if selected is None:
        print("uv or kaji/sdk/.venv is required", file=sys.stderr)
        return 2
    python, pytest = selected

    if args.mode == "quick":
        status = run(
            [
                *pytest,
                str(SDK / "tests" / "test_runtime_complexity.py"),
                str(SDK / "tests" / "test_runtime_faults.py"),
                str(SDK / "tests" / "test_events_journal.py"),
                str(SDK / "tests" / "test_runtime_concurrency.py"),
                str(SDK / "tests" / "test_tool_execution_limits.py"),
                str(SDK / "tests" / "test_approval_lifecycle.py"),
                "-q",
                "--no-cov",
            ]
        )
        if status != 0:
            return status
        status = run(
            [
                "bun",
                "run",
                "vitest",
                "run",
                "tests/runtime-complexity.test.ts",
                "tests/runtime-faults.test.ts",
                "tests/event-delivery.test.ts",
                "tests/runtime-concurrency.test.ts",
                "tests/tool-execution-limits.test.ts",
                "tests/approval-lifecycle.test.ts",
                "tests/safe-fetch.test.ts",
                "tests/registry-resource-limits.test.ts",
            ],
            cwd=TYPESCRIPT,
        )
        if status != 0:
            return status
        with tempfile.TemporaryDirectory(prefix="kaji-benchmark-quick-") as temporary:
            output = Path(temporary) / "quick-results.json"
            status = run(
                [
                    *python,
                    str(GATE),
                    "--mode",
                    "quick",
                    "--output",
                    str(output),
                ]
            )
            if status != 0:
                return status
            try:
                result = json.loads(output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                print(
                    f"FAIL: unreadable quick benchmark report: {error}", file=sys.stderr
                )
                return 1
            if result.get("passed") is not True or result.get("mode") != "quick":
                print("FAIL: quick benchmark report did not pass", file=sys.stderr)
                return 1
        print("PASS: deterministic complexity/fault gates and quick benchmark smoke")
        return 0

    artifacts = ROOT / ".artifacts" / "kaji-benchmarks"
    artifacts.mkdir(parents=True, exist_ok=True)
    if args.mode == "full":
        status = run(
            [
                *python,
                str(GATE),
                "--mode",
                "full",
                "--output",
                str(artifacts / "results.json"),
            ]
        )
        if status == 0:
            print("PASS: full benchmark budgets and calibrated regression baseline")
        return status

    status = run(
        [
            *python,
            str(GATE),
            "--mode",
            "calibrate",
            "--output",
            str(artifacts / "calibration-results.json"),
            "--candidate-baseline",
            str(artifacts / "beta-baseline.candidate.json"),
        ]
    )
    if status == 0:
        print("PASS: candidate baseline written for review")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
