#!/usr/bin/env python3
"""Run and validate the cross-runtime production-beta benchmark programs."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import sys
from typing import Any

from benchmark_platform import runner_fingerprint, validate_retained_runner
from installed_release_runtime import (
    InstalledReleaseRuntime,
    installed_release_runtime,
)

from process_runner import (
    BENCHMARK_COMMAND_BUDGET,
    METADATA_BUDGET,
    CommandError,
    run_checked,
)


ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "replay10k",
    "crossSession100",
    "sameSession25",
    "toolBatch100",
    "context10kIterations5",
    "crossSessionCommit100",
    "streamDeltas10k",
    "toolArgDeltas10k",
)
BUDGETS_PATH = ROOT / "kaji" / "benchmarks" / "beta-budgets.json"
BASELINE_PATH = ROOT / "kaji" / "benchmarks" / "beta-baseline.json"
BENCHMARK_SEED = 13
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
SAMPLE_FAILURE_MARKER = re.compile(
    rb"KAJI_BENCHMARK_SAMPLE_FAILURE "
    rb"variant=(replay|indexed) status=(-?(?:0|[1-9][0-9]{0,9}))"
)
SOURCE_TREE_ROOTS = (
    Path("kaji/packages/python/src/kaji"),
    Path("kaji/packages/typescript/src"),
)
SOURCE_INPUTS = (
    Path("kaji/benchmarks/python/runtime_benchmark.py"),
    Path("kaji/packages/typescript/benchmarks/runtime-benchmark.ts"),
    Path("kaji/benchmarks/python/runtime_soak.py"),
    Path("kaji/packages/typescript/benchmarks/runtime-soak.ts"),
    Path("kaji/scripts/beta_benchmark_gate.py"),
    Path("kaji/scripts/run_beta_benchmarks.py"),
    Path("kaji/scripts/beta_soak_gate.py"),
    Path("kaji/scripts/run_beta_soak.py"),
    Path("kaji/scripts/process_runner.py"),
    Path("kaji/scripts/benchmark_platform.py"),
    Path("kaji/scripts/installed_release_runtime.py"),
    Path("kaji/scripts/installed-typescript-runtime/package.core.json"),
    Path("kaji/scripts/installed-typescript-runtime/package-lock.core.json"),
    Path("kaji/scripts/installed-typescript-runtime/package.json"),
    Path("kaji/scripts/installed-typescript-runtime/package-lock.json"),
    Path("kaji/scripts/verify_release_artifacts.py"),
    Path("kaji/benchmarks/beta-budgets.json"),
    Path("kaji/packages/python/pyproject.toml"),
    Path("kaji/packages/typescript/package.json"),
    Path("kaji/packages/typescript/tsconfig.json"),
)


def _command_version(command: list[str]) -> str:
    return (
        run_checked(
            command,
            cwd=ROOT,
            budget=METADATA_BUDGET,
            capture=True,
        )
        .stdout.decode("utf-8")
        .strip()
    )


def _lock_hash() -> str:
    digest = hashlib.sha256()
    # TODO(migration): re-baseline kaji/benchmarks/beta-baseline.json —
    # the Python lock moved to the workspace-root uv.lock, so both the hashed
    # relative path and its bytes changed; the stored dependencyLockHash is stale.
    for relative in ("bun.lock", "uv.lock"):
        path = ROOT / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_hash(root: Path | None = None) -> str:
    root = ROOT if root is None else root
    relative_paths = set(SOURCE_INPUTS)
    for relative_root in SOURCE_TREE_ROOTS:
        source_root = root / relative_root
        if not source_root.is_dir():
            raise RuntimeError(f"performance source tree is missing: {relative_root}")
        relative_paths.update(
            path.relative_to(root)
            for path in source_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )

    digest = hashlib.sha256()
    for relative in sorted(relative_paths, key=lambda path: path.as_posix()):
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"performance source input is missing: {relative}")
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _checked_out_commit() -> str:
    commit = _command_version(["git", "rev-parse", "HEAD"])
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise RuntimeError(
            "checked-out commit is not exactly 40 lowercase hex characters"
        )
    return commit


def _commit() -> str:
    return _checked_out_commit()


def fingerprint(
    *,
    protected: bool = False,
    calibrating: bool = False,
    image_data_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "runner": runner_fingerprint(
            protected=protected,
            calibrating=calibrating,
            image_data_path=image_data_path,
        ),
        "versions": {
            "python": platform.python_version(),
            "node": _command_version(["node", "--version"]),
            "bun": _command_version(["bun", "--version"]),
        },
        "dependencyLockHash": _lock_hash(),
        "sourceHash": _source_hash(),
    }


def release_commit(*, protected: bool) -> str:
    configured = os.environ.get("KAJI_RELEASE_COMMIT")
    if protected and configured is None:
        raise RuntimeError("KAJI_RELEASE_COMMIT is required in protected mode")
    if configured is not None and COMMIT_PATTERN.fullmatch(configured) is None:
        raise RuntimeError(
            "KAJI_RELEASE_COMMIT must be exactly 40 lowercase hex characters"
        )
    checked_out = _checked_out_commit()
    if configured is not None and configured != checked_out:
        raise RuntimeError("KAJI_RELEASE_COMMIT does not match checked-out commit")
    return configured or checked_out


def performance_provenance(
    *,
    protected: bool,
    calibrating: bool = False,
    image_data_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "commit": release_commit(protected=protected),
        "fingerprint": fingerprint(
            protected=protected,
            calibrating=calibrating,
            image_data_path=image_data_path,
        ),
        "protected": protected,
    }


def _runtime_command(
    runtime: str,
    case: str,
    samples: int,
    warmups: int,
    installed: InstalledReleaseRuntime | None = None,
) -> list[str]:
    common = [
        "--case",
        case,
        "--samples",
        str(samples),
        "--warmups",
        str(warmups),
        "--seed",
        str(BENCHMARK_SEED),
        "--json",
    ]
    if runtime == "python":
        return [
            str(installed.python_executable)
            if installed is not None
            else sys.executable,
            str(ROOT / "kaji" / "benchmarks" / "python" / "runtime_benchmark.py"),
            *common,
        ]
    return [
        "bun",
        str(
            installed.typescript_benchmark
            if installed is not None
            else ROOT
            / "kaji"
            / "packages"
            / "typescript"
            / "benchmarks"
            / "runtime-benchmark.ts"
        ),
        *common,
    ]


def _context_sample_failure(stderr: bytes) -> tuple[str, int] | None:
    matches = [
        match
        for line in stderr.splitlines()
        if (match := SAMPLE_FAILURE_MARKER.fullmatch(line)) is not None
    ]
    if len(matches) != 1:
        return None
    status = int(matches[0].group(2))
    if status == 0 or not -(2**31) <= status < 2**31:
        return None
    return matches[0].group(1).decode("ascii"), status


def _run_case(
    runtime: str,
    case: str,
    samples: int,
    warmups: int,
    installed: InstalledReleaseRuntime | None = None,
) -> dict[str, Any]:
    try:
        completed = run_checked(
            _runtime_command(runtime, case, samples, warmups, installed),
            cwd=(
                installed.typescript_workdir
                if installed is not None and runtime == "typescript"
                else installed.root
                if installed is not None
                else ROOT
            ),
            budget=BENCHMARK_COMMAND_BUDGET,
            capture=True,
            env=installed.environment if installed is not None else None,
            check=False,
        )
    except CommandError as error:
        raise RuntimeError(f"{runtime} {case} failed") from error
    if completed.returncode != 0:
        if runtime == "python" and case == "context10kIterations5":
            diagnostic = _context_sample_failure(completed.stderr)
            if diagnostic is not None:
                variant, status = diagnostic
                raise RuntimeError(
                    f"{runtime} {case} failed: variant={variant} status={status}"
                )
        raise RuntimeError(f"{runtime} {case} failed")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{runtime} {case} emitted non-JSON stdout") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{runtime} {case} result is not an object")
    required = {
        "schemaVersion",
        "runtime",
        "case",
        "samples",
        "warmups",
        "seed",
        "sampleResults",
        "medianMs",
        "maxPeakMiB",
    }
    missing = sorted(required - result.keys())
    if missing:
        raise RuntimeError(f"{runtime} {case} is missing fields: {', '.join(missing)}")
    for field in ("schemaVersion", "samples", "warmups", "seed"):
        if type(result[field]) is not int:
            raise RuntimeError(f"{runtime} {case} {field} must be an integer")
    if result["schemaVersion"] != 1 or result["runtime"] != runtime:
        raise RuntimeError(f"{runtime} {case} has the wrong schema identity")
    if result["seed"] != BENCHMARK_SEED:
        raise RuntimeError(f"{runtime} {case} returned the wrong seed")
    resolved_package = result.get("resolvedPackage")
    if resolved_package is not None and (
        not isinstance(resolved_package, str) or not resolved_package
    ):
        raise RuntimeError(f"{runtime} {case} returned an invalid package path")
    if installed is not None:
        if resolved_package is None:
            raise RuntimeError(f"{runtime} {case} is missing fields: resolvedPackage")
        expected_package = (
            installed.resolved_python_package
            if runtime == "python"
            else installed.resolved_typescript_package
        )
        if Path(resolved_package).resolve() != expected_package:
            raise RuntimeError(f"{runtime} {case} resolved a different package")
    sample_results = result["sampleResults"]
    if not isinstance(sample_results, list):
        raise RuntimeError(f"{runtime} {case} sampleResults is not an array")
    if (
        result["case"] != case
        or result["samples"] != samples
        or result["warmups"] != warmups
        or len(sample_results) != samples
    ):
        raise RuntimeError(f"{runtime} {case} has inconsistent sample metadata")
    for index, sample in enumerate(sample_results, 1):
        if not isinstance(sample, dict):
            raise RuntimeError(f"{runtime} {case} sample {index} is not an object")
        if not {"durationMs", "peakMiB"} <= sample.keys():
            raise RuntimeError(f"{runtime} {case} sample is missing duration or RSS")
        warmup_runs = sample.get("warmupRuns")
        if (
            isinstance(warmup_runs, bool)
            or not isinstance(warmup_runs, int)
            or warmup_runs != warmups
        ):
            raise RuntimeError(
                f"{runtime} {case} sample {index} warmupRuns does not match"
            )
    _validate_result_aggregates(runtime, case, result)
    return result


def _validate_result_aggregates(
    runtime: str, case: str, result: dict[str, Any]
) -> None:
    label = f"{runtime} {case}"
    sample_results = result.get("sampleResults")
    if not isinstance(sample_results, list) or not sample_results:
        raise RuntimeError(f"{label} sampleResults must be a non-empty array")

    durations: list[float] = []
    peaks: list[float] = []
    for index, sample in enumerate(sample_results, 1):
        if not isinstance(sample, dict):
            raise RuntimeError(f"{label} sample {index} is not an object")
        for field, values in (("durationMs", durations), ("peakMiB", peaks)):
            value = sample.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise RuntimeError(
                    f"{label} sample {index} {field} must be finite and non-negative"
                )
            values.append(float(value))

    for field in ("medianMs", "maxPeakMiB"):
        value = result.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise RuntimeError(f"{label} {field} must be finite and non-negative")

    if result["medianMs"] != statistics.median(durations):
        raise RuntimeError(f"{label} medianMs does not match sample median")
    if result["maxPeakMiB"] != max(peaks):
        raise RuntimeError(f"{label} maxPeakMiB does not match sample maximum")


def _sample_failures(
    runtime: str,
    case: str,
    sample: dict[str, Any],
    budget: dict[str, Any],
    sample_number: int | None = None,
) -> list[str]:
    label = f"{runtime} {case}"
    if sample_number is not None:
        label += f" sample {sample_number}"
    failures: list[str] = []

    def number(field: str) -> float | None:
        value = sample.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            failures.append(f"{label} {field} is missing or non-numeric")
            return None
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0:
            failures.append(f"{label} {field} is non-finite or negative")
            return None
        return numeric

    def exact(field: str, expected: int | float) -> None:
        value = number(field)
        if value is not None and value != expected:
            failures.append(f"{label} {field} {value:g} != {expected}")

    def capped(field: str, maximum: int | float) -> None:
        value = number(field)
        if value is not None and value > maximum:
            failures.append(f"{label} {field} {value:g} exceeds {maximum}")

    def minimum(field: str, expected: int | float) -> None:
        value = number(field)
        if value is not None and value < expected:
            failures.append(f"{label} {field} {value:g} is below {expected}")

    number("durationMs")
    number("peakMiB")
    benchmark_repetitions = budget.get("benchmarkRepetitions")
    if benchmark_repetitions is not None and (
        type(benchmark_repetitions) is not dict
        or not set(benchmark_repetitions) <= {"python", "typescript"}
        or any(
            type(value) is not int or value < 1
            for value in benchmark_repetitions.values()
        )
    ):
        failures.append(f"{label} benchmarkRepetitions budget is invalid")
    else:
        expected_repetitions = (
            None
            if benchmark_repetitions is None
            else benchmark_repetitions.get(runtime)
        )
        if expected_repetitions is None:
            if "benchmarkRepetitions" in sample:
                failures.append(f"{label} benchmarkRepetitions is unexpected evidence")
        else:
            exact("benchmarkRepetitions", expected_repetitions)
    if case == "replay10k":
        expected = budget["expectedEvents"]
        exact("eventsApplied", expected)
        exact("cursor", expected)
    elif case == "crossSession100":
        exact("turns", 100)
        minimum("maxActive", budget["minOverlappingSessions"])
        capped("maxActive", budget["maxOverlappingSessions"])
        exact("coordinatorEntries", 0)
        exact("coordinatorWaiters", 0)
    elif case == "sameSession25":
        exact("turns", 25)
        exact("maxActive", budget["maxActive"])
        exact("coordinatorEntries", 0)
        exact("coordinatorWaiters", 0)
    elif case == "toolBatch100":
        exact("maxActive", budget["maxActive"])
        if runtime == "typescript":
            exact("batchRepetitions", budget["batchRepetitions"])
            exact("calls", budget["calls"])
            exact("completed", budget["calls"])
        else:
            exact("calls", 100)
            for field in ("batchRepetitions", "completed"):
                if field in sample:
                    failures.append(f"{label} {field} is TypeScript-only evidence")
        exact("stuckCalls", budget["stuckCalls"])
    elif case == "context10kIterations5":
        exact("historyEvents", 10_000)
        exact("fullHistoryScans", budget["maxFullHistoryScans"])
        exact("providerIterations", budget["maxProviderIterations"])
        exact("coldEvents", 10_000)
        exact("incrementalEvents", 21)
        exact("suffixCalls", 5)
        capped("copiedPayloadBytes", budget["maxCopiedPayloadBytes"])
        retained = number("retainedTurns")
        entries = number("turnIndexEntries")
        if retained is not None and retained <= 0:
            failures.append(f"{label} retainedTurns must be nonzero")
        elif retained is not None and entries is not None:
            ratio = entries / retained
            if ratio > budget["maxIndexEntriesPerRetainedTurn"]:
                failures.append(
                    f"{label} turnIndexEntries/retainedTurns {ratio:.3f} exceeds "
                    f"{budget['maxIndexEntriesPerRetainedTurn']}"
                )
        capped("sentinelEntries", budget["maxSentinelEntries"])
        total = number("totalIndexEntries")
        sentinel = number("sentinelEntries")
        if total is not None and entries is not None and sentinel is not None:
            if total != entries + sentinel:
                failures.append(
                    f"{label} totalIndexEntries does not equal turnIndexEntries + "
                    "sentinelEntries"
                )
        capped("maxVisitedTurnEntries", budget["maxSuffixTurnVisits"])
        capped("incrementalRssBytes", budget["maxIncrementalRssBytes"])
        capped("timerLeaks", budget["maxTimerLeaks"])
        capped("providerTaskLeaks", budget["maxProviderTaskLeaks"])
    elif case == "crossSessionCommit100":
        exact("sessions", 100)
        exact("commits", 100)
        minimum("overlappingSessions", budget["minOverlappingSessions"])
        exact("contiguousSessions", 100)
        capped("laneEntriesAfter", budget["maxLaneEntriesAfter"])
        capped("reservationEntriesAfter", budget["maxReservationEntriesAfter"])
    elif case == "streamDeltas10k":
        exact("characters", budget["expectedCharacters"])
        capped("deltaEvents", budget["maxDeltaEvents"])
        exact("inputFragments", budget["expectedCharacters"])
        delta_events = number("deltaEvents")
        delta_joins = number("deltaJoinOperations")
        if (
            delta_events is not None
            and delta_joins is not None
            and delta_events != delta_joins
        ):
            failures.append(f"{label} deltaJoinOperations must equal deltaEvents")
        exact("responseJoinOperations", 1)
        exact("providerTextMaxBytes", budget["maxProviderTextBytes"])
        exact("providerResponseMaxBytes", budget["maxProviderResponseBytes"])
        exact("completionEvents", 1)
        exact("completionEventsAfterFailure", 0)
        capped("timerLeaks", budget["maxTimerLeaks"])
        capped("providerTaskLeaks", budget["maxProviderTaskLeaks"])
    elif case == "toolArgDeltas10k":
        exact("argumentBytes", budget["maxArgumentBytes"])
        exact("responseMaxBytes", budget["maxResponseBytes"])
        exact("argumentFragments", 10_000)
        exact("rawFragments", 10_002)
        exact("fragmentJoins", budget["maxFragmentJoins"])
        exact("overLimitBytes", budget["maxArgumentBytes"] + 1)
        if sample.get("overLimitRejectedBeforeParse") is not True:
            failures.append(f"{label} overLimitRejectedBeforeParse is not true")
        capped("iteratorLeaks", budget["maxIteratorLeaks"])
        capped("parserLeaks", budget["maxParserLeaks"])
        capped("providerTaskLeaks", budget["maxProviderTaskLeaks"])
    else:
        failures.append(f"{label} has no semantic validator")
    return failures


def _case_failures(
    runtime: str,
    case: str,
    result: dict[str, Any],
    budgets: dict[str, Any],
    include_timing: bool,
) -> list[str]:
    _validate_result_aggregates(runtime, case, result)
    failures: list[str] = []
    for index, sample in enumerate(result.get("sampleResults", ()), 1):
        if not isinstance(sample, dict):
            failures.append(f"{runtime} {case} sample {index} is not an object")
            continue
        failures.extend(_sample_failures(runtime, case, sample, budgets[case], index))
    budget = budgets[case]
    if include_timing and "maxMedianMs" in budget:
        maximum = budget["maxMedianMs"]
        if result["medianMs"] > maximum:
            failures.append(
                f"{runtime} {case} median {result['medianMs']:.2f} ms exceeds {maximum} ms"
            )
    if include_timing and "maxPeakMiB" in budget:
        maximum = budget["maxPeakMiB"]
        if result["maxPeakMiB"] > maximum:
            failures.append(
                f"{runtime} {case} peak RSS {result['maxPeakMiB']:.2f} MiB exceeds "
                f"{maximum} MiB"
            )
    return failures


def _absolute_failures(
    runtime: str,
    results: dict[str, dict[str, Any]],
    budgets: dict[str, Any],
    *,
    include_timing: bool,
) -> list[str]:
    failures: list[str] = []
    for case in CASES:
        if case not in results:
            failures.append(f"{runtime} results are missing {case}")
            continue
        failures.extend(
            _case_failures(runtime, case, results[case], budgets, include_timing)
        )
    return failures


def _include_timing(mode: str) -> bool:
    return mode == "full"


def _baseline_fingerprint(baseline: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(baseline, dict):
        raise RuntimeError("baseline must be an object")
    runner = baseline.get("runner")
    versions = baseline.get("versions")
    dependency_lock_hash = baseline.get("dependencyLockHash")
    source_hash = baseline.get("sourceHash")
    if not isinstance(runner, dict):
        raise RuntimeError("baseline runner must be an object")
    runner = validate_retained_runner(runner)
    if not isinstance(versions, dict):
        raise RuntimeError("baseline versions must be an object")
    if not isinstance(dependency_lock_hash, str):
        raise RuntimeError("baseline dependencyLockHash must be a string")
    if not isinstance(source_hash, str) or HASH_PATTERN.fullmatch(source_hash) is None:
        raise RuntimeError("baseline sourceHash must be 64 lowercase hex characters")
    return {
        "runner": runner,
        "versions": versions,
        "dependencyLockHash": dependency_lock_hash,
        "sourceHash": source_hash,
    }


def _validate_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    """Validate applicability, not release-artifact identity.

    Calibration commit and artifact fields are retained provenance for the
    measured artifact set A. A later candidate B may use that baseline only
    when its benchmark source, dependency locks, toolchain, and observed hosted
    image fingerprint match. Full and soak receipts bind B's own artifact hashes.
    """
    if not isinstance(baseline, dict):
        raise RuntimeError("baseline must be an object")
    if baseline.get("schemaVersion") != 1 or baseline.get("status") != "calibrated":
        raise RuntimeError("beta baseline is uncalibrated")
    calibration_commit = baseline.get("calibrationCommit")
    if (
        not isinstance(calibration_commit, str)
        or COMMIT_PATTERN.fullmatch(calibration_commit) is None
    ):
        raise RuntimeError(
            "baseline calibrationCommit must be exactly 40 lowercase hex characters"
        )
    baseline_fingerprint = _baseline_fingerprint(baseline)
    if baseline_fingerprint["sourceHash"] != current.get("sourceHash"):
        raise RuntimeError("benchmark source hash does not match the baseline")
    if baseline_fingerprint != current:
        raise RuntimeError("benchmark runner fingerprint does not match the baseline")
    evidence: dict[str, dict[str, Any]] = {}
    for field in ("medians", "rawSamples", "maxPeakMiB", "rawPeakMiB"):
        value = baseline.get(field)
        if not isinstance(value, dict):
            raise RuntimeError(f"baseline {field} must be an object")
        evidence[field] = value
    for runtime in ("python", "typescript"):
        runtime_evidence: dict[str, dict[str, Any]] = {}
        for field, values in evidence.items():
            value = values.get(runtime)
            if not isinstance(value, dict):
                raise RuntimeError(f"baseline {field}.{runtime} must be an object")
            runtime_evidence[field] = value
        medians = runtime_evidence["medians"]
        raw = runtime_evidence["rawSamples"]
        peak = runtime_evidence["maxPeakMiB"]
        raw_peak = runtime_evidence["rawPeakMiB"]
        if set(medians) != set(CASES) or set(raw) != set(CASES):
            raise RuntimeError(f"baseline is missing {runtime} cases")
        if set(peak) != set(CASES) or set(raw_peak) != set(CASES):
            raise RuntimeError(f"baseline is missing {runtime} RSS cases")
        for case in CASES:
            if not isinstance(raw[case], list):
                raise RuntimeError(
                    f"baseline rawSamples.{runtime}.{case} must be an array"
                )
            if not isinstance(raw_peak[case], list):
                raise RuntimeError(
                    f"baseline rawPeakMiB.{runtime}.{case} must be an array"
                )
        if any(len(raw[case]) != 5 for case in CASES):
            raise RuntimeError(
                f"baseline {runtime} raw samples must contain five values"
            )
        if any(len(raw_peak[case]) != 5 for case in CASES):
            raise RuntimeError(
                f"baseline {runtime} raw RSS samples must contain five values"
            )
        numeric_evidence = [*medians.values(), *peak.values()]
        numeric_evidence.extend(value for values in raw.values() for value in values)
        numeric_evidence.extend(
            value for values in raw_peak.values() for value in values
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            for value in numeric_evidence
        ):
            raise RuntimeError(
                f"baseline {runtime} timing and RSS values must be finite "
                "non-negative numbers"
            )
        if any(peak[case] != max(raw_peak[case]) for case in CASES):
            raise RuntimeError(
                f"baseline {runtime} RSS aggregate does not match raw samples"
            )
        if any(medians[case] != statistics.median(raw[case]) for case in CASES):
            raise RuntimeError(
                f"baseline {runtime} duration median does not match raw samples"
            )


def _regression_failures(
    results: dict[str, dict[str, dict[str, Any]]],
    baseline: dict[str, Any],
    percent: float,
) -> list[str]:
    failures: list[str] = []
    multiplier = 1 + percent / 100
    for runtime in ("python", "typescript"):
        for case in CASES:
            _validate_result_aggregates(runtime, case, results[runtime][case])
            measured = results[runtime][case]["medianMs"]
            maximum = baseline["medians"][runtime][case] * multiplier
            if measured > maximum:
                failures.append(
                    f"{runtime} {case} median {measured:.2f} ms exceeds "
                    f"{percent}% regression limit {maximum:.2f} ms"
                )
            measured_peak = results[runtime][case]["maxPeakMiB"]
            maximum_peak = baseline["maxPeakMiB"][runtime][case] * multiplier
            if measured_peak > maximum_peak:
                failures.append(
                    f"{runtime} {case} peak RSS {measured_peak:.2f} MiB exceeds "
                    f"{percent}% regression limit {maximum_peak:.2f} MiB"
                )
    return failures


def _require_case_coverage(
    results: dict[str, dict[str, dict[str, Any]]],
) -> None:
    for runtime in ("python", "typescript"):
        cases = results.get(runtime, {})
        missing = sorted(set(CASES) - set(cases))
        extra = sorted(set(cases) - set(CASES))
        if missing:
            raise RuntimeError(f"missing {runtime} cases: {', '.join(missing)}")
        if extra:
            raise RuntimeError(f"unexpected {runtime} cases: {', '.join(extra)}")


def _candidate_baseline(
    results: dict[str, dict[str, dict[str, Any]]],
    current: dict[str, Any],
    artifact_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_case_coverage(results)
    for runtime in ("python", "typescript"):
        for case in CASES:
            _validate_result_aggregates(runtime, case, results[runtime][case])
            if len(results[runtime][case].get("sampleResults", ())) != 5:
                raise RuntimeError(
                    f"candidate {runtime} {case} must contain five measured samples"
                )
    return {
        "schemaVersion": 1,
        "status": "calibrated",
        **current,
        **(artifact_identity or {}),
        "calibrationCommit": _commit(),
        "calibratedAt": datetime.now(timezone.utc).isoformat(),
        "medians": {
            runtime: {case: results[runtime][case]["medianMs"] for case in CASES}
            for runtime in ("python", "typescript")
        },
        "rawSamples": {
            runtime: {
                case: [
                    sample["durationMs"]
                    for sample in results[runtime][case]["sampleResults"]
                ]
                for case in CASES
            }
            for runtime in ("python", "typescript")
        },
        "maxPeakMiB": {
            runtime: {
                case: max(
                    sample["peakMiB"]
                    for sample in results[runtime][case]["sampleResults"]
                )
                for case in CASES
            }
            for runtime in ("python", "typescript")
        },
        "rawPeakMiB": {
            runtime: {
                case: [
                    sample["peakMiB"]
                    for sample in results[runtime][case]["sampleResults"]
                ]
                for case in CASES
            }
            for runtime in ("python", "typescript")
        },
    }


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("quick", "full", "calibrate"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-baseline", type=Path)
    parser.add_argument("--protected", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--expected-commit")
    return parser.parse_args()


def _installed_context(args: argparse.Namespace):
    protected = getattr(args, "protected", False)
    required = protected or args.mode in {"full", "calibrate"}
    artifacts_dir = getattr(args, "artifacts_dir", None)
    expected_commit = getattr(args, "expected_commit", None)
    if not required:
        return nullcontext(None)
    if artifacts_dir is None:
        raise RuntimeError(
            "--artifacts-dir is required for protected/full/calibrate mode"
        )
    if (
        not isinstance(expected_commit, str)
        or COMMIT_PATTERN.fullmatch(expected_commit) is None
    ):
        raise RuntimeError(
            "--expected-commit must be exactly 40 lowercase hex characters"
        )
    if os.environ.get("KAJI_RELEASE_COMMIT") != expected_commit:
        raise RuntimeError("--expected-commit must equal KAJI_RELEASE_COMMIT")
    return installed_release_runtime(artifacts_dir, expected_commit=expected_commit)


def main() -> int:
    args = _parse_args()
    budgets = json.loads(BUDGETS_PATH.read_text())
    failures: list[str] = []
    protected = getattr(args, "protected", False)
    calibrating = args.mode == "calibrate"
    try:
        provenance = performance_provenance(
            protected=protected,
            calibrating=calibrating,
        )
    except (CommandError, OSError, RuntimeError) as error:
        provenance = {
            "commit": os.environ.get("KAJI_RELEASE_COMMIT"),
            "fingerprint": {},
            "protected": protected,
        }
        failures.append(str(error))
    fingerprint_value = provenance["fingerprint"]
    current: dict[str, Any] = (
        fingerprint_value if isinstance(fingerprint_value, dict) else {}
    )
    baseline: dict[str, Any] | None = None
    baseline_fingerprint: dict[str, Any] | None = None
    installed_required = protected or args.mode in {"full", "calibrate"}
    artifact_identity: dict[str, Any] = (
        {
            "releaseManifestSha256": None,
            "artifacts": {},
            "resolvedPackages": {},
            "typescriptConsumerLock": {
                "templateSha256": None,
                "renderedSha256": None,
            },
        }
        if installed_required
        else {}
    )

    if args.mode == "calibrate":
        if os.environ.get("KAJI_BENCHMARK_CALIBRATION") != "1":
            failures.append("calibration requires KAJI_BENCHMARK_CALIBRATION=1")
        if args.candidate_baseline is None:
            failures.append("calibration requires --candidate-baseline")
    elif args.mode == "full":
        try:
            loaded_baseline = json.loads(BASELINE_PATH.read_text())
            if not isinstance(loaded_baseline, dict):
                raise RuntimeError("baseline must be an object")
            baseline = loaded_baseline
            _validate_baseline(baseline, current)
            baseline_fingerprint = _baseline_fingerprint(baseline)
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as error:
            failures.append(f"beta baseline is invalid: {error}")

    samples, warmups = (1, 1) if args.mode == "quick" else (5, 2)
    results: dict[str, dict[str, dict[str, Any]]] = {
        "python": {},
        "typescript": {},
    }
    if not failures:
        try:
            context = _installed_context(args)
            with context as installed:
                if installed is not None:
                    identity = installed.identity()
                    if identity["commit"] != provenance["commit"]:
                        raise RuntimeError(
                            "installed artifact commit differs from benchmark provenance"
                        )
                    artifact_identity = {
                        key: identity[key]
                        for key in (
                            "releaseManifestSha256",
                            "artifacts",
                            "resolvedPackages",
                            "typescriptConsumerLock",
                        )
                    }
                for runtime in results:
                    for case in CASES:
                        results[runtime][case] = _run_case(
                            runtime, case, samples, warmups, installed
                        )
        except SystemExit as error:
            failures.append(str(error))
        except (OSError, CommandError, RuntimeError) as error:
            failures.append(str(error))

    if all(results.values()) and all(
        len(cases) == len(CASES) for cases in results.values()
    ):
        for runtime in results:
            failures.extend(
                _absolute_failures(
                    runtime,
                    results[runtime],
                    budgets,
                    include_timing=_include_timing(args.mode),
                )
            )
        if args.mode == "full" and baseline is not None:
            failures.extend(
                _regression_failures(
                    results, baseline, float(budgets["regressionPercent"])
                )
            )

    report = {
        "schemaVersion": 1,
        "mode": args.mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        **provenance,
        "baselineFingerprint": baseline_fingerprint,
        **artifact_identity,
        "results": results,
        "failures": failures,
        "passed": not failures,
    }
    _write(args.output, report)

    if args.mode == "calibrate" and not failures:
        assert args.candidate_baseline is not None
        _write(
            args.candidate_baseline,
            _candidate_baseline(
                results,
                current,
                {"commit": provenance["commit"], **artifact_identity},
            ),
        )
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
