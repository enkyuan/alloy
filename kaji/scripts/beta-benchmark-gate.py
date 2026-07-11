#!/usr/bin/env python3
"""Run and validate the cross-runtime production-beta benchmark programs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CASES = ("replay10k", "crossSession100", "sameSession25", "toolBatch100")
BUDGETS_PATH = ROOT / "kaji" / "benchmarks" / "beta-budgets.json"
BASELINE_PATH = ROOT / "kaji" / "benchmarks" / "beta-baseline.json"


def _command_version(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _ram_mib() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return 0
    return pages * page_size // (1024 * 1024)


def _lock_hash() -> str:
    digest = hashlib.sha256()
    for relative in ("bun.lock", "kaji/sdk/uv.lock"):
        path = ROOT / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _commit() -> str:
    configured = os.environ.get("GITHUB_SHA")
    if configured:
        return configured
    return _command_version(["git", "rev-parse", "HEAD"])


def fingerprint() -> dict[str, Any]:
    return {
        "runner": {
            "imageDigest": os.environ.get("KAJI_BENCHMARK_RUNNER_IMAGE_DIGEST")
            or "local-unpinned",
            "os": platform.system(),
            "arch": platform.machine(),
            "cpuModel": _cpu_model(),
            "cpuCount": os.cpu_count(),
            "ramMiB": _ram_mib(),
        },
        "versions": {
            "python": platform.python_version(),
            "node": _command_version(["node", "--version"]),
            "bun": _command_version(["bun", "--version"]),
        },
        "dependencyLockHash": _lock_hash(),
    }


def _runtime_command(runtime: str, case: str, samples: int, warmups: int) -> list[str]:
    common = [
        "--case",
        case,
        "--samples",
        str(samples),
        "--warmups",
        str(warmups),
        "--seed",
        "13",
        "--json",
    ]
    if runtime == "python":
        return [
            sys.executable,
            str(ROOT / "kaji" / "sdk" / "benchmarks" / "runtime_benchmark.py"),
            *common,
        ]
    return [
        "bun",
        str(ROOT / "kaji" / "ts" / "benchmarks" / "runtime-benchmark.ts"),
        *common,
    ]


def _run_case(runtime: str, case: str, samples: int, warmups: int) -> dict[str, Any]:
    completed = subprocess.run(
        _runtime_command(runtime, case, samples, warmups),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{runtime} {case} emitted non-JSON stdout") from error
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
    if result["schemaVersion"] != 1 or result["runtime"] != runtime:
        raise RuntimeError(f"{runtime} {case} has the wrong schema identity")
    if result["case"] != case or len(result["sampleResults"]) != samples:
        raise RuntimeError(f"{runtime} {case} has inconsistent sample metadata")
    for sample in result["sampleResults"]:
        if not {"durationMs", "peakMiB"} <= sample.keys():
            raise RuntimeError(f"{runtime} {case} sample is missing duration or RSS")
    return result


def _absolute_failures(
    runtime: str,
    results: dict[str, dict[str, Any]],
    budgets: dict[str, Any],
    *,
    include_timing: bool,
) -> list[str]:
    failures: list[str] = []
    replay = results["replay10k"]
    for sample in replay["sampleResults"]:
        if sample.get("eventsApplied") != 10_000 or sample.get("cursor") != 10_000:
            failures.append(f"{runtime} replay10k did not apply exactly 10,000 events")
            break
    if replay["maxPeakMiB"] > budgets["replay10k"]["maxPeakMiB"]:
        failures.append(
            f"{runtime} replay10k peak RSS {replay['maxPeakMiB']:.2f} MiB exceeds "
            f"{budgets['replay10k']['maxPeakMiB']} MiB"
        )
    for case in ("sameSession25", "toolBatch100"):
        expected = budgets[case]["maxActive"]
        if results[case].get("maxActive") != expected:
            failures.append(
                f"{runtime} {case} maxActive {results[case].get('maxActive')} != {expected}"
            )
    cross = results["crossSession100"]
    if not 2 <= cross.get("maxActive", 0) <= 100:
        failures.append(
            f"{runtime} crossSession100 did not demonstrate bounded session overlap"
        )
    for case in ("crossSession100", "sameSession25"):
        for sample in results[case]["sampleResults"]:
            if (
                sample.get("coordinatorEntries") != 0
                or sample.get("coordinatorWaiters") != 0
            ):
                failures.append(f"{runtime} {case} leaked coordinator state")
                break
    if any(
        sample.get("stuckCalls") != 0
        for sample in results["toolBatch100"]["sampleResults"]
    ):
        failures.append(f"{runtime} toolBatch100 leaked tool handlers")
    if include_timing:
        for case in ("replay10k", "crossSession100"):
            maximum = budgets[case]["maxMedianMs"]
            if results[case]["medianMs"] > maximum:
                failures.append(
                    f"{runtime} {case} median {results[case]['medianMs']:.2f} ms exceeds "
                    f"{maximum} ms"
                )
    return failures


def _baseline_fingerprint(baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "runner": baseline["runner"],
        "versions": baseline["versions"],
        "dependencyLockHash": baseline["dependencyLockHash"],
    }


def _validate_baseline(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    if baseline.get("schemaVersion") != 1 or baseline.get("status") != "calibrated":
        raise RuntimeError("beta baseline is uncalibrated")
    if _baseline_fingerprint(baseline) != current:
        raise RuntimeError("benchmark runner fingerprint does not match the baseline")
    for runtime in ("python", "typescript"):
        medians = baseline.get("medians", {}).get(runtime, {})
        raw = baseline.get("rawSamples", {}).get(runtime, {})
        if set(medians) != set(CASES) or set(raw) != set(CASES):
            raise RuntimeError(f"baseline is missing {runtime} cases")
        if any(len(raw[case]) != 5 for case in CASES):
            raise RuntimeError(
                f"baseline {runtime} raw samples must contain five values"
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
            measured = results[runtime][case]["medianMs"]
            maximum = baseline["medians"][runtime][case] * multiplier
            if measured > maximum:
                failures.append(
                    f"{runtime} {case} median {measured:.2f} ms exceeds "
                    f"{percent}% regression limit {maximum:.2f} ms"
                )
    return failures


def _candidate_baseline(
    results: dict[str, dict[str, dict[str, Any]]], current: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "calibrated",
        **current,
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
    }


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("quick", "full", "calibrate"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-baseline", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    budgets = json.loads(BUDGETS_PATH.read_text())
    baseline = json.loads(BASELINE_PATH.read_text())
    current = fingerprint()
    failures: list[str] = []

    if args.mode == "calibrate":
        if os.environ.get("KAJI_BENCHMARK_CALIBRATION") != "1":
            failures.append("calibration requires KAJI_BENCHMARK_CALIBRATION=1")
        if os.environ.get("KAJI_BENCHMARK_PINNED_RUNNER") != "1":
            failures.append("calibration requires KAJI_BENCHMARK_PINNED_RUNNER=1")
        if current["runner"]["imageDigest"] == "local-unpinned":
            failures.append("calibration requires a pinned runner image digest")
        if args.candidate_baseline is None:
            failures.append("calibration requires --candidate-baseline")
    elif args.mode == "full":
        try:
            _validate_baseline(baseline, current)
        except (KeyError, RuntimeError) as error:
            failures.append(str(error))

    samples, warmups = (1, 1) if args.mode == "quick" else (5, 2)
    results: dict[str, dict[str, dict[str, Any]]] = {
        "python": {},
        "typescript": {},
    }
    if not failures:
        try:
            for runtime in results:
                for case in CASES:
                    results[runtime][case] = _run_case(runtime, case, samples, warmups)
        except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
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
                    include_timing=args.mode != "quick",
                )
            )
        if args.mode == "full":
            failures.extend(
                _regression_failures(
                    results, baseline, float(budgets["regressionPercent"])
                )
            )

    report = {
        "schemaVersion": 1,
        "mode": args.mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fingerprint": current,
        "results": results,
        "failures": failures,
        "passed": not failures,
    }
    _write(args.output, report)

    if args.mode == "calibrate" and not failures:
        assert args.candidate_baseline is not None
        _write(args.candidate_baseline, _candidate_baseline(results, current))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
