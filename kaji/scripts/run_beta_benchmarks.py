#!/usr/bin/env python3
"""Run the quick, full, or calibration production-beta benchmark gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from benchmark_platform import (
    BenchmarkPlatformError,
    retain_reported_github_image_data,
)
from process_runner import (
    BENCHMARK_ORCHESTRATOR_BUDGET,
    LOCAL_COMMAND_BUDGET,
    CommandBudget,
    CommandExitError,
    CommandStartError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "kaji"
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


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    budget: CommandBudget = LOCAL_COMMAND_BUDGET,
) -> int:
    try:
        run_checked(command, cwd=cwd, budget=budget)
        return 0
    except CommandExitError as error:
        return error.returncode if error.returncode >= 0 else 128 - error.returncode
    except CommandStartError:
        print("FAIL: command could not be started", file=sys.stderr)
        return 127


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--quick", action="store_const", const="quick", dest="mode")
    mode.add_argument("--full", action="store_const", const="full", dest="mode")
    mode.add_argument(
        "--calibrate", action="store_const", const="calibrate", dest="mode"
    )
    parser.add_argument("--protected", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed = args.protected or args.mode in {"full", "calibrate"}
    artifacts_dir = getattr(args, "artifacts_dir", None)
    expected_commit = os.environ.get("KAJI_RELEASE_COMMIT")
    if installed and artifacts_dir is None:
        print(
            "FAIL: --artifacts-dir is required for protected/full/calibrate mode",
            file=sys.stderr,
        )
        return 2
    if installed and (
        expected_commit is None
        or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None
    ):
        print(
            "FAIL: exact KAJI_RELEASE_COMMIT is required for installed benchmarks",
            file=sys.stderr,
        )
        return 2
    selected = commands()
    if selected is None:
        print("uv or kaji/.venv is required", file=sys.stderr)
        return 2
    python, pytest = selected
    installed_args = (
        [
            "--artifacts-dir",
            str(artifacts_dir),
            "--expected-commit",
            expected_commit,
        ]
        if installed
        else []
    )

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
                "test",
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
                    *installed_args,
                    *(["--protected"] if args.protected else []),
                ],
                budget=BENCHMARK_ORCHESTRATOR_BUDGET,
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
        output = artifacts / "results.json"
        status = run(
            [
                *python,
                str(GATE),
                "--mode",
                "full",
                "--output",
                str(output),
                *installed_args,
                *(["--protected"] if args.protected else []),
            ],
            budget=BENCHMARK_ORCHESTRATOR_BUDGET,
        )
        if args.protected and (status == 0 or output.is_file()):
            try:
                retain_reported_github_image_data(output)
            except BenchmarkPlatformError as error:
                print(f"FAIL: {error}", file=sys.stderr)
                return status if status != 0 else 1
        if status == 0:
            print("PASS: full benchmark budgets and calibrated regression baseline")
        return status

    output = artifacts / "calibration-results.json"
    candidate = artifacts / "beta-baseline.candidate.json"
    status = run(
        [
            *python,
            str(GATE),
            "--mode",
            "calibrate",
            "--output",
            str(output),
            "--candidate-baseline",
            str(candidate),
            *installed_args,
            *(["--protected"] if args.protected else []),
        ],
        budget=BENCHMARK_ORCHESTRATOR_BUDGET,
    )
    if status == 0 or output.is_file():
        try:
            retain_reported_github_image_data(output)
        except BenchmarkPlatformError as error:
            candidate.unlink(missing_ok=True)
            print(f"FAIL: {error}", file=sys.stderr)
            return status if status != 0 else 1
    if status == 0:
        print("PASS: candidate baseline written for review")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
