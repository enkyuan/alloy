#!/usr/bin/env python3
"""Measure one protected, matched Kaji beta benchmark replica."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import math
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import statistics
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_platform import runner_fingerprint, validate_retained_runner
from beta_benchmark_gate import (
    BENCHMARK_SEED,
    BUDGETS_PATH,
    CASES,
    _case_failures,
    _command_version,
    _lock_hash,
    _run_case,
)
from installed_release_runtime import (
    InstalledReleaseRuntime,
    installed_release_runtime,
)
from verify_release_artifacts import BETA2_REFERENCE_RELEASE_CONTRACT


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATH = ROOT / "kaji" / "benchmarks" / "beta-reference.json"
RUNTIMES = ("python", "typescript")
SUBJECTS = ("reference", "candidate")
SAMPLES = 5
WARMUPS = 2
THRESHOLD = 1.2
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
PROTOCOL_INPUTS = (
    Path(".github/actions/setup-bun-cache/action.yml"),
    Path(".github/actions/setup-python-uv/action.yml"),
    Path(".github/workflows/kaji.performance.yml"),
    Path("kaji/benchmarks/python/runtime_benchmark.py"),
    Path("kaji/packages/ts/benchmarks/runtime-benchmark.ts"),
    Path("kaji/benchmarks/beta-budgets.json"),
    Path("kaji/scripts/paired_benchmark.py"),
    Path("kaji/scripts/aggregate_benchmarks.py"),
    Path("kaji/scripts/beta_benchmark_gate.py"),
    Path("kaji/scripts/benchmark_platform.py"),
    Path("kaji/scripts/installed_release_runtime.py"),
    Path("kaji/scripts/process_runner.py"),
    Path("kaji/scripts/verify_release_artifacts.py"),
    Path("kaji/scripts/installed-typescript-runtime/package.core.json"),
    Path("kaji/scripts/installed-typescript-runtime/package-lock.core.json"),
)
IDENTITY_FILES = {
    "pythonWheel": "kaji-0.2.0b1-py3-none-any.whl",
    "pythonSdist": "kaji-0.2.0b1.tar.gz",
    "typescript": "kaji-0.2.0-beta.11.tgz",
}
REFERENCE_IDENTITY_FILES = {
    "pythonWheel": "kaji-0.2.0b1-py3-none-any.whl",
    "pythonSdist": "kaji-0.2.0b1.tar.gz",
    "typescript": "kaji-0.2.0-beta.2.tgz",
}
REPORT_KEYS = {
    "schemaVersion",
    "kind",
    "generatedAt",
    "protected",
    "protocolHash",
    "replica",
    "threshold",
    "runnerEvidence",
    "referenceRecordSha256",
    "reference",
    "candidate",
    "referenceReceiptSha256",
    "candidateReceiptSha256",
    "cases",
    "referenceFailures",
    "candidateFailures",
    "hardFailures",
    "outcome",
    "passed",
    "reportReceiptSha256",
}


def _reject_constant(_value: str) -> None:
    raise RuntimeError("JSON contains a non-finite number")


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise RuntimeError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid JSON document: {path.name}") from error


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protocol_hash(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for relative in sorted(PROTOCOL_INPUTS, key=lambda path: path.as_posix()):
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"benchmark protocol input is missing: {relative}")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _validate_utc_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError(f"{label} must be a UTC timestamp") from error
    if parsed.tzinfo != timezone.utc:
        raise RuntimeError(f"{label} must be a UTC timestamp")
    return value


def _validate_identity(
    value: Any,
    label: str,
    expected_files: dict[str, str] = IDENTITY_FILES,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "commit",
        "releaseManifestSha256",
        "artifacts",
    }:
        raise RuntimeError(f"{label} identity has the wrong shape")
    commit = value["commit"]
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise RuntimeError(f"{label} commit is invalid")
    manifest_hash = _validate_hash(
        value["releaseManifestSha256"], f"{label} manifest hash"
    )
    artifacts = value["artifacts"]
    if type(artifacts) is not dict or set(artifacts) != set(expected_files):
        raise RuntimeError(f"{label} artifacts have the wrong shape")
    validated: dict[str, dict[str, str]] = {}
    for artifact, expected_file in expected_files.items():
        entry = artifacts[artifact]
        if (
            type(entry) is not dict
            or set(entry) != {"file", "sha256"}
            or entry.get("file") != expected_file
        ):
            raise RuntimeError(f"{label} {artifact} identity is invalid")
        validated[artifact] = {
            "file": expected_file,
            "sha256": _validate_hash(entry["sha256"], f"{label} {artifact} hash"),
        }
    return {
        "commit": commit,
        "releaseManifestSha256": manifest_hash,
        "artifacts": validated,
    }


def _load_reference(path: Path = REFERENCE_PATH) -> dict[str, Any]:
    value = _load_json(path)
    if type(value) is not dict or set(value) != {
        "schemaVersion",
        "commit",
        "releaseManifestSha256",
        "artifacts",
        "dependencyLockHash",
        "githubArtifact",
    }:
        raise RuntimeError("benchmark reference has the wrong shape")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise RuntimeError("benchmark reference schema is unsupported")
    _validate_identity(
        {
            "commit": value["commit"],
            "releaseManifestSha256": value["releaseManifestSha256"],
            "artifacts": value["artifacts"],
        },
        "reference",
        REFERENCE_IDENTITY_FILES,
    )
    _validate_hash(value["dependencyLockHash"], "reference dependency lock hash")
    github = value["githubArtifact"]
    if (
        type(github) is not dict
        or set(github) != {"runId", "artifactId", "name", "digest", "expiresAt"}
        or type(github["runId"]) is not int
        or type(github["artifactId"]) is not int
        or github["runId"] <= 0
        or github["artifactId"] <= 0
        or not isinstance(github["name"], str)
        or not github["name"]
        or not isinstance(github["digest"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", github["digest"]) is None
    ):
        raise RuntimeError("benchmark reference GitHub receipt is invalid")
    _validate_utc_timestamp(github["expiresAt"], "reference artifact expiry")
    return value


def _reference_identity(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "commit": reference["commit"],
        "releaseManifestSha256": reference["releaseManifestSha256"],
        "artifacts": reference["artifacts"],
    }


def _installed_identity(
    installed: InstalledReleaseRuntime,
    expected_files: dict[str, str] = IDENTITY_FILES,
) -> dict[str, Any]:
    release = installed.release
    return _validate_identity(
        {
            "commit": release.commit,
            "releaseManifestSha256": release.manifest_sha256,
            "artifacts": {
                "pythonWheel": {
                    "file": release.python_wheel.name,
                    "sha256": release.artifact_sha256[release.python_wheel.name],
                },
                "pythonSdist": {
                    "file": release.python_sdist.name,
                    "sha256": release.artifact_sha256[release.python_sdist.name],
                },
                "typescript": {
                    "file": release.npm_tarball.name,
                    "sha256": release.artifact_sha256[release.npm_tarball.name],
                },
            },
        },
        "installed",
        expected_files,
    )


def _subject_order(replica: int, case: str, sample: int) -> tuple[str, str]:
    if replica not in (1, 2, 3):
        raise RuntimeError("replica must be 1, 2, or 3")
    try:
        case_index = CASES.index(case)
    except ValueError as error:
        raise RuntimeError(f"unknown benchmark case: {case}") from error
    if sample not in range(1, SAMPLES + 1):
        raise RuntimeError("sample must be between 1 and 5")
    if (replica + case_index + sample) % 2 == 0:
        return ("candidate", "reference")
    return ("reference", "candidate")


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
        or (positive and value == 0)
    ):
        qualifier = "positive" if positive else "non-negative"
        raise RuntimeError(f"{label} must be a finite {qualifier} number")
    return float(value)


def _subject_result(
    runtime: str, case: str, samples: list[dict[str, Any]]
) -> dict[str, Any]:
    durations = [
        _number(sample.get("durationMs"), f"{runtime} {case} duration")
        for sample in samples
    ]
    peaks = [
        _number(sample.get("peakMiB"), f"{runtime} {case} RSS") for sample in samples
    ]
    return {
        "schemaVersion": 1,
        "runtime": runtime,
        "case": case,
        "samples": SAMPLES,
        "warmups": WARMUPS,
        "seed": BENCHMARK_SEED,
        "sampleResults": samples,
        "medianMs": statistics.median(durations),
        "maxPeakMiB": max(peaks),
    }


def _case_evidence(
    runtime: str,
    case: str,
    pairs: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[str]]:
    if runtime not in RUNTIMES or case not in CASES:
        raise RuntimeError("paired benchmark case identity is invalid")
    if not isinstance(pairs, list) or len(pairs) != SAMPLES:
        raise RuntimeError(f"{runtime} {case} must contain five paired samples")
    retained: list[dict[str, Any]] = []
    reference_samples: list[dict[str, Any]] = []
    candidate_samples: list[dict[str, Any]] = []
    duration_ratios: list[float] = []
    rss_ratios: list[float] = []
    base_keys = {"sample", "order", "reference", "candidate"}
    evidence_keys = base_keys | {"durationRatio", "rssRatio"}
    for expected_sample, pair in enumerate(pairs, 1):
        if type(pair) is not dict or set(pair) not in (base_keys, evidence_keys):
            raise RuntimeError(f"{runtime} {case} pair has the wrong shape")
        if type(pair["sample"]) is not int or pair["sample"] != expected_sample:
            raise RuntimeError(f"{runtime} {case} sample ordering is invalid")
        order = pair["order"]
        if type(order) is not list or len(order) != 2 or set(order) != set(SUBJECTS):
            raise RuntimeError(f"{runtime} {case} subject order is invalid")
        reference_sample = pair["reference"]
        candidate_sample = pair["candidate"]
        if type(reference_sample) is not dict or type(candidate_sample) is not dict:
            raise RuntimeError(f"{runtime} {case} paired samples must be objects")
        for subject, sample_value in (
            ("reference", reference_sample),
            ("candidate", candidate_sample),
        ):
            if (
                type(sample_value.get("warmupRuns")) is not int
                or sample_value["warmupRuns"] != WARMUPS
            ):
                raise RuntimeError(
                    f"{runtime} {case} {subject} warmupRuns must equal {WARMUPS}"
                )
        reference_duration = _number(
            reference_sample.get("durationMs"),
            f"{runtime} {case} reference duration",
            positive=True,
        )
        reference_rss = _number(
            reference_sample.get("peakMiB"),
            f"{runtime} {case} reference RSS",
            positive=True,
        )
        candidate_duration = _number(
            candidate_sample.get("durationMs"),
            f"{runtime} {case} candidate duration",
            positive=True,
        )
        candidate_rss = _number(
            candidate_sample.get("peakMiB"),
            f"{runtime} {case} candidate RSS",
            positive=True,
        )
        duration_ratio = candidate_duration / reference_duration
        rss_ratio = candidate_rss / reference_rss
        retained.append(
            {
                "sample": expected_sample,
                "order": order,
                "reference": reference_sample,
                "candidate": candidate_sample,
                "durationRatio": duration_ratio,
                "rssRatio": rss_ratio,
            }
        )
        reference_samples.append(reference_sample)
        candidate_samples.append(candidate_sample)
        duration_ratios.append(duration_ratio)
        rss_ratios.append(rss_ratio)

    budgets = _load_json(BUDGETS_PATH)
    if type(budgets) is not dict:
        raise RuntimeError("benchmark budgets must be an object")
    reference_result = _subject_result(runtime, case, reference_samples)
    candidate_result = _subject_result(runtime, case, candidate_samples)
    reference_failures = [
        f"reference: {failure}"
        for failure in _case_failures(
            runtime, case, reference_result, budgets, include_timing=True
        )
    ]
    candidate_failures = [
        f"candidate: {failure}"
        for failure in _case_failures(
            runtime, case, candidate_result, budgets, include_timing=True
        )
    ]
    duration_ratio = statistics.median(duration_ratios)
    max_rss_ratio = max(rss_ratios)
    if max_rss_ratio > THRESHOLD:
        candidate_failures.append(
            f"candidate: {runtime} {case} peak RSS ratio "
            f"{max_rss_ratio:.6f} exceeds {THRESHOLD:.2f}"
        )
    return (
        {
            "pairs": retained,
            "durationRatio": duration_ratio,
            "maxRssRatio": max_rss_ratio,
            "durationCrossed": duration_ratio > THRESHOLD,
            "rssCrossed": max_rss_ratio > THRESHOLD,
        },
        reference_failures,
        candidate_failures,
    )


def _runner_evidence(
    *, protected: bool, image_data_path: Path | None
) -> dict[str, Any]:
    return {
        "runner": runner_fingerprint(
            protected=protected,
            calibrating=False,
            image_data_path=image_data_path,
        ),
        "versions": {
            "python": platform.python_version(),
            "node": _command_version(["node", "--version"]),
            "bun": _command_version(["bun", "--version"]),
        },
        "dependencyLockHash": _lock_hash(),
        "invocation": _invocation_evidence(protected=protected),
    }


def _invocation_evidence(*, protected: bool) -> dict[str, Any]:
    if not protected:
        return {
            "runId": 0,
            "runAttempt": 0,
            "job": "local",
            "runnerName": "local",
            "workflowRef": "local",
            "workflowSha": "0" * 40,
        }

    def positive_integer(name: str) -> int:
        value = os.environ.get(name)
        if value is None or re.fullmatch(r"[1-9][0-9]*", value) is None:
            raise RuntimeError(f"protected benchmark requires {name}")
        return int(value)

    def required(name: str) -> str:
        value = os.environ.get(name)
        if value is None or not value:
            raise RuntimeError(f"protected benchmark requires {name}")
        return value

    workflow_sha = required("GITHUB_WORKFLOW_SHA")
    if COMMIT_PATTERN.fullmatch(workflow_sha) is None:
        raise RuntimeError("protected benchmark GITHUB_WORKFLOW_SHA is invalid")
    return {
        "runId": positive_integer("GITHUB_RUN_ID"),
        "runAttempt": positive_integer("GITHUB_RUN_ATTEMPT"),
        "job": required("GITHUB_JOB"),
        "runnerName": required("RUNNER_NAME"),
        "workflowRef": required("GITHUB_WORKFLOW_REF"),
        "workflowSha": workflow_sha,
    }


def _validate_invocation(value: Any) -> dict[str, Any]:
    keys = {
        "runId",
        "runAttempt",
        "job",
        "runnerName",
        "workflowRef",
        "workflowSha",
    }
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError("runner invocation evidence has the wrong shape")
    if (
        type(value["runId"]) is not int
        or value["runId"] <= 0
        or type(value["runAttempt"]) is not int
        or value["runAttempt"] <= 0
        or any(
            not isinstance(value[field], str) or not value[field]
            for field in ("job", "runnerName", "workflowRef")
        )
        or not isinstance(value["workflowSha"], str)
        or COMMIT_PATTERN.fullmatch(value["workflowSha"]) is None
    ):
        raise RuntimeError("runner invocation evidence is invalid")
    return {key: value[key] for key in keys}


def _validate_runner_evidence(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "runner",
        "versions",
        "dependencyLockHash",
        "invocation",
    }:
        raise RuntimeError("runner evidence has the wrong shape")
    runner = validate_retained_runner(value["runner"])
    versions = value["versions"]
    if (
        type(versions) is not dict
        or set(versions) != {"python", "node", "bun"}
        or any(not isinstance(item, str) or not item for item in versions.values())
    ):
        raise RuntimeError("runner versions are invalid")
    return {
        "runner": runner,
        "versions": dict(versions),
        "dependencyLockHash": _validate_hash(
            value["dependencyLockHash"], "dependency lock hash"
        ),
        "invocation": _validate_invocation(value["invocation"]),
    }


def _measure_replica(
    *,
    reference_artifacts: Path,
    candidate_artifacts: Path,
    candidate_commit: str,
    replica: int,
    protected: bool,
    image_data_path: Path | None,
) -> dict[str, Any]:
    if COMMIT_PATTERN.fullmatch(candidate_commit) is None:
        raise RuntimeError("candidate commit must be 40 lowercase hexadecimal chars")
    reference_record = _load_reference()
    reference_identity = _reference_identity(reference_record)
    driver_lock_hash = _lock_hash()
    runner_evidence = _runner_evidence(
        protected=protected,
        image_data_path=image_data_path,
    )
    if runner_evidence["dependencyLockHash"] != driver_lock_hash:
        raise RuntimeError("measured dependency lock differs from checkout")
    with ExitStack() as stack:
        reference_runtime = stack.enter_context(
            installed_release_runtime(
                reference_artifacts,
                expected_commit=reference_identity["commit"],
                artifact_contract=BETA2_REFERENCE_RELEASE_CONTRACT,
            )
        )
        candidate_runtime = stack.enter_context(
            installed_release_runtime(
                candidate_artifacts,
                expected_commit=candidate_commit,
            )
        )
        if (
            _installed_identity(reference_runtime, REFERENCE_IDENTITY_FILES)
            != reference_identity
        ):
            raise RuntimeError("installed reference artifacts differ from the anchor")
        candidate_identity = _installed_identity(candidate_runtime)
        if candidate_identity["commit"] != candidate_commit:
            raise RuntimeError("installed candidate commit differs")
        if (
            protected
            and runner_evidence["invocation"]["workflowSha"] != candidate_commit
        ):
            raise RuntimeError("workflow commit differs from installed candidate")
        cases: dict[str, dict[str, Any]] = {runtime: {} for runtime in RUNTIMES}
        reference_failures: list[str] = []
        candidate_failures: list[str] = []
        runtimes = {
            "reference": reference_runtime,
            "candidate": candidate_runtime,
        }
        for runtime in RUNTIMES:
            for case in CASES:
                pairs: list[dict[str, Any]] = []
                for sample in range(1, SAMPLES + 1):
                    order = _subject_order(replica, case, sample)
                    measured: dict[str, dict[str, Any]] = {}
                    for subject in order:
                        result = _run_case(
                            runtime,
                            case,
                            1,
                            WARMUPS,
                            runtimes[subject],
                        )
                        measured[subject] = result["sampleResults"][0]
                    pairs.append(
                        {
                            "sample": sample,
                            "order": list(order),
                            "reference": measured["reference"],
                            "candidate": measured["candidate"],
                        }
                    )
                evidence, invalid_reference, invalid_candidate = _case_evidence(
                    runtime, case, pairs
                )
                cases[runtime][case] = evidence
                reference_failures.extend(invalid_reference)
                candidate_failures.extend(invalid_candidate)
        if _lock_hash() != driver_lock_hash:
            raise RuntimeError("installed driver dependency lock changed during run")

    outcome = (
        "invalid-reference"
        if reference_failures
        else "hard-failure"
        if candidate_failures
        else "pass"
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "kaji-paired-benchmark-replica",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "protected": protected,
        "protocolHash": _protocol_hash(),
        "replica": replica,
        "threshold": THRESHOLD,
        "runnerEvidence": runner_evidence,
        "referenceRecordSha256": _file_sha256(REFERENCE_PATH),
        "reference": reference_identity,
        "candidate": candidate_identity,
        "referenceReceiptSha256": _json_sha256(reference_identity),
        "candidateReceiptSha256": _json_sha256(candidate_identity),
        "cases": cases,
        "referenceFailures": reference_failures,
        "candidateFailures": candidate_failures,
        "hardFailures": [],
        "outcome": outcome,
        "passed": outcome == "pass",
    }
    report["reportReceiptSha256"] = _json_sha256(report)
    return report


def _validate_replica_report(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != REPORT_KEYS:
        raise RuntimeError("paired benchmark report has the wrong shape")
    receipt = value["reportReceiptSha256"]
    unsigned = {
        key: item for key, item in value.items() if key != "reportReceiptSha256"
    }
    if _validate_hash(receipt, "report receipt") != _json_sha256(unsigned):
        raise RuntimeError("paired benchmark report receipt does not match")
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["kind"] != "kaji-paired-benchmark-replica"
        or value["protected"] is not True
        or value["protocolHash"] != _protocol_hash()
        or type(value["replica"]) is not int
        or value["replica"] not in (1, 2, 3)
        or isinstance(value["threshold"], bool)
        or value["threshold"] != THRESHOLD
    ):
        raise RuntimeError("paired benchmark report identity is invalid")
    _validate_utc_timestamp(value["generatedAt"], "report generatedAt")
    reference_record = _load_reference()
    runner_evidence = _validate_runner_evidence(value["runnerEvidence"])
    if runner_evidence["dependencyLockHash"] != _lock_hash():
        raise RuntimeError("paired benchmark dependency lock differs from checkout")
    if value["referenceRecordSha256"] != _file_sha256(REFERENCE_PATH):
        raise RuntimeError("paired benchmark reference record receipt differs")
    reference_identity = _validate_identity(
        value["reference"], "reference", REFERENCE_IDENTITY_FILES
    )
    if reference_identity != _reference_identity(reference_record):
        raise RuntimeError("paired benchmark reference identity differs")
    candidate_identity = _validate_identity(value["candidate"], "candidate")
    if runner_evidence["invocation"]["workflowSha"] != candidate_identity["commit"]:
        raise RuntimeError("paired benchmark workflow commit differs from candidate")
    if value["referenceReceiptSha256"] != _json_sha256(reference_identity):
        raise RuntimeError("paired benchmark reference receipt differs")
    if value["candidateReceiptSha256"] != _json_sha256(candidate_identity):
        raise RuntimeError("paired benchmark candidate receipt differs")
    for failure_field in (
        "referenceFailures",
        "candidateFailures",
        "hardFailures",
    ):
        if type(value[failure_field]) is not list or any(
            not isinstance(item, str) for item in value[failure_field]
        ):
            raise RuntimeError(f"{failure_field} must be an array of strings")
    expected_outcome = (
        "invalid-reference"
        if value["referenceFailures"]
        else "hard-failure"
        if value["candidateFailures"] or value["hardFailures"]
        else "pass"
    )
    if value["outcome"] != expected_outcome or value["passed"] is not (
        expected_outcome == "pass"
    ):
        raise RuntimeError("paired benchmark terminal outcome is inconsistent")
    if expected_outcome == "invalid-reference":
        raise RuntimeError("paired benchmark reference evidence is invalid")
    if expected_outcome == "hard-failure":
        raise RuntimeError("paired benchmark candidate has a hard failure")
    cases = value["cases"]
    if type(cases) is not dict or set(cases) != set(RUNTIMES):
        raise RuntimeError("paired benchmark runtime coverage differs")
    for runtime in RUNTIMES:
        runtime_cases = cases[runtime]
        if type(runtime_cases) is not dict or set(runtime_cases) != set(CASES):
            raise RuntimeError(f"paired benchmark {runtime} case coverage differs")
        for case in CASES:
            evidence = runtime_cases[case]
            if type(evidence) is not dict or set(evidence) != {
                "pairs",
                "durationRatio",
                "maxRssRatio",
                "durationCrossed",
                "rssCrossed",
            }:
                raise RuntimeError(f"{runtime} {case} evidence has the wrong shape")
            if (
                isinstance(evidence["durationRatio"], bool)
                or not isinstance(evidence["durationRatio"], (int, float))
                or isinstance(evidence["maxRssRatio"], bool)
                or not isinstance(evidence["maxRssRatio"], (int, float))
                or type(evidence["durationCrossed"]) is not bool
                or type(evidence["rssCrossed"]) is not bool
            ):
                raise RuntimeError(f"{runtime} {case} derived evidence is invalid")
            expected, reference_failures, candidate_failures = _case_evidence(
                runtime, case, evidence["pairs"]
            )
            for sample, pair in enumerate(evidence["pairs"], 1):
                if pair["order"] != list(
                    _subject_order(value["replica"], case, sample)
                ):
                    raise RuntimeError(f"{runtime} {case} order is not counterbalanced")
            if reference_failures:
                raise RuntimeError(reference_failures[0])
            if candidate_failures:
                raise RuntimeError(candidate_failures[0])
            if evidence != expected:
                raise RuntimeError(f"{runtime} {case} derived evidence differs")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-artifacts-dir", required=True, type=Path)
    parser.add_argument("--candidate-artifacts-dir", required=True, type=Path)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--replica", required=True, type=int, choices=(1, 2, 3))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runner-image-data", type=Path)
    parser.add_argument("--protected", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.protected and args.runner_image_data is None:
        print(
            "FAIL: protected paired benchmark requires --runner-image-data",
            file=sys.stderr,
        )
        return 2
    try:
        report = _measure_replica(
            reference_artifacts=args.reference_artifacts_dir,
            candidate_artifacts=args.candidate_artifacts_dir,
            candidate_commit=args.candidate_commit,
            replica=args.replica,
            protected=args.protected,
            image_data_path=args.runner_image_data,
        )
        _write(args.output, report)
    except (OSError, RuntimeError, SystemExit) as error:
        message = str(error)
        print(
            message if message.startswith("FAIL:") else f"FAIL: {message}",
            file=sys.stderr,
        )
        return 1
    if not report["passed"]:
        for failure in (
            *report["referenceFailures"],
            *report["candidateFailures"],
            *report["hardFailures"],
        ):
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"PASS: paired benchmark replica {args.replica}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
