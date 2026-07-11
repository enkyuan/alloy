#!/usr/bin/env python3
"""Run Python and TypeScript production-beta soak programs concurrently."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import signal
import subprocess
import sys


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


class Terminated(RuntimeError):
    """The runner received a termination signal."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"received signal {signum}")


def terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    args = parse_args()
    python = python_command()
    if python is None:
        print("uv or kaji/sdk/.venv is required", file=sys.stderr)
        return 2

    artifacts = ROOT / ".artifacts" / "kaji-soak"
    artifacts.mkdir(parents=True, exist_ok=True)
    python_result = artifacts / "python.json"
    typescript_result = artifacts / "typescript.json"
    processes: list[subprocess.Popen[bytes]] = []

    def handle_termination(signum: int, _frame: object) -> None:
        raise Terminated(signum)

    previous_sigterm = signal.signal(signal.SIGTERM, handle_termination)

    try:
        with (
            python_result.open("w", encoding="utf-8") as python_output,
            typescript_result.open("w", encoding="utf-8") as typescript_output,
        ):
            processes.append(
                subprocess.Popen(
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
                    stdout=python_output,
                )
            )
            processes.append(
                subprocess.Popen(
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
                    stdout=typescript_output,
                )
            )
            python_status = processes[0].wait()
            typescript_status = processes[1].wait()
    except OSError as error:
        terminate(processes)
        print(f"FAIL: command not found: {error.filename}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126
    except KeyboardInterrupt:
        terminate(processes)
        return 130
    except Terminated as error:
        terminate(processes)
        return 128 + error.signum
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)

    try:
        gate_status = subprocess.run(
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
            check=False,
        ).returncode
    except FileNotFoundError as error:
        print(f"FAIL: command not found: {error.filename}", file=sys.stderr)
        return 127

    if python_status != 0 or typescript_status != 0 or gate_status != 0:
        return 1
    print("PASS: Python and TypeScript soak budgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
