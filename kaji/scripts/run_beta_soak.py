#!/usr/bin/env python3
"""Run Python and TypeScript production-beta soak programs concurrently."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping

from beta_benchmark_gate import release_commit
from installed_release_runtime import installed_release_runtime
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
    parser.add_argument("--protected", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path)
    return parser.parse_args()


def soak_minutes(value: str) -> float:
    try:
        minutes = float(value)
    except ValueError as error:
        raise ValueError("minutes must be a positive finite number") from error
    if not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("minutes must be a positive finite number")
    return minutes


def _write_failure_receipt(
    output: Path,
    *,
    protected: bool,
    failure_code: str,
    commit: str | None,
    identity: Mapping[str, Any] | None = None,
) -> None:
    identity = {} if identity is None else identity
    identity = (
        {
            "commit": identity.get("commit", commit),
            "releaseManifestSha256": identity.get("releaseManifestSha256"),
            "artifacts": identity.get("artifacts", {}),
            "resolvedPackages": identity.get("resolvedPackages", {}),
            "typescriptConsumerLock": identity.get(
                "typescriptConsumerLock",
                {"templateSha256": None, "renderedSha256": None},
            ),
        }
        if protected
        else {}
    )
    _write_json_atomic(
        output,
        {
            "schemaVersion": 1,
            "protected": protected,
            **identity,
            "failureCode": failure_code,
            "failures": [failure_code],
            "passed": False,
        },
    )


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _retain_failure(
    output: Path,
    *,
    protected: bool,
    failure_code: str,
    commit: str | None,
    identity: Mapping[str, Any] | None = None,
) -> bool:
    try:
        _write_failure_receipt(
            output,
            protected=protected,
            failure_code=failure_code,
            commit=commit,
            identity=identity,
        )
    except OSError:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        print("FAIL: soak failure receipt could not be retained", file=sys.stderr)
        return False
    return True


def main() -> int:
    artifacts = ROOT / ".artifacts" / "kaji-soak"
    output = artifacts / "results.json"
    protected = "--protected" in sys.argv[1:]
    expected_commit = os.environ.get("KAJI_RELEASE_COMMIT")
    if not _retain_failure(
        output,
        protected=protected,
        failure_code="not_started",
        commit=expected_commit,
    ):
        return 1
    try:
        args = parse_args()
    except SystemExit as error:
        _retain_failure(
            output,
            protected=protected,
            failure_code="invalid_invocation",
            commit=expected_commit,
        )
        return error.code if isinstance(error.code, int) else 2
    protected = bool(args.protected)
    if not _retain_failure(
        output,
        protected=protected,
        failure_code="validating",
        commit=expected_commit,
    ):
        return 1
    try:
        minutes = soak_minutes(args.minutes)
    except ValueError as error:
        _retain_failure(
            output,
            protected=protected,
            failure_code="invalid_duration",
            commit=expected_commit,
        )
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    release_artifacts = getattr(args, "artifacts_dir", None)
    if protected and release_artifacts is None:
        _retain_failure(
            output,
            protected=True,
            failure_code="missing_artifacts",
            commit=expected_commit,
        )
        print("FAIL: --artifacts-dir is required in protected mode", file=sys.stderr)
        return 2
    if protected:
        try:
            expected_commit = release_commit(protected=True)
        except (CommandError, RuntimeError) as error:
            _retain_failure(
                output,
                protected=True,
                failure_code="invalid_release_commit",
                commit=expected_commit,
            )
            print(f"FAIL: {error}", file=sys.stderr)
            return 2
    python = python_command()
    if python is None:
        _retain_failure(
            output,
            protected=protected,
            failure_code="missing_python_runtime",
            commit=expected_commit,
        )
        print("uv or kaji/sdk/.venv is required", file=sys.stderr)
        return 2

    python_result = artifacts / "python.json"
    typescript_result = artifacts / "typescript.json"
    soak_budget = CommandBudget(
        timeout_seconds=minutes * 60 + 120,
        max_output_bytes=4 * 1024 * 1024,
    )
    installed_identity: Mapping[str, Any] | None = None
    try:
        context = (
            installed_release_runtime(
                release_artifacts,
                expected_commit=expected_commit,
            )
            if args.protected
            and release_artifacts is not None
            and expected_commit is not None
            else nullcontext(None)
        )
        with context as installed:
            runtime_identity_path = artifacts / "installed-runtime.json"
            if installed is not None:
                installed_identity = installed.identity()
                _write_json_atomic(runtime_identity_path, installed_identity)
            child_python = (
                [str(installed.python_executable)] if installed is not None else python
            )
            child_environment = installed.environment if installed is not None else None
            child_root = installed.root if installed is not None else ROOT
            typescript_workdir = (
                installed.typescript_workdir if installed is not None else ROOT
            )
            typescript_driver = (
                installed.typescript_soak
                if installed is not None
                else ROOT / "kaji" / "ts" / "benchmarks" / "runtime-soak.ts"
            )
            python_completed, typescript_completed = run_parallel_checked(
                (
                    CommandSpec(
                        [
                            *child_python,
                            str(SDK / "benchmarks" / "runtime_soak.py"),
                            "--minutes",
                            args.minutes,
                            "--seed",
                            "13",
                            "--artifacts-dir",
                            str(artifacts),
                            "--json",
                        ],
                        cwd=child_root,
                        budget=soak_budget,
                        capture=True,
                        env=child_environment,
                    ),
                    CommandSpec(
                        [
                            "bun",
                            str(typescript_driver),
                            "--minutes",
                            args.minutes,
                            "--seed",
                            "13",
                            "--artifact-dir",
                            str(artifacts),
                            "--json",
                        ],
                        cwd=typescript_workdir,
                        budget=soak_budget,
                        capture=True,
                        env=child_environment,
                    ),
                )
            )
            python_result.write_bytes(python_completed.stdout)
            typescript_result.write_bytes(typescript_completed.stdout)

            run_checked(
                [
                    *child_python,
                    str(GATE),
                    "--minutes",
                    args.minutes,
                    "--python",
                    str(python_result),
                    "--typescript",
                    str(typescript_result),
                    "--output",
                    str(output),
                    *(
                        ["--runtime-identity", str(runtime_identity_path)]
                        if installed is not None
                        else []
                    ),
                    *(["--protected"] if args.protected else []),
                ],
                cwd=child_root,
                budget=LOCAL_COMMAND_BUDGET,
                env=child_environment,
            )
    except KeyboardInterrupt:
        _retain_failure(
            output,
            protected=protected,
            failure_code="interrupted",
            commit=expected_commit,
            identity=installed_identity,
        )
        return 130
    except SystemExit:
        _retain_failure(
            output,
            protected=protected,
            failure_code="installed_runtime_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        return 1
    except CommandInterruptedError as error:
        _retain_failure(
            output,
            protected=protected,
            failure_code="interrupted",
            commit=expected_commit,
            identity=installed_identity,
        )
        return 128 + error.signum
    except CommandExitError:
        _retain_failure(
            output,
            protected=protected,
            failure_code="soak_gate_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        return 1
    except CommandError as error:
        _retain_failure(
            output,
            protected=protected,
            failure_code="soak_command_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        print(f"FAIL: soak child process failed: {error}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as error:
        _retain_failure(
            output,
            protected=protected,
            failure_code="installed_runtime_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        print(f"FAIL: installed soak setup failed: {error}", file=sys.stderr)
        return 1

    print("PASS: Python and TypeScript soak budgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
