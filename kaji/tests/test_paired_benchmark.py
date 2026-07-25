from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "kaji" / "scripts"


def _load_script(name: str):
    scripts = str(SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}_{id(path)}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runner() -> dict[str, str]:
    return {
        "environment": "github-hosted",
        "os": "Darwin",
        "arch": "arm64",
        "platformVersion": "15.7.7",
        "imageOS": "macos15",
        "imageLabel": "macos-15-arm64",
        "imageVersion": "20260715.0234.1",
        "imageDataSha256": "a" * 64,
    }


def _invocation(replica: int) -> dict[str, Any]:
    return {
        "runId": 300_900_000,
        "runAttempt": 1,
        "job": "paired",
        "runnerName": f"GitHub Actions {replica}",
        "workflowRef": "enkyuan/alloy/.github/workflows/kaji.benchmark.yml@refs/heads/main",
        "workflowSha": "f" * 40,
    }


def _sample(
    case: str, duration: float, peak: float, *, runtime: str = "python"
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "durationMs": duration,
        "peakMiB": peak,
        "warmupRuns": 2,
    }
    values: dict[str, dict[str, Any]] = {
        "replay10k": {"eventsApplied": 10_000, "cursor": 10_000},
        "crossSession100": {
            "turns": 100,
            "maxActive": 2,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "sameSession25": {
            "turns": 25,
            "maxActive": 1,
            "coordinatorEntries": 0,
            "coordinatorWaiters": 0,
        },
        "toolBatch100": {"maxActive": 4, "calls": 100, "stuckCalls": 0},
        "context10kIterations5": {
            "historyEvents": 10_000,
            "fullHistoryScans": 1,
            "providerIterations": 5,
            "coldEvents": 10_000,
            "incrementalEvents": 21,
            "suffixCalls": 5,
            "copiedPayloadBytes": 0,
            "retainedTurns": 32,
            "turnIndexEntries": 32,
            "sentinelEntries": 1,
            "totalIndexEntries": 33,
            "maxVisitedTurnEntries": 32,
            "incrementalRssBytes": 1_024,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "crossSessionCommit100": {
            "sessions": 100,
            "commits": 100,
            "overlappingSessions": 99,
            "contiguousSessions": 100,
            "laneEntriesAfter": 0,
            "reservationEntriesAfter": 0,
        },
        "streamDeltas10k": {
            "characters": 10_000,
            "deltaEvents": 3,
            "inputFragments": 10_000,
            "deltaJoinOperations": 3,
            "responseJoinOperations": 1,
            "providerTextMaxBytes": 262_144,
            "providerResponseMaxBytes": 524_288,
            "completionEvents": 1,
            "completionEventsAfterFailure": 0,
            "timerLeaks": 0,
            "providerTaskLeaks": 0,
        },
        "toolArgDeltas10k": {
            "argumentBytes": 65_536,
            "responseMaxBytes": 524_288,
            "argumentFragments": 10_000,
            "rawFragments": 10_002,
            "fragmentJoins": 1,
            "overLimitBytes": 65_537,
            "overLimitRejectedBeforeParse": True,
            "iteratorLeaks": 0,
            "parserLeaks": 0,
            "providerTaskLeaks": 0,
        },
    }
    sample = {**common, **values[case]}
    if case == "toolBatch100" and runtime == "typescript":
        sample.update(
            {
                "batchRepetitions": 64,
                "calls": 6_400,
                "completed": 6_400,
            }
        )
    return sample


def _identity(commit: str, prefix: str) -> dict[str, Any]:
    return {
        "commit": commit,
        "releaseManifestSha256": prefix * 64,
        "artifacts": {
            "pythonWheel": {
                "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
                "sha256": chr(ord(prefix) + 1) * 64,
            },
            "pythonSdist": {
                "file": "kaji_sdk-0.2.0b1.tar.gz",
                "sha256": chr(ord(prefix) + 2) * 64,
            },
            "typescript": {
                "file": "kaji-sdk-0.2.0-beta.2.tgz",
                "sha256": chr(ord(prefix) + 3) * 64,
            },
        },
    }


def _complete_report(
    pair: Any,
    *,
    replica: int,
    duration_ratio: float = 1.0,
    rss_ratio: float = 1.0,
) -> dict[str, Any]:
    anchor = pair._load_reference()
    reference = pair._reference_identity(anchor)
    candidate = _identity("f" * 40, "1")
    cases: dict[str, dict[str, Any]] = {}
    for runtime in pair.RUNTIMES:
        cases[runtime] = {}
        for case in pair.CASES:
            pairs = []
            for sample_number in range(1, 6):
                reference_sample = _sample(case, 0.1, 1.0, runtime=runtime)
                candidate_sample = _sample(
                    case,
                    0.1 * duration_ratio,
                    1.0 * rss_ratio,
                    runtime=runtime,
                )
                pairs.append(
                    {
                        "sample": sample_number,
                        "order": list(
                            pair._subject_order(replica, case, sample_number)
                        ),
                        "reference": reference_sample,
                        "candidate": candidate_sample,
                    }
                )
            evidence, reference_failures, candidate_failures = pair._case_evidence(
                runtime, case, pairs
            )
            assert reference_failures == []
            assert candidate_failures == []
            cases[runtime][case] = evidence
    report = {
        "schemaVersion": 1,
        "kind": "kaji-beta-paired-benchmark-replica",
        "generatedAt": "2026-07-24T00:00:00+00:00",
        "protected": True,
        "protocolHash": pair._protocol_hash(),
        "replica": replica,
        "threshold": 1.2,
        "runnerEvidence": {
            "runner": _runner(),
            "versions": {
                "python": "3.11.9",
                "node": "v22.14.0",
                "bun": "1.3.11",
            },
            "dependencyLockHash": anchor["dependencyLockHash"],
            "invocation": _invocation(replica),
        },
        "referenceRecordSha256": pair._file_sha256(pair.REFERENCE_PATH),
        "reference": reference,
        "candidate": candidate,
        "referenceReceiptSha256": pair._json_sha256(reference),
        "candidateReceiptSha256": pair._json_sha256(candidate),
        "cases": cases,
        "referenceFailures": [],
        "candidateFailures": [],
        "hardFailures": [],
        "outcome": "pass",
        "passed": True,
    }
    report["reportReceiptSha256"] = pair._json_sha256(report)
    return report


def _reseal(pair: Any, report: dict[str, Any]) -> None:
    report["reportReceiptSha256"] = pair._json_sha256(
        {key: value for key, value in report.items() if key != "reportReceiptSha256"}
    )


@pytest.mark.parametrize("script", ["paired_benchmark.py", "aggregate_benchmarks.py"])
def test_paired_benchmark_clis_support_python_safe_path(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--help"],
        cwd=ROOT,
        env={**os.environ, "PYTHONSAFEPATH": "1"},
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert "usage:" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


def test_reference_anchor_is_exact_and_contains_no_runtime_paths() -> None:
    pair = _load_script("paired_benchmark.py")

    anchor = pair._load_reference()

    assert anchor["commit"] == "5ed864c0098a4e8c5d0c065c787947aba9603860"
    assert (
        anchor["releaseManifestSha256"]
        == "fc0527cb950600f7d1984abdfbc4216996408ec0ac20ad28c0ddd9d64265d6b4"
    )
    assert (
        anchor["dependencyLockHash"]
        == "1bed0911da7da85aa527a059eec2d6c560d80f3cff699ec98468eb560168dabc"
        == pair._lock_hash()
    )
    assert anchor["githubArtifact"] == {
        "runId": 30081423771,
        "artifactId": 8592160276,
        "name": "kaji-beta-artifacts",
        "digest": (
            "sha256:03c122caacce77608eded3511e56183f022739164d387a28a83c27a06a86e721"
        ),
        "expiresAt": "2026-10-22T09:07:42Z",
    }
    assert anchor["artifacts"] == {
        "pythonWheel": {
            "file": "kaji_sdk-0.2.0b1-py3-none-any.whl",
            "sha256": (
                "2a092b49c2c87666db9178bb8233f0b42551b683fa69475739582a8678ff0945"
            ),
        },
        "pythonSdist": {
            "file": "kaji_sdk-0.2.0b1.tar.gz",
            "sha256": (
                "58540d729bc1eb64fd02c0bc153fdbcf826a997e2ef91c4bc06254e94079be1d"
            ),
        },
        "typescript": {
            "file": "kaji-sdk-0.2.0-beta.2.tgz",
            "sha256": (
                "266c9931456bef6f1abe9bbc96c6407d8ec98240ffdb164bad1f7785ca44d369"
            ),
        },
    }
    assert "resolved" not in json.dumps(anchor).lower()


def test_subject_order_is_deterministic_and_counterbalanced() -> None:
    pair = _load_script("paired_benchmark.py")

    first = [pair._subject_order(1, "replay10k", sample) for sample in range(1, 6)]
    second = [pair._subject_order(2, "replay10k", sample) for sample in range(1, 6)]

    assert first == [
        ("candidate", "reference"),
        ("reference", "candidate"),
        ("candidate", "reference"),
        ("reference", "candidate"),
        ("candidate", "reference"),
    ]
    assert second == [tuple(reversed(order)) for order in first]


def test_case_evidence_keeps_raw_pairs_and_exact_threshold_passes() -> None:
    pair = _load_script("paired_benchmark.py")
    pairs = [
        {
            "sample": index,
            "order": list(pair._subject_order(1, "replay10k", index)),
            "reference": _sample("replay10k", 10.0, 10.0),
            "candidate": _sample("replay10k", 12.0, 12.0),
        }
        for index in range(1, 6)
    ]

    evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", pairs
    )

    assert reference_failures == []
    assert candidate_failures == []
    assert evidence["durationRatio"] == 1.2
    assert evidence["maxRssRatio"] == 1.2
    assert evidence["durationCrossed"] is False
    assert evidence["rssCrossed"] is False
    assert len(evidence["pairs"]) == 5


def test_case_evidence_rejects_incomplete_tool_batch_repetitions() -> None:
    pair = _load_script("paired_benchmark.py")
    pairs: list[dict[str, Any]] = [
        {
            "sample": index,
            "order": list(pair._subject_order(1, "toolBatch100", index)),
            "reference": _sample("toolBatch100", 10.0, 10.0, runtime="typescript"),
            "candidate": _sample("toolBatch100", 10.0, 10.0, runtime="typescript"),
        }
        for index in range(1, 6)
    ]
    pairs[0]["candidate"]["completed"] = 6_399

    _, reference_failures, candidate_failures = pair._case_evidence(
        "typescript", "toolBatch100", pairs
    )

    assert reference_failures == []
    assert any("completed" in failure for failure in candidate_failures)


def test_case_evidence_rejects_a_masked_pairwise_rss_crossing() -> None:
    pair = _load_script("paired_benchmark.py")
    pairs = [
        {
            "sample": index,
            "order": list(pair._subject_order(1, "replay10k", index)),
            "reference": _sample("replay10k", 10.0, 10.0 if index == 1 else 100.0),
            "candidate": _sample("replay10k", 10.0, 12.00001 if index == 1 else 100.0),
        }
        for index in range(1, 6)
    ]

    evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", pairs
    )

    assert reference_failures == []
    assert evidence["pairs"][0]["rssRatio"] > 1.2
    assert evidence["maxRssRatio"] > 1.2
    assert any("peak RSS ratio" in failure for failure in candidate_failures)


def test_case_evidence_makes_relative_rss_crossing_a_hard_failure() -> None:
    pair = _load_script("paired_benchmark.py")
    pairs = [
        {
            "sample": index,
            "order": list(pair._subject_order(1, "replay10k", index)),
            "reference": _sample("replay10k", 10.0, 10.0),
            "candidate": _sample("replay10k", 10.0, 12.00001),
        }
        for index in range(1, 6)
    ]

    evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", pairs
    )

    assert reference_failures == []
    assert evidence["maxRssRatio"] > 1.2
    assert any("peak RSS ratio" in failure for failure in candidate_failures)


@pytest.mark.parametrize(
    ("subject", "expected"),
    [("reference", "reference:"), ("candidate", "candidate:")],
)
def test_case_evidence_reuses_semantic_validator_for_both_subjects(
    subject: str, expected: str
) -> None:
    pair = _load_script("paired_benchmark.py")
    pairs: list[dict[str, Any]] = [
        {
            "sample": index,
            "order": list(pair._subject_order(1, "replay10k", index)),
            "reference": _sample("replay10k", 10.0, 10.0),
            "candidate": _sample("replay10k", 10.0, 10.0),
        }
        for index in range(1, 6)
    ]
    pairs[0][subject]["eventsApplied"] = 9_999

    _evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", pairs
    )

    failures = reference_failures if subject == "reference" else candidate_failures
    assert any(
        failure.startswith(expected) and "eventsApplied" in failure
        for failure in failures
    )


def test_protocol_hash_excludes_product_sources_and_paths_from_receipts() -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)

    assert all("src/kaji" not in path.as_posix() for path in pair.PROTOCOL_INPUTS)
    assert all("kaji/ts/src" not in path.as_posix() for path in pair.PROTOCOL_INPUTS)
    assert pair.HASH_PATTERN.fullmatch(report["protocolHash"])
    assert "resolvedPackage" not in json.dumps(report)


def test_replica_measurement_uses_two_isolated_artifacts_and_adjacent_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pair = _load_script("paired_benchmark.py")
    anchor = pair._load_reference()
    reference_identity = pair._reference_identity(anchor)
    candidate_identity = _identity("f" * 40, "1")
    reference_runtime = SimpleNamespace(label="reference")
    candidate_runtime = SimpleNamespace(label="candidate")
    opened: list[tuple[Path, str]] = []

    class RuntimeContext:
        def __init__(self, runtime: Any) -> None:
            self.runtime = runtime

        def __enter__(self) -> Any:
            return self.runtime

        def __exit__(self, *_args: object) -> None:
            return None

    def installed(artifacts: Path, *, expected_commit: str) -> RuntimeContext:
        opened.append((artifacts, expected_commit))
        runtime = (
            reference_runtime
            if expected_commit == reference_identity["commit"]
            else candidate_runtime
        )
        return RuntimeContext(runtime)

    measured: list[tuple[str, str, int, int, str]] = []

    def run_case(
        runtime: str, case: str, samples: int, warmups: int, installed: Any
    ) -> dict[str, Any]:
        measured.append((runtime, case, samples, warmups, installed.label))
        sample = _sample(case, 0.1, 1.0, runtime=runtime)
        return {"sampleResults": [sample]}

    monkeypatch.setattr(pair, "installed_release_runtime", installed)
    monkeypatch.setattr(
        pair,
        "_installed_identity",
        lambda runtime: (
            reference_identity if runtime is reference_runtime else candidate_identity
        ),
    )
    monkeypatch.setattr(pair, "_run_case", run_case)
    monkeypatch.setattr(pair, "_lock_hash", lambda: anchor["dependencyLockHash"])
    monkeypatch.setattr(
        pair,
        "_runner_evidence",
        lambda **_kwargs: {
            "runner": _runner(),
            "versions": {
                "python": "3.11.9",
                "node": "v22.14.0",
                "bun": "1.3.11",
            },
            "dependencyLockHash": anchor["dependencyLockHash"],
            "invocation": _invocation(1),
        },
    )
    reference_dir = tmp_path / "reference"
    candidate_dir = tmp_path / "candidate"

    report = pair._measure_replica(
        reference_artifacts=reference_dir,
        candidate_artifacts=candidate_dir,
        candidate_commit="f" * 40,
        replica=1,
        protected=True,
        image_data_path=tmp_path / "imagedata.json",
    )

    assert opened == [
        (reference_dir, reference_identity["commit"]),
        (candidate_dir, "f" * 40),
    ]
    assert [(samples, warmups) for _, _, samples, warmups, _ in measured] == [
        (1, 2)
    ] * (len(pair.RUNTIMES) * len(pair.CASES) * 10)
    expected_subjects = [
        subject
        for sample in range(1, 6)
        for subject in pair._subject_order(1, "replay10k", sample)
    ]
    assert [subject for _, _, _, _, subject in measured[:10]] == expected_subjects
    assert report["reference"] == reference_identity
    assert report["candidate"] == candidate_identity
    assert report["outcome"] == "pass"
    assert report["passed"] is True


def test_replica_measurement_rejects_dependency_lock_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pair = _load_script("paired_benchmark.py")
    monkeypatch.setattr(pair, "_lock_hash", lambda: "0" * 64)
    monkeypatch.setattr(
        pair,
        "_runner_evidence",
        lambda **_kwargs: pytest.fail("runner measured after lock mismatch"),
    )

    with pytest.raises(RuntimeError, match="dependency lock differs"):
        pair._measure_replica(
            reference_artifacts=tmp_path / "reference",
            candidate_artifacts=tmp_path / "candidate",
            candidate_commit="f" * 40,
            replica=1,
            protected=True,
            image_data_path=tmp_path / "imagedata.json",
        )


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [
        ((1.2, 1.2, 1.2), "pass"),
        ((1.200001, 1.200001, 1.200001), "regression"),
        ((1.0, 1.200001, 1.200001), "inconclusive"),
    ],
)
def test_aggregator_requires_unanimous_three_replica_verdict(
    ratios: tuple[float, float, float], expected: str
) -> None:
    pair = _load_script("paired_benchmark.py")
    aggregate = _load_script("aggregate_benchmarks.py")
    reports = [
        _complete_report(pair, replica=index, duration_ratio=ratio)
        for index, ratio in enumerate(ratios, 1)
    ]

    result = aggregate._aggregate(reports)

    assert result["cases"]["python"]["replay10k"]["durationVerdict"] == expected
    assert result["passed"] is (expected == "pass")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda reports: reports.pop(),
        lambda reports: reports[2].__setitem__("replica", 2),
        lambda reports: reports[2].__setitem__("protocolHash", "0" * 64),
        lambda reports: reports[2]["candidate"].__setitem__("commit", "e" * 40),
        lambda reports: reports[2]["cases"]["python"].pop("replay10k"),
        lambda reports: reports[2]["cases"]["python"]["replay10k"]["pairs"][0][
            "candidate"
        ].__setitem__("durationMs", 9.0),
    ],
    ids=(
        "missing-replica",
        "duplicate-replica",
        "protocol-mismatch",
        "candidate-mismatch",
        "case-mismatch",
        "tamper",
    ),
)
def test_aggregator_rejects_incomplete_or_inconsistent_evidence(mutate: Any) -> None:
    pair = _load_script("paired_benchmark.py")
    aggregate = _load_script("aggregate_benchmarks.py")
    reports = [_complete_report(pair, replica=index) for index in range(1, 4)]
    mutate(reports)

    with pytest.raises(RuntimeError):
        aggregate._aggregate(reports)


def test_replica_validator_recomputes_semantics_even_with_new_receipt() -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)
    sample = report["cases"]["python"]["replay10k"]["pairs"][0]["candidate"]
    sample["eventsApplied"] = 9_999
    _reseal(pair, report)

    with pytest.raises(RuntimeError, match="eventsApplied"):
        pair._validate_replica_report(report)


def test_replica_validator_rejects_malformed_nested_evidence_with_new_receipt() -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)
    report["cases"]["python"]["replay10k"]["pairs"] = "not-an-array"
    _reseal(pair, report)

    with pytest.raises(RuntimeError, match="five paired samples"):
        pair._validate_replica_report(report)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("warmupRuns", None, "warmupRuns"),
        ("durationMs", 0.0, "positive"),
        ("peakMiB", 0.0, "positive"),
    ],
)
def test_replica_validator_rejects_forged_candidate_sample_metadata(
    field: str, value: object, expected: str
) -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)
    sample = report["cases"]["python"]["replay10k"]["pairs"][0]["candidate"]
    if value is None:
        sample.pop(field)
    else:
        sample[field] = value
    _reseal(pair, report)

    with pytest.raises(RuntimeError, match=expected):
        pair._validate_replica_report(report)


def test_replica_validator_labels_reference_failure_as_invalid_evidence() -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)
    case = report["cases"]["python"]["replay10k"]
    case["pairs"][0]["reference"]["eventsApplied"] = 9_999
    evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", case["pairs"]
    )
    report["cases"]["python"]["replay10k"] = evidence
    report["referenceFailures"] = reference_failures
    report["candidateFailures"] = candidate_failures
    report["outcome"] = "invalid-reference"
    report["passed"] = False
    _reseal(pair, report)

    with pytest.raises(RuntimeError, match="reference evidence is invalid"):
        pair._validate_replica_report(report)


def test_aggregator_blocks_one_replica_relative_rss_failure() -> None:
    pair = _load_script("paired_benchmark.py")
    aggregate = _load_script("aggregate_benchmarks.py")
    reports = [_complete_report(pair, replica=index) for index in range(1, 4)]
    case = reports[0]["cases"]["python"]["replay10k"]
    for sample in case["pairs"]:
        sample["candidate"]["peakMiB"] = 1.200001
    evidence, reference_failures, candidate_failures = pair._case_evidence(
        "python", "replay10k", case["pairs"]
    )
    assert reference_failures == []
    reports[0]["cases"]["python"]["replay10k"] = evidence
    reports[0]["candidateFailures"] = candidate_failures
    reports[0]["outcome"] = "hard-failure"
    reports[0]["passed"] = False
    _reseal(pair, reports[0])

    with pytest.raises(RuntimeError, match="candidate has a hard failure"):
        aggregate._aggregate(reports)


def test_aggregator_rejects_runner_toolchain_mismatch_with_valid_receipts() -> None:
    pair = _load_script("paired_benchmark.py")
    aggregate = _load_script("aggregate_benchmarks.py")
    reports = [_complete_report(pair, replica=index) for index in range(1, 4)]
    reports[2]["runnerEvidence"]["versions"]["bun"] = "1.3.12"
    _reseal(pair, reports[2])

    with pytest.raises(RuntimeError, match="versions"):
        aggregate._aggregate(reports)


def test_replica_validator_rejects_unanchored_dependency_lock() -> None:
    pair = _load_script("paired_benchmark.py")
    report = _complete_report(pair, replica=1)
    report["runnerEvidence"]["dependencyLockHash"] = "0" * 64
    _reseal(pair, report)

    with pytest.raises(RuntimeError, match="dependency lock differs"):
        pair._validate_replica_report(report)


def test_aggregator_accepts_repeated_diagnostic_runner_names() -> None:
    pair = _load_script("paired_benchmark.py")
    aggregate = _load_script("aggregate_benchmarks.py")
    reports = [_complete_report(pair, replica=index) for index in range(1, 4)]
    reports[2]["runnerEvidence"]["invocation"]["runnerName"] = reports[1][
        "runnerEvidence"
    ]["invocation"]["runnerName"]
    _reseal(pair, reports[2])

    result = aggregate._aggregate(reports)

    assert result["passed"] is True
    assert set(result["replicas"]) == {"1", "2", "3"}


def test_paired_benchmark_cli_preserves_safe_operator_failure(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "paired_benchmark.py"),
            "--reference-artifacts-dir",
            str(tmp_path / "reference"),
            "--candidate-artifacts-dir",
            str(tmp_path / "candidate"),
            "--candidate-commit",
            "invalid",
            "--replica",
            "1",
            "--output",
            str(tmp_path / "report.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 1
    assert "candidate commit must be 40 lowercase hexadecimal chars" in completed.stderr
