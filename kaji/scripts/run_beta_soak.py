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

from benchmark_platform import (
    IMAGE_DATA_PATH,
    BenchmarkPlatformError,
    retain_reported_github_image_data,
)
from beta_benchmark_gate import COMMIT_PATTERN, HASH_PATTERN, release_commit
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
SDK = ROOT / "kaji"
GATE = Path(__file__).with_name("beta_soak_gate.py")
PROTECTED_GATE_PARENT_ENV = (
    "GITHUB_ACTIONS",
    "RUNNER_ENVIRONMENT",
    "RUNNER_OS",
    "RUNNER_ARCH",
    "ImageOS",
    "ImageVersion",
)
FAILURE_CODES = frozenset(
    {
        "not_started",
        "invalid_invocation",
        "validating",
        "invalid_duration",
        "missing_artifacts",
        "invalid_release_commit",
        "missing_python_runtime",
        "python_soak_failed",
        "typescript_soak_failed",
        "soak_child_failed",
        "soak_gate_failed",
        "interrupted",
        "installed_runtime_failed",
        "soak_command_failed",
        "runner_image_evidence_failed",
    }
)
EXPECTED_ARTIFACTS = {
    "python": "kaji_sdk-0.2.0b1-py3-none-any.whl",
    "typescript": "kaji-sdk-0.2.0-beta.7.tgz",
}


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


def _protected_gate_environment(
    environment: Mapping[str, str], commit: str
) -> dict[str, str]:
    gate_environment = dict(environment)
    gate_environment["KAJI_RELEASE_COMMIT"] = commit
    for name in PROTECTED_GATE_PARENT_ENV:
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"protected soak requires {name}")
        gate_environment[name] = value
    return gate_environment


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
    diagnostics: Mapping[str, Any] | None = None,
) -> None:
    source_identity = {} if identity is None else identity
    safe_commit = source_identity.get("commit", commit)
    safe_commit = (
        safe_commit
        if isinstance(safe_commit, str)
        and COMMIT_PATTERN.fullmatch(safe_commit) is not None
        else None
    )
    manifest = source_identity.get("releaseManifestSha256")
    manifest = (
        manifest
        if isinstance(manifest, str) and HASH_PATTERN.fullmatch(manifest) is not None
        else None
    )
    source_artifacts = source_identity.get("artifacts")
    safe_artifacts: dict[str, dict[str, str]] = {}
    if isinstance(source_artifacts, Mapping):
        for runtime, expected_file in EXPECTED_ARTIFACTS.items():
            artifact = source_artifacts.get(runtime)
            if not isinstance(artifact, Mapping):
                continue
            digest = artifact.get("sha256")
            if (
                artifact.get("file") == expected_file
                and isinstance(digest, str)
                and HASH_PATTERN.fullmatch(digest) is not None
            ):
                safe_artifacts[runtime] = {
                    "file": expected_file,
                    "sha256": digest,
                }
    source_lock = source_identity.get("typescriptConsumerLock")
    safe_lock = {"templateSha256": None, "renderedSha256": None}
    if isinstance(source_lock, Mapping):
        for name in safe_lock:
            digest = source_lock.get(name)
            if isinstance(digest, str) and HASH_PATTERN.fullmatch(digest) is not None:
                safe_lock[name] = digest
    safe_identity = (
        {
            "commit": safe_commit,
            "releaseManifestSha256": manifest,
            "artifacts": safe_artifacts,
            "resolvedPackages": {},
            "typescriptConsumerLock": safe_lock,
        }
        if protected
        else {}
    )
    safe_failure_code = failure_code if failure_code in FAILURE_CODES else "soak_failed"
    safe_diagnostics: dict[str, Any] = {}
    if diagnostics is not None:
        phase = diagnostics.get("phase")
        runtime = diagnostics.get("runtime")
        exit_status = diagnostics.get("exitStatus")
        if phase in {"child", "gate"}:
            safe_diagnostics["phase"] = phase
        if runtime in {"python", "typescript", None}:
            safe_diagnostics["runtime"] = runtime
        if type(exit_status) is int:
            safe_diagnostics["exitStatus"] = exit_status
    _write_json_atomic(
        output,
        {
            "schemaVersion": 1,
            "protected": protected,
            **safe_identity,
            "failureCode": safe_failure_code,
            "failures": [safe_failure_code],
            "passed": False,
            **({"diagnostics": safe_diagnostics} if safe_diagnostics else {}),
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


def _reset_artifacts(artifacts: Path) -> None:
    if artifacts.is_symlink() or artifacts.is_file():
        artifacts.unlink()
    elif artifacts.exists():
        shutil.rmtree(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)


def _retain_failure(
    output: Path,
    *,
    protected: bool,
    failure_code: str,
    commit: str | None,
    identity: Mapping[str, Any] | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> bool:
    try:
        _write_failure_receipt(
            output,
            protected=protected,
            failure_code=failure_code,
            commit=commit,
            identity=identity,
            diagnostics=diagnostics,
        )
    except OSError:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        print("FAIL: soak failure receipt could not be retained", file=sys.stderr)
        return False
    return True


def _child_failure(
    error: CommandExitError,
) -> tuple[str, dict[str, Any]]:
    runtime = {0: "python", 1: "typescript"}.get(error.command_index)
    failure_code = f"{runtime}_soak_failed" if runtime else "soak_child_failed"
    return (
        failure_code,
        {
            "phase": "child",
            "runtime": runtime,
            "exitStatus": error.returncode,
        },
    )


def _has_detailed_gate_failure(output: Path) -> bool:
    try:
        report = json.loads(output.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if (
        not isinstance(report, dict)
        or report.get("schemaVersion") != 1
        or report.get("passed") is not False
        or isinstance(report.get("requestedMinutes"), bool)
        or not isinstance(report.get("requestedMinutes"), (int, float))
        or not isinstance(report.get("budgets"), dict)
        or not isinstance(report.get("results"), dict)
    ):
        return False
    failures = report.get("failures")
    return (
        isinstance(failures, list)
        and bool(failures)
        and all(isinstance(failure, str) and failure for failure in failures)
    )


def _passed_gate_results(output: Path) -> dict[str, dict[str, Any]] | None:
    try:
        report = json.loads(output.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(report, dict)
        or report.get("schemaVersion") != 1
        or report.get("passed") is not True
        or report.get("failures") != []
        or isinstance(report.get("requestedMinutes"), bool)
        or not isinstance(report.get("requestedMinutes"), (int, float))
        or not isinstance(report.get("budgets"), dict)
    ):
        return None
    results = report.get("results")
    if not isinstance(results, dict) or set(results) != {"python", "typescript"}:
        return None
    for runtime in ("python", "typescript"):
        result = results[runtime]
        resolved_package = (
            result.get("resolvedPackage") if isinstance(result, dict) else None
        )
        if (
            not isinstance(result, dict)
            or result.get("schemaVersion") != 2
            or result.get("runtime") != runtime
            or not isinstance(resolved_package, str)
            or not resolved_package
        ):
            return None
    return results


def main() -> int:
    artifacts = ROOT / ".artifacts" / "kaji-soak"
    output = artifacts / "results.json"
    protected = "--protected" in sys.argv[1:]
    expected_commit = os.environ.get("KAJI_RELEASE_COMMIT")
    try:
        _reset_artifacts(artifacts)
    except OSError:
        print("FAIL: soak artifact directory could not be prepared", file=sys.stderr)
        return 1
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
        except (CommandError, RuntimeError):
            _retain_failure(
                output,
                protected=True,
                failure_code="invalid_release_commit",
                commit=expected_commit,
            )
            print("FAIL: release commit validation failed", file=sys.stderr)
            return 2
    python = python_command()
    if python is None:
        _retain_failure(
            output,
            protected=protected,
            failure_code="missing_python_runtime",
            commit=expected_commit,
        )
        print("uv or kaji/.venv is required", file=sys.stderr)
        return 2

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
        with (
            context as installed,
            tempfile.TemporaryDirectory(prefix="kaji-soak-child-") as child_output,
        ):
            python_result = Path(child_output) / "python.json"
            typescript_result = Path(child_output) / "typescript.json"
            child_artifacts = Path(child_output) / "artifacts"
            runtime_identity_path = artifacts / "installed-runtime.json"
            if installed is not None:
                installed_identity = installed.identity()
            child_python = (
                [str(installed.python_executable)] if installed is not None else python
            )
            child_environment = installed.environment if installed is not None else None
            gate_environment = child_environment
            if args.protected:
                if child_environment is None or expected_commit is None:
                    raise RuntimeError(
                        "protected soak requires an isolated validated runtime"
                    )
                gate_environment = _protected_gate_environment(
                    child_environment,
                    expected_commit,
                )
            child_root = installed.root if installed is not None else ROOT
            typescript_workdir = (
                installed.typescript_workdir if installed is not None else ROOT
            )
            typescript_driver = (
                installed.typescript_soak
                if installed is not None
                else ROOT / "kaji" / "ts" / "benchmarks" / "runtime-soak.ts"
            )
            try:
                python_completed, typescript_completed = run_parallel_checked(
                    (
                        CommandSpec(
                            [
                                *child_python,
                                str(SDK / "benchmarks" / "python" / "runtime_soak.py"),
                                "--minutes",
                                args.minutes,
                                "--seed",
                                "13",
                                "--artifacts-dir",
                                str(child_artifacts),
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
                                str(child_artifacts),
                                "--json",
                            ],
                            cwd=typescript_workdir,
                            budget=soak_budget,
                            capture=True,
                            env=child_environment,
                        ),
                    )
                )
            except CommandExitError as error:
                failure_code, diagnostics = _child_failure(error)
                _retain_failure(
                    output,
                    protected=protected,
                    failure_code=failure_code,
                    commit=expected_commit,
                    identity=installed_identity,
                    diagnostics=diagnostics,
                )
                runtime = diagnostics["runtime"] or "unknown"
                print(
                    f"FAIL: {runtime} soak exited with status {error.returncode}",
                    file=sys.stderr,
                )
                return 1
            python_result.write_bytes(python_completed.stdout)
            typescript_result.write_bytes(typescript_completed.stdout)

            _reset_artifacts(artifacts)
            if installed_identity is not None:
                _write_json_atomic(runtime_identity_path, installed_identity)
            output.unlink(missing_ok=True)
            gate_completed = run_checked(
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
                    *(
                        ["--runner-image-data", str(IMAGE_DATA_PATH)]
                        if args.protected
                        else []
                    ),
                    *(["--protected"] if args.protected else []),
                ],
                cwd=child_root,
                budget=LOCAL_COMMAND_BUDGET,
                env=gate_environment,
                check=False,
            )
            gate_status = getattr(gate_completed, "returncode", 0)
            if gate_status != 0:
                if _has_detailed_gate_failure(output):
                    report = json.loads(output.read_text())
                    for failure in report["failures"]:
                        print(f"FAIL: {failure}", file=sys.stderr)
                else:
                    _retain_failure(
                        output,
                        protected=protected,
                        failure_code="soak_gate_failed",
                        commit=expected_commit,
                        identity=installed_identity,
                        diagnostics={
                            "phase": "gate",
                            "runtime": None,
                            "exitStatus": gate_status,
                        },
                    )
                return 1
            results = _passed_gate_results(output)
            if results is None:
                _retain_failure(
                    output,
                    protected=protected,
                    failure_code="soak_gate_failed",
                    commit=expected_commit,
                    identity=installed_identity,
                    diagnostics={
                        "phase": "gate",
                        "runtime": None,
                        "exitStatus": gate_status,
                    },
                )
                print("FAIL: soak gate produced an invalid report", file=sys.stderr)
                return 1
            try:
                for runtime in ("python", "typescript"):
                    _write_json_atomic(artifacts / f"{runtime}.json", results[runtime])
            except OSError:
                _reset_artifacts(artifacts)
                raise
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
    except CommandError:
        _retain_failure(
            output,
            protected=protected,
            failure_code="soak_command_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        print("FAIL: soak child process failed", file=sys.stderr)
        return 1
    except (OSError, RuntimeError):
        _retain_failure(
            output,
            protected=protected,
            failure_code="installed_runtime_failed",
            commit=expected_commit,
            identity=installed_identity,
        )
        print("FAIL: installed soak setup failed", file=sys.stderr)
        return 1

    if protected:
        try:
            retain_reported_github_image_data(output)
        except BenchmarkPlatformError:
            _retain_failure(
                output,
                protected=True,
                failure_code="runner_image_evidence_failed",
                commit=expected_commit,
                identity=installed_identity,
            )
            print("FAIL: runner image evidence failed", file=sys.stderr)
            return 1

    print("PASS: Python and TypeScript soak budgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
